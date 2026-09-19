"""Report Agent: heuristic_report (no-AI fallback) must produce a valid
ReportSpec from real query-plan node rows, and _materialize_report must copy
row data verbatim rather than trusting anything the LLM echoes back — these
are the exact regression tests for the two real production bugs documented
in CLAUDE.md (wrong KPI column picked; data-gap text shown as a finding).
"""
from app.agents.report_agent import (
    _filter_insights,
    _kpi_scalar,
    _materialize_report,
    heuristic_report,
)
from app.query_engine.plan import QueryPlan, QueryPlanNode
from app.schemas.report import ReportSpec


def _plan_with_two_nodes() -> QueryPlan:
    kpi_node = QueryPlanNode(
        id="q1", description="Total Revenue", status="success",
        rows=[{"total_revenue": 50000.0}], row_count=1,
    )
    table_node = QueryPlanNode(
        id="q2", description="Top Customers", status="success",
        rows=[
            {"customer": "Acme", "revenue": 30000.0},
            {"customer": "Globex", "revenue": 20000.0},
        ],
        row_count=2,
    )
    return QueryPlan(nodes=[kpi_node, table_node])


def test_heuristic_report_produces_valid_spec():
    plan = _plan_with_two_nodes()
    report = heuristic_report("Show revenue and top customers", plan, analytics_summary={})
    assert isinstance(report, ReportSpec)
    assert report.title == "Show revenue and top customers"
    assert len(report.kpis) == 1
    assert report.kpis[0].value == 50000.0
    # 2-row/2-column result renders as a bar chart + table by the heuristic
    assert len(report.charts) == 1
    assert len(report.tables) == 1
    assert len(report.query_trace) == 2


def test_heuristic_report_empty_plan_returns_empty_report():
    plan = QueryPlan(nodes=[])
    report = heuristic_report("No data question", plan, analytics_summary={})
    assert report.kpis == []
    assert report.charts == []
    assert report.tables == []


def test_heuristic_report_all_failed_nodes_returns_empty_report():
    plan = QueryPlan(nodes=[QueryPlanNode(id="q1", description="Failed query", status="error", error="boom")])
    report = heuristic_report("A question that failed", plan, analytics_summary={})
    assert report.kpis == []
    assert report.charts == []
    assert report.tables == []
    assert report.query_trace[0].status == "error"


def test_materialize_report_copies_real_row_data_not_llm_values():
    """Even if the LLM's own layout dict tried to claim a value, only
    source_node_id + field-name choices are trusted; every actual number
    comes from plan.get(node_id).rows."""
    plan = _plan_with_two_nodes()
    llm_plan = {
        "title": "Revenue Overview",
        "subtitle": "September performance",
        "sections": [
            {
                "source_node_id": "q1", "render_as": "kpi", "title": "Total Revenue",
                "subtitle": "", "x_field": "", "y_field": "total_revenue", "format": "currency",
                "kpi_label": "Total Revenue", "kpi_delta_vs_node_id": "",
                # An LLM cannot even express a fabricated numeric value in this
                # schema (no "value" field exists) — the schema itself enforces
                # that only structure/labels/field-names can be supplied.
            },
            {
                "source_node_id": "q2", "render_as": "table", "title": "Top Customers",
                "subtitle": "", "x_field": "", "y_field": "", "format": "number",
                "kpi_label": "", "kpi_delta_vs_node_id": "",
            },
        ],
        "insights": ["Acme is the top customer."],
    }
    report = _materialize_report(llm_plan, plan, analytics_summary={})

    assert report.kpis[0].value == 50000.0  # real value from the node
    assert report.tables[0].rows == plan.nodes[1].rows  # exact same row objects
    assert report.insights[0].text == "Acme is the top customer."


