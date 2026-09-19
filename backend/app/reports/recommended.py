"""Recommended Reports — a small fixed catalog of hand-written SQL "reports" that
materialize into the exact same ReportSpec shape as the AI pipeline, via
report_agent._materialize_report(), just with a hand-written rendering plan instead
of an LLM-produced one. Zero LLM calls — works with no OpenAI key at all.

Exposed as one-click buttons on the chat home screen and inside the ai_disabled
notice (see CLAUDE.md "Recommended Reports"). Runs are persisted into the same
ChatMessage/conversation history as /api/chat so a follow-up chat message can
REPORT_EDIT a recommended report once AI is configured.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from app.query_engine.plan import QueryPlan, QueryPlanNode
from app.query_engine.executor import execute_plan
from app.schemas.report import ReportSpec


@dataclass
class RecommendedReport:
    id: str
    title: str
    description: str
    sql: str
    render: str  # "kpi_row" | "bar_chart" | "table"
    x_field: str | None = None
    y_field: str | None = None
    theme: str = "generic"


CATALOG: list[RecommendedReport] = [
    RecommendedReport(
        id="revenue_overview",
        title="Revenue Overview",
        description="Total revenue and invoice count from sales invoices.",
        sql=(
            "SELECT COUNT(*) AS invoice_count, COALESCE(SUM(total_amount), 0) AS total_revenue "
            "FROM sales_invoices"
        ),
        render="kpi_row",
        theme="sales",
    ),
    RecommendedReport(
        id="top_customers",
        title="Top Customers by Revenue",
        description="Top 10 customers ranked by total invoiced revenue.",
        sql=(
            "SELECT c.name AS customer, SUM(i.total_amount) AS revenue "
            "FROM sales_invoices i JOIN customers c ON c.id = i.customer_id "
            "GROUP BY c.name ORDER BY revenue DESC LIMIT 10"
        ),
        render="bar_chart",
        x_field="customer",
        y_field="revenue",
        theme="sales",
    ),
    RecommendedReport(
        id="delayed_deliveries",
        title="Delayed Deliveries",
        description="Deliveries where the actual date is later than the expected date.",
        sql=(
            "SELECT d.id AS delivery_id, d.expected_delivery_date, d.actual_delivery_date, "
            "d.status FROM deliveries d "
            "WHERE d.actual_delivery_date IS NOT NULL AND d.expected_delivery_date IS NOT NULL "
            "AND d.actual_delivery_date > d.expected_delivery_date "
            "ORDER BY d.actual_delivery_date DESC LIMIT 50"
        ),
        render="table",
        theme="order_to_delivery",
    ),
    RecommendedReport(
        id="inventory_risk",
        title="Inventory Risk",
        description="Products with stock below their reorder level.",
        sql=(
            "SELECT p.name AS product, s.quantity_on_hand, p.reorder_level "
            "FROM stock s JOIN products p ON p.id = s.product_id "
            "WHERE s.quantity_on_hand < p.reorder_level "
            "ORDER BY (p.reorder_level - s.quantity_on_hand) DESC LIMIT 50"
        ),
        render="table",
        theme="inventory",
    ),
    RecommendedReport(
        id="sales_vs_purchase",
        title="Sales vs Purchase Value",
        description="Total sales revenue compared with total purchase order value.",
        sql=(
            "SELECT "
            "(SELECT COALESCE(SUM(total_amount),0) FROM sales_invoices) AS total_sales, "
            "(SELECT COALESCE(SUM(total_amount),0) FROM purchase_orders) AS total_purchase"
        ),
        render="kpi_row",
        theme="finance",
    ),
    RecommendedReport(
        id="attendance_overview",
        title="Attendance Overview",
        description="Attendance status counts across all employees.",
        sql=(
            "SELECT status, COUNT(*) AS count FROM attendance GROUP BY status ORDER BY count DESC"
        ),
        render="bar_chart",
        x_field="status",
        y_field="count",
        theme="hr",
    ),
    RecommendedReport(
        id="production_quality",
        title="Production Quality",
        description="Production output vs rejections by product.",
        sql=(
            "SELECT p.name AS product, COALESCE(SUM(po.quantity_produced),0) AS produced, "
            "COALESCE(SUM(pr.quantity_rejected),0) AS rejected "
            "FROM production_orders o "
            "JOIN products p ON p.id = o.product_id "
            "LEFT JOIN production_output po ON po.production_order_id = o.id "
            "LEFT JOIN production_rejections pr ON pr.production_order_id = o.id "
            "GROUP BY p.name ORDER BY produced DESC LIMIT 20"
        ),
        render="table",
        theme="production",
    ),
]


def list_catalog() -> list[dict]:
    return [{"id": r.id, "title": r.title, "description": r.description} for r in CATALOG]


def _find(report_id: str) -> RecommendedReport | None:
    return next((r for r in CATALOG if r.id == report_id), None)


async def run_recommended(report_id: str) -> ReportSpec:
    item = _find(report_id)
    if item is None:
        raise ValueError(f"Unknown recommended report: {report_id}")

    node = QueryPlanNode(id="n1", description=item.description, sql=item.sql)
    plan = QueryPlan(nodes=[node])
    plan = await execute_plan(plan)

    from app.agents.report_agent import heuristic_report

    report = heuristic_report(item.title, plan, analytics_summary={})
    report.title = item.title
    report.subtitle = item.description
    report.generated_by = "heuristic"
    return report
