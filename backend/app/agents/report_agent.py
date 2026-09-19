"""Report Agent (CLAUDE.md Agents #7): the core of the conversational-report
product direction. Takes ALL successful query-plan node results for a turn +
the deterministic analytics summary, and produces ONE structured `ReportSpec`
(title/subtitle/kpis/charts/tables/insights/layout) via one structured-output
call. The LLM only ever decides *which node feeds which section, what to call
it, and how to lay it out* — every KPI value, chart data point, and table row
is copied verbatim in Python (`_materialize_report`) from the already-
validated, already-executed query result, never trusted from the LLM's own
echo (see CLAUDE.md known-bug #1: a KPI once showed SUM instead of COUNT
because the wrong column was picked — `_kpi_scalar` below is the fix).

Has a deterministic `heuristic_report()` fallback for when AI is disabled.
"""
from __future__ import annotations

import uuid
from typing import Any

from app.ai.chart_image_client import generate_full_report_image
from app.ai.image_client import generate_decorative_image
from app.ai.openai_client import is_enabled, structured_completion
from app.query_engine.plan import QueryPlan, QueryPlanNode
from app.schemas.report import ReportSpec

REPORT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "subtitle": {"type": "string"},
        "sections": {
            "type": "array",
            "description": "One entry per query node to surface in the report, in display order.",
            "items": {
                "type": "object",
                "properties": {
                    "source_node_id": {"type": "string", "description": "must match one of the provided node ids"},
                    "render_as": {
                        "type": "string",
                        "enum": [
                            "kpi", "kpi_comparison", "bar", "horizontal_bar", "line", "area",
                            "pie", "donut", "scatter", "funnel", "gauge", "heatmap", "table", "skip",
                        ],
                    },
                    "title": {"type": "string"},
                    "subtitle": {"type": "string"},
                    "x_field": {"type": "string", "description": "real column name for category/x-axis, or empty string"},
                    "y_field": {"type": "string", "description": "real column name for value/y-axis (also used as the KPI's value column), or empty string"},
                    "format": {"type": "string", "enum": ["number", "currency", "percentage", "decimal"]},
                    "kpi_label": {"type": "string", "description": "for render_as=kpi/kpi_comparison: label under the number"},
                    "kpi_delta_vs_node_id": {
                        "type": "string",
                        "description": "for render_as=kpi_comparison: another node id to compute a % delta against, or empty string",
                    },
                },
                "required": [
                    "source_node_id", "render_as", "title", "subtitle",
                    "x_field", "y_field", "format", "kpi_label", "kpi_delta_vs_node_id",
                ],
                "additionalProperties": False,
            },
        },
        "insights": {
            "type": "array",
            "description": "2-4 short, concrete business insight sentences referencing only the real numbers given below.",
            "items": {"type": "string"},
        },
    },
    "required": ["title", "subtitle", "sections", "insights"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You are the Report Agent inside an AI-native BI platform. You turn a set of
already-executed, already-validated SQL query results into ONE polished
business report specification — a single coherent canvas a business owner
could present to management, not a scattered list of mini-charts.

You will be given, for each query-plan node: its id, its description, the
REAL column names, a small REAL sample of its rows, and its total row count,
plus a deterministic analytics summary (growth %, totals) already computed in
Python. For each node, decide:
  - whether to include it at all ("skip" a purely intermediate/unhelpful node)
  - how to render it: a single-row/single-value result is almost always a
    "kpi" (or "kpi_comparison" if it should show a % delta against a sibling
    node's value — set kpi_delta_vs_node_id to that sibling's node id); a
    time series (date/month/year column + one metric) is "line" or "area"; a
    ranked list of categories with one metric is "bar" or "horizontal_bar"
    (horizontal for long labels or >8 categories); part-to-whole with few
    categories is "pie" or "donut"; wide tabular detail data is a "table".
  - x_field/y_field must be REAL column names from that node's columns (or
    empty string if not applicable) — never invent a field name. For KPIs,
    y_field MUST be the column whose value should be displayed (not just
    whichever column happens to come first).

Then write one title and one-line subtitle for the WHOLE report, and 2-4
short "insights" — concrete sentences referencing only numbers actually
present in the data/analytics given to you. Order sections: KPIs first, then
trend/comparison charts, then ranked/breakdown charts, then detail tables.

CRITICAL — insights must be real business findings, never status/error
commentary: do not write an insight saying data is "unavailable", "missing",
"no data available", "cannot be compared", or similar phrasing — that is not
a finding, it will be shown to the user as if it were one, and that is
misleading. If part of the question has no corresponding successful node,
simply write insights about the data you DO have and omit any mention of
what's missing."""


