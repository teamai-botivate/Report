// TypeScript mirror of backend/app/schemas/report.py — field names and
// optionality must match exactly. Every KPI value / chart data point / table
// row the backend sends here was already copied verbatim in Python from a
// validated, executed query result (see CLAUDE.md's Report Agent section) —
// the frontend just renders it.

export type ChartType =
  | "bar"
  | "horizontal_bar"
  | "line"
  | "area"
  | "pie"
  | "donut"
  | "scatter"
  | "funnel"
  | "gauge"
  | "heatmap";

export type KpiFormat = "number" | "currency" | "percentage" | "decimal";
export type Trend = "up" | "down" | "flat";

export interface KPISpec {
  id: string;
  label: string;
  value: number | string;
  format: KpiFormat;
  delta?: number | null;
  delta_label?: string | null;
  trend?: Trend | null;
  source_node_id?: string | null;
  // 2026-09-19: per-item image field, superseded the same day by the
  // report-level ReportSpec.report_image_url below. No longer populated by
  // the backend; kept for backward compatibility.
  image_url?: string | null;
}

export interface ChartSeriesSpec {
  name: string;
  field: string;
}

export interface ChartSpec {
  id: string;
  type: ChartType;
  title: string;
  subtitle?: string | null;
  x_field?: string | null;
  y_field?: string | null;
  series: ChartSeriesSpec[];
  data: Record<string, any>[];
  source_node_id?: string | null;
  color_theme?: string | null;
  // 2026-09-19: per-item image field, superseded the same day by the
  // report-level ReportSpec.report_image_url below. No longer populated by
  // the backend; kept for backward compatibility.
  image_url?: string | null;
}

export type TableColumnFormat =
  | "number"
  | "currency"
  | "percentage"
  | "decimal"
  | "text"
  | "date";

export interface TableColumnSpec {
  field: string;
  label: string;
  format: TableColumnFormat;
}

export interface TableSpec {
  id: string;
  title: string;
  columns: TableColumnSpec[];
  rows: Record<string, any>[];
  source_node_id?: string | null;
  // 2026-09-19: per-item image field, superseded the same day by the
  // report-level ReportSpec.report_image_url below. No longer populated by
  // the backend; kept for backward compatibility.
  image_url?: string | null;
}

export type InsightKind = "headline" | "note" | "warning";

export interface InsightSpec {
  id: string;
  text: string;
  kind: InsightKind;
}

export interface QueryTraceSpec {
  node_id: string;
  description: string;
  sql: string;
  row_count: number;
  elapsed_ms: number;
  status: "success" | "error";
  tables: string[];
}

export interface ReportSpec {
  id: string;
  title: string;
  subtitle?: string | null;
  kpis: KPISpec[];
  charts: ChartSpec[];
  tables: TableSpec[];
  insights: InsightSpec[];
  layout: any[];
  banner_image_url?: string | null;
  // 2026-09-19 single-image revision: ONE AI-generated image depicting the
  // ENTIRE report (title + all KPIs + all charts + all tables + all
  // insights) as one cohesive dashboard picture. When present, the frontend
  // renders ONLY this image for the whole report body. When absent (image
  // generation disabled or failed), the frontend falls back to rendering the
  // full multi-section ECharts/DOM layout — never a mix of the two.
  report_image_url?: string | null;
  query_trace: QueryTraceSpec[];
  generated_by: "ai" | "heuristic";
}

export type ChatIntent =
  | "ANALYSIS"
  | "REPORT_EDIT"
  | "DATA_PREVIEW"
  | "EXPLAIN_WHY"
  | "GREETING_OR_OTHER";

export interface ChatRequest {
  message: string;
  conversation_id?: string | null;
}

export interface ChatResponse {
  conversation_id: string;
  message: string;
  intent: ChatIntent;
  report?: ReportSpec | null;
  error?: string | null;
}

export interface JobEnqueueResponse {
  job_id: string;
}

export type JobStatus = "pending" | "running" | "done" | "error";

export interface JobStatusResponse {
  job_id: string;
  status: JobStatus;
  result?: ChatResponse | null;
  error?: string | null;
}

// ---- Endpoints not defined by report.py, best-effort shapes ----

export interface SchemaColumn {
  name: string;
  type: string;
  is_pk?: boolean;
  is_fk?: boolean;
  references?: string | null;
}

export interface SchemaTable {
  table: string;
  columns: SchemaColumn[];
}

// GET /api/schema returns a bare array of SchemaTable, not a wrapper object.
export type SchemaResponse = SchemaTable[];

export interface DataPreviewResponse {
  columns: string[];
  rows: Record<string, any>[];
  row_count: number;
  total_count: number;
}

export interface RecommendedReportSummary {
  id: string;
  title: string;
  description: string;
}

export interface HealthResponse {
  status: string;
  [key: string]: unknown;
}
