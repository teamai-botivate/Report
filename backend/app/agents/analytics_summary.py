"""Deterministic analytics summary builder (CLAUDE.md Analytics Agent, #6).

Runs the LLM-free deterministic helpers in app/analytics/engine.py over an
executed QueryPlan's node rows to produce a plain-Python summary dict that
report_agent.py consumes when composing insights/KPIs. Never calls the LLM —
every number here is Python arithmetic over already-validated, already-
executed query results.
"""
from __future__ import annotations

from typing import Any

from app.analytics.engine import safe_pct_change, scalar_from_single_row
from app.query_engine.plan import QueryPlan, QueryPlanNode


def _single_scalar_summary(node: QueryPlanNode) -> Any:
    """If a node's result is a single row, summarize it as either one scalar
    (single column) or the row dict itself (multiple columns) — mirrors the
    shape a human would want to read back in a debug/insight context."""
    if not node.rows or len(node.rows) != 1:
        return None
    row = node.rows[0]
    if len(row) == 1:
        return scalar_from_single_row(node.rows)
    return row


def build_analytics_summary(plan: QueryPlan) -> dict[str, Any]:
    """Deterministic post-query summary over REAL node results.

    Shape:
    {
      "nodes": {node_id: {"description":..., "row_count":..., "scalar": <value or None>}},
      "comparisons": [{"node_a": id, "node_b": id, "pct_change": float|None}, ...]
    }

    `comparisons` is populated heuristically: any two successful single-row/
    single-column nodes are offered as a pairwise pct-change candidate so the
    Report Agent (or its heuristic fallback) can surface a delta without ever
    computing it itself.
    """
    summary: dict[str, Any] = {"nodes": {}, "comparisons": []}
    successful = [n for n in plan.nodes if n.status == "success"]

    scalar_nodes: list[tuple[QueryPlanNode, Any]] = []
    for node in successful:
        scalar = _single_scalar_summary(node)
        summary["nodes"][node.id] = {
            "description": node.description,
            "row_count": node.row_count,
            "scalar": scalar,
        }
        if isinstance(scalar, (int, float)):
            scalar_nodes.append((node, scalar))

    for i in range(len(scalar_nodes)):
        for j in range(i + 1, len(scalar_nodes)):
            node_a, value_a = scalar_nodes[i]
            node_b, value_b = scalar_nodes[j]
            pct = safe_pct_change(value_a, value_b)
            summary["comparisons"].append(
                {
                    "node_a": node_a.id,
                    "node_b": node_b.id,
                    "value_a": value_a,
                    "value_b": value_b,
                    "pct_change": pct,
                }
            )

    return summary


__all__ = ["build_analytics_summary"]