def _node_summary(node: QueryPlanNode) -> dict[str, Any]:
    columns = list(node.rows[0].keys()) if node.rows else []
    return {
        "node_id": node.id,
        "description": node.description,
        "columns": columns,
        "sample_rows": (node.rows or [])[:5],
        "row_count": node.row_count,
    }


async def build_report(question: str, plan: QueryPlan, analytics_summary: dict) -> ReportSpec:
    """One structured_completion call constrained to reference only
    source_node_id + field names (never actual data values), followed by
    Python-side materialization of every real value from plan node rows."""
    successful = [n for n in plan.nodes if n.status == "success" and n.rows]
    if not successful:
        return _empty_report(question, plan)

    if not is_enabled():
        report = heuristic_report(question, plan, analytics_summary)
        await _attach_images_safely(report)
        return report

    node_summaries = [_node_summary(n) for n in successful]
    user_prompt = (
        f"User question: {question}\n\n"
        f"Query nodes (id/description/columns/sample rows):\n{node_summaries}\n\n"
        f"Deterministic analytics already computed (JSON, use for insight text where relevant): "
        f"{analytics_summary}"
    )
    try:
        llm_plan = await structured_completion(
            system=SYSTEM_PROMPT,
            user=user_prompt,
            schema_name="report_spec",
            json_schema=REPORT_SCHEMA,
            temperature=0.2,
        )
    except Exception:  # noqa: BLE001 - report composition failure degrades to heuristic, never crashes the turn
        report = heuristic_report(question, plan, analytics_summary)
        await _attach_images_safely(report)
        return report

    report = _materialize_report(llm_plan, plan, analytics_summary)

    try:
        theme = _guess_theme(plan)
        report.banner_image_url = await generate_decorative_image(report.title, theme)
    except Exception:  # noqa: BLE001 - banner is best-effort, never required
        pass

    # 2026-09-19 single-image revision (see app/ai/chart_image_client.py
    # module docstring): the WHOLE report (title + all KPIs + all charts +
    # all tables + all insights) is rendered as ONE AI-generated image from
    # this same already-materialized real data, replacing the earlier
    # per-KPI/per-chart/per-table image approach. Runs for both the AI report
    # path and the heuristic fallback path above, as long as OPENAI_API_KEY
    # is configured for the image call itself — independent of whether AI
    # text-generation (structured_completion) is enabled. Non-fatal:
    # report_image_url stays None on any failure/disablement, and the
    # frontend then falls back to the full multi-section ECharts/DOM layout.
    await _attach_images_safely(report)

    return report


async def _attach_images_safely(report: ReportSpec) -> None:
    try:
        report.report_image_url = await generate_full_report_image(report)
    except Exception:  # noqa: BLE001 - image rendering is best-effort, never required
        pass


def _guess_theme(plan: QueryPlan) -> str:
    text = " ".join(n.description.lower() for n in plan.nodes)
    for theme in (
        "sales", "purchase", "hr", "inventory", "production",
        "order_to_delivery", "tasks", "finance",
    ):
        if theme.replace("_", " ") in text or theme in text:
            return theme
    return "executive"


def _humanize_field(field: str) -> str:
    """'total_revenue' -> 'Total Revenue' — used to label a KPI derived from a
    raw SQL column alias when no LLM-provided label exists."""
    return " ".join(word.capitalize() for word in field.replace("_", " ").split())


def _looks_like_money_field(field: str) -> bool:
    lowered = field.lower()
    return any(
        hint in lowered
        for hint in ("amount", "revenue", "value", "price", "cost", "sales", "purchase", "payable", "receivable")
    )


def _kpi_scalar(rows: list[dict[str, Any]], section: dict[str, Any]) -> Any:
    """Picks the value for a kpi/kpi_comparison section. A single-row query
    can return more than one column (e.g. SUM(total_amount) AS total_value,
    COUNT(*) AS order_count) — blindly taking "whichever column comes first
    in the row dict" silently picks the wrong number whenever the columns
    aren't ordered by KPI-relevance. This is the exact fix for the real
    production bug in CLAUDE.md: a "Total Purchase Orders" KPI displayed the
    SUM of order values instead of a count. Prefer the LLM-specified y_field
    (falling back to x_field) when it's actually present in the row; only
    fall back to "first scalar in the row" when neither named field is real."""
    if not rows:
        return None
    row = rows[0]
    for field_key in ("y_field", "x_field"):
        field = section.get(field_key)
        if field and field in row and isinstance(row[field], (int, float, str)):
            return row[field]
    for value in row.values():
        if isinstance(value, (int, float, str)):
            return value
    return None