def test_materialize_report_kpi_comparison_computes_real_delta():
    current = QueryPlanNode(id="cur", description="September Revenue", status="success", rows=[{"total": 120.0}], row_count=1)
    previous = QueryPlanNode(id="prev", description="August Revenue", status="success", rows=[{"total": 100.0}], row_count=1)
    plan = QueryPlan(nodes=[current, previous])
    llm_plan = {
        "title": "Revenue Comparison",
        "subtitle": "",
        "sections": [
            {
                "source_node_id": "cur", "render_as": "kpi_comparison", "title": "September Revenue",
                "subtitle": "", "x_field": "", "y_field": "total", "format": "currency",
                "kpi_label": "September Revenue", "kpi_delta_vs_node_id": "prev",
            },
        ],
        "insights": [],
    }
    report = _materialize_report(llm_plan, plan, analytics_summary={})
    assert report.kpis[0].value == 120.0
    assert report.kpis[0].delta == 20.0  # (120-100)/100 * 100
    assert report.kpis[0].trend == "up"


def test_kpi_scalar_prefers_named_y_field_over_first_column():
    """Regression test for the real production bug: a 'Total Purchase
    Orders' KPI showed SUM(total_amount) instead of COUNT(*) because the
    row had total_value listed before order_count and the old code just
    took 'whatever key comes first in the dict'."""
    rows = [{"total_value": 2517126.67, "order_count": 2}]
    section = {"y_field": "order_count", "x_field": ""}
    assert _kpi_scalar(rows, section) == 2


def test_kpi_scalar_falls_back_to_x_field_then_first_scalar():
    rows = [{"a": 1, "b": 2}]
    assert _kpi_scalar(rows, {"y_field": "", "x_field": "b"}) == 2
    assert _kpi_scalar(rows, {"y_field": "", "x_field": ""}) == 1


def test_kpi_scalar_ignores_field_name_not_present_in_row():
    rows = [{"total": 42}]
    assert _kpi_scalar(rows, {"y_field": "not_a_real_column", "x_field": ""}) == 42


def test_materialize_report_kpi_uses_correct_column_not_first_in_dict():
    node = QueryPlanNode(
        id="q1", description="Total Purchase Orders", status="success",
        rows=[{"total_value": 2517126.67, "order_count": 2}], row_count=1,
    )
    plan = QueryPlan(nodes=[node])
    llm_plan = {
        "title": "Purchase Orders",
        "subtitle": "",
        "sections": [
            {
                "source_node_id": "q1", "render_as": "kpi", "title": "Total Purchase Orders",
                "subtitle": "", "x_field": "", "y_field": "order_count", "format": "number",
                "kpi_label": "Total Purchase Orders", "kpi_delta_vs_node_id": "",
            },
        ],
        "insights": [],
    }
    report = _materialize_report(llm_plan, plan, analytics_summary={})
    assert report.kpis[0].value == 2


def test_filter_insights_drops_data_gap_statements():
    insights = [
        "Revenue grew 12% this month.",
        "No sales department data is available for last week, so a direct comparison cannot be made.",
        "Purchase orders totaled $2.5M.",
    ]
    filtered = _filter_insights(insights)
    assert len(filtered) == 2
    assert all("no sales department data" not in text.lower() for text in filtered)


def test_filter_insights_keeps_normal_business_sentences():
    insights = ["Delivery delays increased by 8% versus August."]
    assert _filter_insights(insights) == insights


def test_materialize_report_filters_data_gap_insight_from_headline():
    """End-to-end version of the second real production bug: a status/error
    sentence must never reach the report's insights list at all, let alone
    as the first (headline) entry."""
    node = QueryPlanNode(id="q1", description="Sales", status="success", rows=[{"total": 100}], row_count=1)
    plan = QueryPlan(nodes=[node])
    llm_plan = {
        "title": "Sales Report",
        "subtitle": "",
        "sections": [
            {
                "source_node_id": "q1", "render_as": "kpi", "title": "Total Sales",
                "subtitle": "", "x_field": "", "y_field": "total", "format": "currency",
                "kpi_label": "Total Sales", "kpi_delta_vs_node_id": "",
            },
        ],
        "insights": [
            "No sales department data available for comparison.",
            "Total sales reached $100.",
        ],
    }
    report = _materialize_report(llm_plan, plan, analytics_summary={})
    assert len(report.insights) == 1
    assert report.insights[0].text == "Total sales reached $100."
    assert report.insights[0].kind == "headline"
