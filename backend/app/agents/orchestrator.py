"""Orchestrator (CLAUDE.md Agents #1): the single chat entrypoint.

Pipeline for a turn (see CLAUDE.md "Pipeline for a turn"):
  ANALYSIS / DATA_PREVIEW / EXPLAIN_WHY
      -> plan_queries -> execute_plan (SQL generation + validation + execution,
         with sql_agent.regenerate_sql wired as the executor's self-correction
         callback) -> deterministic analytics -> report_agent.build_report (or
         heuristic_report if AI disabled) -> explanation_agent.explain_result
         -> assemble ChatResponse
  REPORT_EDIT
      -> load the last report from `history` -> report_edit_agent.edit_report
         -> apply_structural_operations and/or a small follow-up query-plan
         pipeline, merged into the existing report -> ChatResponse
  GREETING_OR_OTHER
      -> a static nudge, no report

`history` shape expected by this module: a list of prior-turn dicts, each
optionally carrying a `role` ("user"/"assistant"), `content` (str), and for
assistant turns that produced/updated a report, a `report` key holding that
turn's ReportSpec as a plain dict (`ReportSpec.model_dump()`). The caller
(API layer) is responsible for persisting/assembling this list across turns;
the orchestrator only reads it. The most recent assistant turn carrying a
non-null `report` is used as the REPORT_EDIT target.

Never let one node's failure kill the whole turn — a partial report with
some sections plus an insight noting what worked is returned rather than a
hard error; only if EVERY node fails does this return a clear, honest error
message instead of a fabricated report.

When app.ai.openai_client.is_enabled() is False, SQL cannot be generated
from natural language at all (sql_agent.generate_sql requires AI — see its
docstring), so an ANALYSIS-shaped turn cannot run. In that case this returns
a ChatResponse with error="ai_disabled" pointing the user at the zero-LLM
recommended-reports feature (app/reports/recommended.py / app/api/
recommended.py, owned by another agent — not built here).
"""
from __future__ import annotations

import uuid
from typing import Any

from app.agents import explanation_agent, report_agent, report_edit_agent, sql_agent
from app.agents.analytics_summary import build_analytics_summary
from app.agents.query_planner_agent import plan_queries
from app.ai.openai_client import is_enabled
from app.core.config import get_settings
from app.core.logging_config import ai_logger
from app.query_engine.executor import execute_plan
from app.query_engine.plan import QueryPlan
from app.schemas.report import ChatResponse, ReportSpec

settings = get_settings()

AI_DISABLED_MESSAGE = (
    "AI features are disabled because no OPENAI_API_KEY is configured, so I can't turn a "
    "new question into SQL right now. You can still explore the data with one of the "
    "one-click Recommended Reports on the home screen — those run with zero AI and work "
    "with no API key at all."
)


def _known_tables() -> set[str] | None:
    """The security gate checks generated SQL's tables against the real,
    cached set of tables that exist in this database (see
    app.semantic_layer.metadata_cache, refreshed at boot and kept in
    memory — no extra DB round trip needed here). This turns an
    LLM-invented table name (e.g. "orders" when the real table is
    "sales_invoices") into an immediate, clear "unknown table" validation
    rejection that feeds back into SQL regeneration, instead of only
    surfacing as an opaque Postgres UndefinedTableError after execution.
    Falls back to None (check disabled) if the cache hasn't been populated
    yet for some reason, so this never blocks a turn."""
    from app.semantic_layer.metadata_cache import get_cached_metadata

    tables = get_cached_metadata().get("tables")
    if not tables:
        return None
    return set(tables.keys())