_DATA_GAP_PHRASES = (
    "no data",
    "not available",
    "unavailable",
    "cannot be compared",
    "cannot be made",
    "could not be",
    "no available data",
    "missing data",
    "insufficient data",
    "n/a",
    "data is not",
    "data available",
    "no comparison",
    "not possible to compare",
)


def _filter_insights(insights: list[str]) -> list[str]:
    """Strips data-gap/error phrasing before it can reach the frontend as if
    it were a business finding (CLAUDE.md known-bug #2: a "no sales
    department data available" statement was once promoted to the report's
    headline callout). Case-insensitive substring match against common
    phrasing; conservative enough to rarely false-positive on a normal
    business sentence."""
    kept = []
    for text in insights:
        if not isinstance(text, str):
            continue
        lowered = text.lower()
        if any(phrase in lowered for phrase in _DATA_GAP_PHRASES):
            continue
        kept.append(text)
    return kept


def _materialize_report(llm_plan: dict, plan: QueryPlan, analytics_summary: dict) -> ReportSpec:
    """Turns the LLM's per-node rendering plan into a full ReportSpec,
    copying every KPI value / chart data point / table row VERBATIM from
    plan.get(node_id).rows — the LLM's own numeric echoes (if any slip
    through the schema) are ignored; only source_node_id + field-name
    choices from the LLM are trusted."""
    node_map = {n.id: n for n in plan.nodes}
    kpis: list[dict[str, Any]] = []
    charts: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    layout: list[dict[str, Any]] = []
    sections = llm_plan.get("sections", [])

    for i, section in enumerate(sections):
        node = node_map.get(section.get("source_node_id"))
        if node is None or node.status != "success" or not node.rows:
            continue
        render_as = section.get("render_as", "table")
        if render_as == "skip":
            continue

        section_id = f"sec_{i}_{node.id}"

        if render_as in ("kpi", "kpi_comparison"):
            value = _kpi_scalar(node.rows, section)
            delta = None
            delta_label = None
            trend = None
            if render_as == "kpi_comparison":
                other = node_map.get(section.get("kpi_delta_vs_node_id") or "")
                if other and other.status == "success" and other.rows:
                    other_section = next(
                        (s for s in sections if s.get("source_node_id") == other.id), section
                    )
                    other_value = _kpi_scalar(other.rows, other_section)
                    if (
                        isinstance(value, (int, float))
                        and isinstance(other_value, (int, float))
                        and other_value
                    ):
                        delta = round((value - other_value) / abs(other_value) * 100, 2)
                        delta_label = f"vs {other.description}"
                        trend = "up" if delta > 0 else ("down" if delta < 0 else "flat")
            kpis.append(
                {
                    "id": section_id,
                    "label": section.get("kpi_label") or section.get("title") or node.description,
                    "value": value if value is not None else 0,
                    "format": section.get("format") or "number",
                    "delta": delta,
                    "delta_label": delta_label,
                    "trend": trend,
                    "source_node_id": node.id,
                }
            )
            layout.append({"type": "kpi", "id": section_id})
        elif render_as == "table":
            columns = list(node.rows[0].keys())
            tables.append(
                {
                    "id": section_id,
                    "title": section.get("title") or node.description,
                    "columns": [{"field": c, "label": c.replace("_", " ").title(), "format": "text"} for c in columns],
                    "rows": node.rows,
                    "source_node_id": node.id,
                }
            )
            layout.append({"type": "table", "id": section_id})
        else:
            charts.append(
                {
                    "id": section_id,
                    "type": render_as,
                    "title": section.get("title") or node.description,
                    "subtitle": section.get("subtitle") or None,
                    "x_field": section.get("x_field") or None,
                    "y_field": section.get("y_field") or None,
                    "series": [],
                    "data": node.rows,
                    "source_node_id": node.id,
                }
            )
            layout.append({"type": "chart", "id": section_id})

    insight_texts = _filter_insights(llm_plan.get("insights", []))
    insights = [
        {"id": f"insight_{i}", "text": text, "kind": "headline" if i == 0 else "note"}
        for i, text in enumerate(insight_texts)
    ]

    return ReportSpec(
        id=str(uuid.uuid4()),
        title=llm_plan.get("title") or (plan.nodes[0].description if plan.nodes else "Report"),
        subtitle=llm_plan.get("subtitle") or None,
        kpis=kpis,
        charts=charts,
        tables=tables,
        insights=insights,
        layout=layout,
        query_trace=_build_query_trace(plan),
        generated_by="ai",
    )


