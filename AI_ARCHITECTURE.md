# AI_ARCHITECTURE

## Principles

1. **The AI must never fabricate a business number.** Every KPI value, chart data
   point, and table row shown to the user comes from a real, validated, executed SQL
   query against the database. The LLM decides *what to ask for* and *how to present
   it* — never the numbers themselves.
2. **Structured outputs over free-form text.** Every agent call that must produce a
   machine-consumed result (query plans, SQL, report layout, structural edit
   operations, intent classification) uses OpenAI's JSON-schema-constrained
   structured output (`app/ai/openai_client.py::structured_completion`), never
   regex-parsed free text.
3. **Graceful degradation without any credentials.** With no `OPENAI_API_KEY`, the
   app still runs fully: seeded data, the Data explorer, exports, and a curated set
   of zero-LLM "Recommended Reports" all work. Natural-language chat clearly reports
   `error: "ai_disabled"` rather than pretending to understand the question.

## Model configuration

Fully environment-driven, never hardcoded:
- `OPENAI_MODEL` (text) — default `gpt-4.1`. The original spec named "GPT-5.6 Sol",
  which does not exist in the OpenAI API; `gpt-4.1` is a real, strong reasoning/
  tool-use model used as the default, swappable with zero code changes once a
  specific desired model id is confirmed.
- `OPENAI_IMAGE_MODEL` (image, decorative only) — default `gpt-image-2`, a real OpenAI
  API model id (confirmed via web search 2026-09-19; OpenAI also offers newer
  `gpt-image-2.5-flare` / `gpt-image-2.5-sunburst` variants and the earlier
  `gpt-image-1`). Code never hardcodes a literal model string, so swapping variants
  is a one-line env change.

## The logical agents

All agents live under `backend/app/agents/` as plain async Python functions/modules
— not separate deployed services.

1. **Orchestrator** (`orchestrator.py`) — the single chat entrypoint. Classifies
   intent, routes to the analysis pipeline or the report-edit pipeline, assembles
   the final `ChatResponse`.
2. **Schema/Semantic Agent** (`semantic_layer/retrieval.py`) — pulls only the
   relevant slice of table/column/measure metadata for the current question
   (deterministic keyword/synonym scoring, no LLM call, no full-schema dump).
3. **Query Planner Agent** (`query_planner_agent.py`) — turns the question + semantic
   context into a `QueryPlan` DAG (nodes with `depends_on`), supporting independent
   parallel nodes and dependent nodes (e.g. a growth-% node depends on two period
   nodes).
4. **SQL Generation Agent** (`sql_agent.py`) — turns one query-plan node into one
   SELECT statement; also implements the error-recovery regeneration path used by
   the executor's retry loop.
5. **Validation Agent** (`security/sql_guard.py`) — sqlglot AST allowlist check +
   table-existence check + timeout/row-limit injection. See `ARCHITECTURE.md`.
6. **Analytics Agent** (`analytics/engine.py`) — deterministic post-query
   calculations (growth %, margin, conversion rate, delivery delay %, ...) — never
   LLM-computed.
7. **Report Agent** (`report_agent.py`) — the core of the product. Takes every
   successful query-plan node's rows + the deterministic analytics summary and
   produces one structured `ReportSpec`. The LLM's single structured-output call
   decides *which node feeds which section, what to title it, and which chart type
   to use* — it never gets to assert a numeric value that survives. Every KPI
   value/chart datapoint/table row is copied verbatim in Python
   (`_materialize_report`) from the already-executed query result. Has a
   deterministic `heuristic_report()` fallback for when AI is disabled or as the
   renderer behind Recommended Reports.
8. **Report Edit Agent** (`report_edit_agent.py`) — handles conversational
   follow-ups to the report just shown. Purely-structural edits (reorder/remove/
   retype/rename/reformat) are applied deterministically via
   `apply_structural_operations` — no new query, cannot alter any existing value.
   Edits that need new data are flagged `needs_requery=true`; the orchestrator runs
   a small follow-up query-plan and merges the new real section(s) into the existing
   report.