async def _run_query_pipeline(question: str, conversation_context: list[dict] | None, session=None) -> QueryPlan:
    """Schema retrieval -> plan -> SQL generation -> validated execution with
    bounded self-correction retry. Requires AI (SQL generation has no
    deterministic fallback) — raises RuntimeError if AI is disabled."""
    if not is_enabled():
        raise RuntimeError("ai_disabled")

    plan = await plan_queries(question, conversation_context, session=session)

    # Semantic metadata is re-fetched per node inside sql_agent via a shared
    # slice; for simplicity and to avoid N redundant retrieval calls, fetch
    # one metadata slice for the whole question and reuse it for every node
    # (nodes of a single turn are near-always about the same tables).
    #
    # retrieve_relevant_schema is a deterministic, in-process-cache-backed
    # lookup (see app/semantic_layer/retrieval.py) — it does NOT actually
    # need a live DB session (the `session` param is accepted only for
    # backward compatibility and is ignored internally), so this must run
    # unconditionally. A previous version of this code gated the call behind
    # `if session is not None`, which meant every real call from the API
    # layer (app/api/chat.py never passes a session) silently got an EMPTY
    # metadata_context — the SQL Generation Agent then had zero real
    # table/column names to work from and hallucinated nonexistent tables
    # (e.g. "orders", "payments", "customers.revenue") that the security
    # gate correctly rejected but the LLM never recovered from. Verified live
    # against a real OpenAI key: this was a genuine end-to-end integration
    # bug, not just a theoretical one.
    from app.semantic_layer.retrieval import retrieve_relevant_schema

    try:
        metadata_context = await retrieve_relevant_schema(session, question)
    except Exception:  # noqa: BLE001
        metadata_context = {}

    for node in plan.nodes:
        try:
            node.sql = await sql_agent.generate_sql(node, metadata_context)
        except Exception as exc:  # noqa: BLE001
            ai_logger.error("sql_generation_failed node=%s error=%s", node.id, exc)
            node.status = "error"
            node.error = f"SQL generation failed: {exc}"

    async def regenerate(node, error_message: str) -> str:
        return await sql_agent.regenerate_sql(node, error_message, metadata_context)

    plan = await execute_plan(
        plan,
        known_tables=_known_tables(),
        regenerate=regenerate,
        max_retry=settings.SQL_MAX_RETRY,
    )
    return plan


def _last_report_from_history(history: list[dict] | None) -> dict | None:
    if not history:
        return None
    for turn in reversed(history):
        report = turn.get("report")
        if report:
            return report
    return None


def _conversation_id(conversation_id: str | None) -> str:
    return conversation_id or str(uuid.uuid4())


async def _run_analysis_pipeline(
    question: str, conversation_id: str, history: list[dict] | None, intent: str, session=None
) -> ChatResponse:
    try:
        plan = await _run_query_pipeline(question, history, session=session)
    except RuntimeError as exc:
        if str(exc) == "ai_disabled":
            return ChatResponse(
                conversation_id=conversation_id,
                message=AI_DISABLED_MESSAGE,
                intent=intent,
                report=None,
                error="ai_disabled",
            )
        raise

    if not plan.nodes or all(n.status != "success" for n in plan.nodes):
        errors = "; ".join(n.error or "unknown error" for n in plan.nodes if n.error) or "No queries could be executed."
        return ChatResponse(
            conversation_id=conversation_id,
            message=f"I couldn't answer that question — every query failed. Details: {errors}",
            intent=intent,
            report=None,
            error="query_failed",
        )

    analytics_summary = build_analytics_summary(plan)
    report = await report_agent.build_report(question, plan, analytics_summary)
    message = await explanation_agent.explain_result(question, report)

    return ChatResponse(
        conversation_id=conversation_id,
        message=message,
        intent=intent,
        report=report,
        error=None,
    )


