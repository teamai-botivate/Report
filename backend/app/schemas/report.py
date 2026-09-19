"""Pydantic schemas for the ReportSpec shape produced by the Report Agent.

Every KPI value / chart data point / table row is copied verbatim in Python
(report_agent._materialize_report) from already-validated, already-executed query
results — never trusted from the LLM's own echo. See CLAUDE.md Report Agent section.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ChartType = Literal[
    "bar", "horizontal_bar", "line", "area", "pie", "donut", "scatter",
    "funnel", "gauge", "heatmap",
]


class KPISpec(BaseModel):
    id: str
    label: str
    value: float | int | str
    format: Literal["number", "currency", "percentage", "decimal"] = "number"
    delta: float | None = None
    delta_label: str | None = None
    trend: Literal["up", "down", "flat"] | None = None
    source_node_id: str | None = None
    # 2026-09-19: per-item image field, SUPERSEDED the same day by the
    # report-level `ReportSpec.report_image_url` (see
    # app/ai/chart_image_client.py). Kept in the schema for backward
    # compatibility; no longer populated by the backend.
    image_url: str | None = None


class ChartSeriesSpec(BaseModel):
    name: str
    field: str


class ChartSpec(BaseModel):
    id: str
    type: ChartType
    title: str
    subtitle: str | None = None
    x_field: str | None = None
    y_field: str | None = None
    series: list[ChartSeriesSpec] = Field(default_factory=list)
    data: list[dict[str, Any]] = Field(default_factory=list)
    source_node_id: str | None = None
    color_theme: str | None = None
    # 2026-09-19: per-item image field, SUPERSEDED the same day by the
    # report-level `ReportSpec.report_image_url` (see
    # app/ai/chart_image_client.py). Kept in the schema for backward
    # compatibility; no longer populated by the backend.
    image_url: str | None = None


class TableColumnSpec(BaseModel):
    field: str
    label: str
    format: Literal["number", "currency", "percentage", "decimal", "text", "date"] = "text"


class TableSpec(BaseModel):
    id: str
    title: str
    columns: list[TableColumnSpec]
    rows: list[dict[str, Any]] = Field(default_factory=list)
    source_node_id: str | None = None
    # 2026-09-19: per-item image field, SUPERSEDED the same day by the
    # report-level `ReportSpec.report_image_url` (see
    # app/ai/chart_image_client.py). Kept in the schema for backward
    # compatibility; no longer populated by the backend.
    image_url: str | None = None


class InsightSpec(BaseModel):
    id: str
    text: str
    kind: Literal["headline", "note", "warning"] = "note"


class QueryTraceSpec(BaseModel):
    node_id: str
    description: str
    sql: str
    row_count: int
    elapsed_ms: float
    status: Literal["success", "error"]
    tables: list[str] = Field(default_factory=list)


class ReportSpec(BaseModel):
    id: str
    title: str
    subtitle: str | None = None
    kpis: list[KPISpec] = Field(default_factory=list)
    charts: list[ChartSpec] = Field(default_factory=list)
    tables: list[TableSpec] = Field(default_factory=list)
    insights: list[InsightSpec] = Field(default_factory=list)
    layout: list[dict[str, Any]] = Field(default_factory=list)
    banner_image_url: str | None = None
    # 2026-09-19 single-image revision (see app/ai/chart_image_client.py):
    # ONE AI-generated image depicting the ENTIRE report (title + all KPIs +
    # all charts + all tables + all insights) as one cohesive dashboard
    # picture. Report-level field, distinct from `banner_image_url` (a purely
    # decorative header image, unrelated to data) and from the per-item
    # `image_url` fields on KPISpec/ChartSpec/TableSpec below (kept in the
    # schema for backward compatibility but no longer populated by the
    # backend going forward — superseded by this single report-level image).
    # None means image generation is disabled or failed; the frontend then
    # falls back to rendering the full multi-section ECharts/DOM layout.
    report_image_url: str | None = None
    query_trace: list[QueryTraceSpec] = Field(default_factory=list)
    generated_by: Literal["ai", "heuristic"] = "heuristic"


class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None


class ChatResponse(BaseModel):
    conversation_id: str
    message: str
    intent: Literal["ANALYSIS", "REPORT_EDIT", "DATA_PREVIEW", "EXPLAIN_WHY", "GREETING_OR_OTHER"]
    report: ReportSpec | None = None
    error: str | None = None


class JobEnqueueResponse(BaseModel):
    job_id: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: Literal["pending", "running", "done", "error"]
    result: ChatResponse | None = None
    error: str | None = None