9. **Explanation/Conversation Agent** (`explanation_agent.py`) — intent
   classification (`ANALYSIS`/`REPORT_EDIT`/`DATA_PREVIEW`/`EXPLAIN_WHY`/
   `GREETING_OR_OTHER`) and the final natural-language reply, referencing only
   values already present in the `ReportSpec` — never re-deriving or inventing a
   number during the explanation step.
10. **Export Agent** (`exports/export_engine.py`) — CSV/XLSX from a report's
    underlying real rows. PNG is deliberately client-rendered only (no server
    endpoint) — see `ARCHITECTURE.md`.
11. **Image Agent** (`ai/image_client.py`) — decorative-only image generation. See
    below; this is the one agent with a hard, code-level (not just documented)
    restriction on what it can be given as input.

## The decorative-only image boundary, enforced structurally

`app/ai/image_client.py::generate_decorative_image(title: str, theme: str = "generic") -> str | None`
is the only function in the codebase that calls an image-generation model. Why this
matters: an image-generation model has no way to guarantee that digits, labels, or
bar heights it draws match real data — using it to render a chart/KPI/table would
directly violate principle #1 above ("the AI must never fabricate a business
number"). So this boundary is enforced in code, not just policy:

- **Signature**: exactly two parameters, both typed `str` — `title` and `theme`.
  There is no parameter through which row data, a `ReportSpec`, a chart's `data`
  list, or any numeric value could be passed.
- **No data imports**: `app/ai/image_client.py` has zero imports of
  `app.query_engine`, `app.analytics`, `app.schemas.report`, or any row/result type.
  It is not merely "unused" — it is architecturally impossible for this function to
  receive query results without changing its signature and adding new imports,
  which would be an obvious, reviewable diff.
- **Runtime guard**: the function also checks `isinstance(title, str)` and
  `isinstance(theme, str)` and refuses (`return None`) if either isn't a plain
  string, in case a future caller tries to smuggle a dict/list through by mistake.
- **Prompt template**: `_build_prompt()` interpolates only `title`/`theme` into a
  fixed template that explicitly instructs the model to draw abstract shapes/
  gradients/icons and **never** numbers, digits, percentages, currency symbols,
  chart/graph shapes, tables, or readable data-like text.
- **Callers**: only `report_agent.py` calls this, to optionally set
  `ReportSpec.banner_image_url` — a decorative header background. It's best-effort
  and swallows all failures; a report is always fully valid without a banner image.
- **Charts themselves never touch an image model at all** — `ChartSpec.data` is real
  row data rendered client-side by ECharts in the browser.

If a future contributor wants a banner to also visually reference the top KPI
number, that must happen by overlaying real DOM text on top of this decorative
image client-side — never by feeding data into `generate_decorative_image`.

## Structured output schemas (representative)

- Query plan: `{"nodes": [{"id": str, "description": str, "depends_on": [str]}]}`
- SQL generation: `{"sql": str}`
- Report layout: `{"title": str, "kpis": [{"source_node_id","label","value_field","format"}], "charts": [...], "tables": [...], "insights": [...]}`
  — note `value_field`/similar always names a column, never a literal value.
- Structural edit ops: `{"needs_requery": bool, "requery_description": str|null, "structural_ops": [{"op": str, "target": str, ...}]}`
- Intent classification: `{"intent": "ANALYSIS"|"REPORT_EDIT"|"DATA_PREVIEW"|"EXPLAIN_WHY"|"GREETING_OR_OTHER"}`

## Error handling / retry

SQL generation failures go through up to `SQL_MAX_RETRY` (default 2) regeneration
attempts, each given the previous SQL + the database error message, before the node
is marked failed. A turn with some failed nodes still returns a partial report with
an honest note about what couldn't be computed, rather than either fabricating a
number or hard-failing the whole turn. If literally every node fails, the response
says so plainly.
