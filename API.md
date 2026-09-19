# API

Base URL (dev): `http://localhost:8000`. All routes are under `/api`.

## Chat (async job pattern)

### `POST /api/chat`
Body: `{"message": string, "conversation_id"?: string}`
Returns immediately: `{"job_id": string}`

### `GET /api/chat/jobs/{job_id}`
Returns: `{"job_id": string, "status": "pending"|"running"|"done"|"error", "result"?: ChatResponse, "error"?: string}`

Poll this until `status` is `done` or `error`. `result` (when `done`) is a
`ChatResponse`:

```json
{
  "conversation_id": "…",
  "message": "Here is the September revenue comparison.",
  "intent": "ANALYSIS",
  "report": { "...": "ReportSpec, see below" },
  "error": null
}
```

If AI is disabled, `error` is `"ai_disabled"` and `message` points at
`GET /api/recommended`.

## Schema / metadata (Data explorer)

### `GET /api/schema`
Returns an array of `{"table": string, "columns": [{"name","type","is_pk","is_fk","references","nullable"}]}` for all 62 business tables, reflected from `Base.metadata` (no per-request `information_schema` query).

### `GET /api/metadata`
Returns the semantic layer's cached `{"tables": {...}, "measures": [...]}`.

### `POST /api/metadata/refresh`
Forces a metadata cache rebuild.

## Data preview

### `GET /api/data/preview?table=customers&limit=50&offset=0`
Returns `{"table","columns","rows","row_count","total_count"}`. `table` must be one
of the real reflected table names (validated server-side against an allowlist —
never string-interpolated from unvalidated input beyond that check).

## Exports

### `POST /api/export/csv`
Body: `{"rows": object[], "columns"?: string[], "filename"?: string}`
Returns a `text/csv` file download.

### `POST /api/export/excel`
Same body shape. Returns an `.xlsx` file download.

PNG export has **no server endpoint** — it's rendered client-side from the actual
report DOM node via `html-to-image` (see `ARCHITECTURE.md`).

## Reports

### `GET /api/reports/{report_id}`
Best-effort lookup of a previously generated `ReportSpec` by id from in-memory
conversation history (process-local; lost on restart).

## Recommended reports (zero-LLM)

### `GET /api/recommended`
Returns `[{"id","title","description"}, ...]`.

### `POST /api/recommended/{id}/run`
Runs one hand-written SQL report and returns a full `ChatResponse` with a populated
`report`, with no LLM call involved.

## Health

### `GET /api/health`
`{"status": "ok", "app": "AI-Native BI Platform"}`

## `ReportSpec` shape

```ts
interface ReportSpec {
  id: string;
  title: string;
  subtitle?: string;
  kpis: Array<{
    id: string; label: string; value: number | string;
    format: "number" | "currency" | "percentage" | "decimal";
    delta?: number; delta_label?: string; trend?: "up" | "down" | "flat";
    source_node_id?: string;
  }>;
  charts: Array<{
    id: string;
    type: "bar" | "horizontal_bar" | "line" | "area" | "pie" | "donut" | "scatter" | "funnel" | "gauge" | "heatmap";
    title: string; subtitle?: string; x_field?: string; y_field?: string;
    series: Array<{ name: string; field: string }>;
    data: Record<string, any>[];
    source_node_id?: string; color_theme?: string;
  }>;
  tables: Array<{
    id: string; title: string;
    columns: Array<{ field: string; label: string; format: "number"|"currency"|"percentage"|"decimal"|"text"|"date" }>;
    rows: Record<string, any>[];
    source_node_id?: string;
  }>;
  insights: Array<{ id: string; text: string; kind: "headline" | "note" | "warning" }>;
  layout: any[];
  banner_image_url?: string;
  query_trace: Array<{
    node_id: string; description: string; sql: string;
    row_count: number; elapsed_ms: number; status: "success" | "error";
    tables: string[];
  }>;
  generated_by: "ai" | "heuristic";
}
```

`query_trace` is the "View Query" / traceability feature — every report can show
exactly what SQL ran, against which tables, how long it took, and how many rows came
back, without exposing internal LLM reasoning.
