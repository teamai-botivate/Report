"""Executes a QueryPlan DAG: validates each node's SQL via the security gate, runs it
against the read-only engine, records timing/row counts, retries via SQL regeneration
on failure (up to SQL_MAX_RETRY), and writes an audit log row for every attempt.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

from sqlalchemy import text

from app.core.config import get_settings
from app.core.logging_config import sql_logger
from app.db.session import ReadonlySessionLocal, AsyncSessionLocal
from app.models.audit import SQLAuditLog
from app.query_engine.plan import QueryPlan, QueryPlanNode
from app.security.sql_guard import validate_sql_safe

settings = get_settings()

RegenerateFn = Callable[[QueryPlanNode, str], Awaitable[str]]
"""Given a failed node and the error message, return a corrected SQL string
(implemented by the SQL Generation Agent's error-recovery path)."""


async def _audit(node: QueryPlanNode, status: str, reason: str | None = None) -> None:
    try:
        async with AsyncSessionLocal() as session:
            session.add(
                SQLAuditLog(
                    node_id=node.id,
                    question=node.description,
                    sql_text=node.sql or "",
                    status=status,
                    rejection_reason=reason,
                    row_count=node.row_count,
                    elapsed_ms=node.elapsed_ms,
                    tables_referenced=",".join(node.tables_referenced) if node.tables_referenced else None,
                )
            )
            await session.commit()
    except Exception:  # noqa: BLE001 - audit logging must never break execution
        sql_logger.exception("Failed to write SQL audit log for node %s", node.id)


async def _run_node_sql(node: QueryPlanNode, known_tables: set[str] | None) -> None:
    validation = validate_sql_safe(node.sql or "", known_tables=known_tables)
    if not validation.ok:
        node.status = "error"
        node.error = validation.reason
        await _audit(node, "rejected", validation.reason)
        return

    node.sql = validation.sql
    node.tables_referenced = validation.tables_referenced

    start = time.perf_counter()
    try:
        async with ReadonlySessionLocal() as session:
            result = await session.execute(text(validation.sql))
            rows = [dict(r._mapping) for r in result.fetchall()]
        node.rows = rows
        node.row_count = len(rows)
        node.status = "success"
        node.elapsed_ms = (time.perf_counter() - start) * 1000
        await _audit(node, "executed")
    except Exception as exc:  # noqa: BLE001
        node.status = "error"
        node.error = str(exc)
        node.elapsed_ms = (time.perf_counter() - start) * 1000
        await _audit(node, "error", str(exc))


async def execute_plan(
    plan: QueryPlan,
    *,
    known_tables: set[str] | None = None,
    regenerate: RegenerateFn | None = None,
    max_retry: int | None = None,
) -> QueryPlan:
    """Run every node in the plan, respecting dependency batches, with retry-on-error."""
    max_retry = max_retry if max_retry is not None else settings.SQL_MAX_RETRY

    for batch in plan.topological_batches():
        await asyncio.gather(*(_run_node_sql(node, known_tables) for node in batch))

        if regenerate is not None:
            for node in batch:
                attempt = 0
                while node.status == "error" and attempt < max_retry:
                    attempt += 1
                    node.retry_count = attempt
                    try:
                        new_sql = await regenerate(node, node.error or "unknown error")
                    except Exception as exc:  # noqa: BLE001
                        node.error = f"regeneration failed: {exc}"
                        break
                    node.sql = new_sql
                    node.status = "pending"
                    await _run_node_sql(node, known_tables)

    return plan