async def _run_report_edit_pipeline(
    message: str, conversation_id: str, history: list[dict] | None, session=None
) -> ChatResponse:
    previous_report = _last_report_from_history(history)
    if previous_report is None:
        # Nothing to edit — treat as a fresh analysis question instead of erroring.
        return await _run_analysis_pipeline(message, conversation_id, history, "ANALYSIS", session=session)

    edit_plan = await report_edit_agent.edit_report(previous_report, message)

    updated_report_dict = previous_report
    if edit_plan.get("structural_ops"):
        updated_report = report_edit_agent.apply_structural_operations(
            previous_report, edit_plan["structural_ops"]
        )
        updated_report_dict = updated_report.model_dump()

    if not edit_plan.get("needs_requery"):
        return ChatResponse(
            conversation_id=conversation_id,
            message="Updated the report as requested.",
            intent="REPORT_EDIT",
            report=ReportSpec(**updated_report_dict),
            error=None,
        )

    requery_description = edit_plan.get("requery_description") or message
    try:
        plan = await _run_query_pipeline(requery_description, history, session=session)
    except RuntimeError as exc:
        if str(exc) == "ai_disabled":
            return ChatResponse(
                conversation_id=conversation_id,
                message=AI_DISABLED_MESSAGE,
                intent="REPORT_EDIT",
                report=ReportSpec(**updated_report_dict),
                error="ai_disabled",
            )
        raise

    if not plan.nodes or all(n.status != "success" for n in plan.nodes):
        # The new data couldn't be fetched — return the (possibly structurally
        # edited) existing report rather than fabricating the requested addition.
        return ChatResponse(
            conversation_id=conversation_id,
            message="I updated what I could, but couldn't fetch the additional data you asked for.",
            intent="REPORT_EDIT",
            report=ReportSpec(**updated_report_dict),
            error=None,
        )

    analytics_summary = build_analytics_summary(plan)
    new_sections_report = await report_agent.build_report(requery_description, plan, analytics_summary)

    merged = dict(updated_report_dict)
    merged["kpis"] = list(updated_report_dict.get("kpis", [])) + [k.model_dump() if hasattr(k, "model_dump") else k for k in new_sections_report.kpis]
    merged["charts"] = list(updated_report_dict.get("charts", [])) + [c.model_dump() if hasattr(c, "model_dump") else c for c in new_sections_report.charts]
    merged["tables"] = list(updated_report_dict.get("tables", [])) + [t.model_dump() if hasattr(t, "model_dump") else t for t in new_sections_report.tables]
    new_layout_entries = [
        entry.model_dump() if hasattr(entry, "model_dump") else entry for entry in new_sections_report.layout
    ]
    merged["layout"] = list(updated_report_dict.get("layout", [])) + new_layout_entries
    merged["query_trace"] = list(updated_report_dict.get("query_trace", [])) + [
        q.model_dump() if hasattr(q, "model_dump") else q for q in new_sections_report.query_trace
    ]

    merged_report = ReportSpec(**merged)
    message_text = await explanation_agent.explain_result(requery_description, merged_report)

    return ChatResponse(
        conversation_id=conversation_id,
        message=message_text,
        intent="REPORT_EDIT",
        report=merged_report,
        error=None,
    )


async def handle_chat_turn(
    message: str, conversation_id: str | None, history: list[dict], session=None
) -> ChatResponse:
    """The single chat entrypoint. `session` is an optional AsyncSession
    (e.g. app.db.session.get_readonly_db / get_db) used for semantic
    metadata retrieval; callers that don't have one may omit it (schema
    retrieval degrades gracefully — see _run_query_pipeline)."""
    conversation_id = _conversation_id(conversation_id)
    has_active_report = _last_report_from_history(history) is not None

    intent = await explanation_agent.classify_intent(message, has_active_report)

    if intent == "GREETING_OR_OTHER":
        return ChatResponse(
            conversation_id=conversation_id,
            message=(
                "Hi! Ask me anything about your business — for example: "
                '"Show total revenue this month", "Compare September sales and purchase", '
                '"Top 10 customers by revenue", or "Show delayed deliveries".'
            ),
            intent=intent,
            report=None,
            error=None,
        )

    if intent == "REPORT_EDIT":
        return await _run_report_edit_pipeline(message, conversation_id, history, session=session)

    # ANALYSIS, DATA_PREVIEW, EXPLAIN_WHY all go through the same query
    # pipeline; DATA_PREVIEW/EXPLAIN_WHY differ only in how the frontend
    # renders the response (raw table vs deeper narrative), both need real data.
    return await _run_analysis_pipeline(message, conversation_id, history, intent, session=session)


__all__ = ["handle_chat_turn"]