def _build_query_trace(plan: QueryPlan) -> list[dict[str, Any]]:
    return [
        {
            "node_id": n.id,
            "description": n.description,
            "sql": n.sql or "",
            "row_count": n.row_count,
            "elapsed_ms": n.elapsed_ms,
            "status": "success" if n.status == "success" else "error",
            "tables": n.tables_referenced,
        }
        for n in plan.nodes
    ]


def _empty_report(question: str, plan: QueryPlan) -> ReportSpec:
    return ReportSpec(
        id=str(uuid.uuid4()),
        title=question,
        subtitle="No data was returned for this question.",
        kpis=[],
        charts=[],
        tables=[],
        insights=[],
        layout=[],
        query_trace=_build_query_trace(plan),
        generated_by="heuristic",
    )


def heuristic_report(question: str, plan: QueryPlan, analytics_summary: dict) -> ReportSpec:
    """Deterministic, zero-LLM fallback (CLAUDE.md: "a deterministic
    heuristic_report() fallback for when AI is disabled"):
      - exactly one successful node with one row -> render as a KPI
      - a successful node with multiple rows and >=2 columns -> bar chart + table
      - a successful node with multiple rows and 1 column -> table only
    Always includes a query_trace built from the plan nodes.
    """
    successful = [n for n in plan.nodes if n.status == "success" and n.rows]
    if not successful:
        return _empty_report(question, plan)

    kpis: list[dict[str, Any]] = []
    charts: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    layout: list[dict[str, Any]] = []

    for i, node in enumerate(successful):
        section_id = f"sec_{i}_{node.id}"
        columns = list(node.rows[0].keys())

        if len(node.rows) == 1:
            row = node.rows[0]
            numeric_columns = [c for c in columns if isinstance(row.get(c), (int, float))]

            if len(numeric_columns) > 1:
                # A single-row aggregate query can return several distinct
                # measures at once (e.g. SUM(total_amount) AS total_revenue,
                # COUNT(*) AS invoice_count) — collapsing this to ONE kpi via
                # "pick a column" would silently drop or mislabel a real
                # number. Emit one kpi per numeric column instead, each
                # explicitly naming its own source field via _kpi_scalar so
                # the "prefer the named field" fix actually has a field to
                # prefer (see _kpi_scalar docstring / CLAUDE.md bug #1).
                for col in numeric_columns:
                    col_section_id = f"{section_id}_{col}"
                    value = _kpi_scalar(node.rows, {"y_field": col, "x_field": ""})
                    kpis.append(
                        {
                            "id": col_section_id,
                            "label": _humanize_field(col),
                            "value": value if value is not None else 0,
                            "format": "currency" if _looks_like_money_field(col) else "number",
                            "delta": None,
                            "delta_label": None,
                            "trend": None,
                            "source_node_id": node.id,
                        }
                    )
                    layout.append({"type": "kpi", "id": col_section_id})
            else:
                value = _kpi_scalar(node.rows, {"y_field": numeric_columns[0] if numeric_columns else "", "x_field": ""})
                kpis.append(
                    {
                        "id": section_id,
                        "label": node.description,
                        "value": value if value is not None else 0,
                        "format": "currency" if numeric_columns and _looks_like_money_field(numeric_columns[0]) else "number",
                        "delta": None,
                        "delta_label": None,
                        "trend": None,
                        "source_node_id": node.id,
                    }
                )
                layout.append({"type": "kpi", "id": section_id})
            continue

        numeric_cols = [c for c in columns if isinstance(node.rows[0].get(c), (int, float))]
        text_cols = [c for c in columns if c not in numeric_cols]

        if numeric_cols and text_cols:
            charts.append(
                {
                    "id": section_id,
                    "type": "bar",
                    "title": node.description,
                    "subtitle": None,
                    "x_field": text_cols[0],
                    "y_field": numeric_cols[0],
                    "series": [],
                    "data": node.rows,
                    "source_node_id": node.id,
                }
            )
            layout.append({"type": "chart", "id": section_id})

        tables.append(
            {
                "id": f"{section_id}_table",
                "title": node.description,
                "columns": [{"field": c, "label": c.replace("_", " ").title(), "format": "text"} for c in columns],
                "rows": node.rows,
                "source_node_id": node.id,
            }
        )
        layout.append({"type": "table", "id": f"{section_id}_table"})

    return ReportSpec(
        id=str(uuid.uuid4()),
        title=question,
        subtitle=None,
        kpis=kpis,
        charts=charts,
        tables=tables,
        insights=[],
        layout=layout,
        query_trace=_build_query_trace(plan),
        generated_by="heuristic",
    )


__all__ = [
    "build_report",
    "heuristic_report",
    "_materialize_report",
    "_kpi_scalar",
    "_filter_insights",
    "_attach_images_safely",
]
