# ARCHITECTURE

## High-level shape

```
Browser (Next.js: Chat + Data explorer)
        |
        v  HTTP/JSON (poll-based for chat)
FastAPI app (single process)
   ├── api/            routers: chat, schema, metadata, data, exports, reports, recommended
   ├── agents/          orchestrator + logical agents (see AI_ARCHITECTURE.md)
   ├── query_engine/    QueryPlan DAG + executor (validate -> execute -> audit)
   ├── security/        sqlglot AST allowlist gate
   ├── semantic_layer/  metadata cache + business dictionary + deterministic retrieval
   ├── analytics/       deterministic measure calculations (never LLM-computed)
   ├── exports/         CSV/XLSX generation
   ├── reports/         zero-LLM "Recommended Reports" catalog
   └── models/          SQLAlchemy ORM, 62 tables across 9 business modules
        |
        v
Two SQLAlchemy async engines against the SAME database (SQLite dev / Neon Postgres prod):
   - primary (read/write): app data, seeding, migrations
   - "readonly" (also used to execute AI-generated SELECTs, after the security gate)
```

## Chat turn pipeline (ANALYSIS / DATA_PREVIEW / EXPLAIN_WHY)

```
user message
   -> Explanation Agent: classify_intent()
   -> Query Planner Agent: plan_queries() -> QueryPlan (DAG of nodes)
   -> SQL Generation Agent: generate_sql() per node
   -> Security gate: validate_sql() (sqlglot AST allowlist, LIMIT injection)
   -> Executor: execute_plan() runs validated SQL against the readonly engine,
      in dependency-respecting parallel batches, with retry-via-regeneration
      on failure (up to SQL_MAX_RETRY), audit-logging every attempt
   -> Analytics Agent: deterministic post-query math (growth %, margin, ...)
   -> Report Agent: build_report() -> ONE ReportSpec
        - AI enabled: one structured-output call decides layout/labels/chart
          choice only; _materialize_report() copies every value verbatim from
          already-executed rows in Python — the LLM's own echoed numbers are
          never trusted.
        - AI disabled: heuristic_report() (zero LLM calls, still needs
          real executed SQL — see "ai_disabled" behavior below)
   -> Explanation Agent: explain_result() -> final NL reply, referencing only
      the ReportSpec's own real values
   -> ChatResponse assembled and returned
```

## Report-edit pipeline (REPORT_EDIT)

```
follow-up message + previous ReportSpec (from this conversation's history)
   -> Report Edit Agent: classify as purely-structural vs needs-requery
   -> structural-only: apply_structural_operations() deterministically
      reorders/removes/retypes/renames sections — cannot alter any existing
      value, only presentation/structure (e.g. "top 3" slices already-real
      rows; "make it horizontal" flips chart.type)
   -> needs_requery=true: a small follow-up QueryPlan is planned/executed/
      analyzed exactly like the main pipeline, and the new real section(s)
      are merged into the existing ReportSpec
   -> same ReportSpec shape returned
```

## Why chat is a background job, not a blocking request

A complex multi-query turn can trigger several sequential OpenAI calls (intent
classification, query planning, one SQL-generation call per node, report
composition, explanation). That can take long enough that a hosting proxy in front
of the app (Render's own reverse proxy, for example) drops the connection before a
single blocking `POST /api/chat` finishes — regardless of client-side timeout
configuration. Fix: `POST /api/chat` returns a `job_id` almost immediately
(`app/core/job_store.py` + FastAPI `BackgroundTasks` in `app/api/chat.py`); the
frontend polls `GET /api/chat/jobs/{job_id}` (`lib/api.ts`'s `postChat()`, which
still exposes a plain `Promise<ChatResponse>` to callers — polling is an
implementation detail). The job store is in-memory and process-local, correct for
this project's single-container deployment; it would need to become a shared store
(e.g. a DB table) if this service were ever scaled horizontally.

## `ai_disabled` behavior

SQL generation from natural language requires an LLM — there is no natural-language
understanding without one. So when `OPENAI_API_KEY` is unset, the orchestrator's
`ANALYSIS`/`DATA_PREVIEW`/`EXPLAIN_WHY` path returns `ChatResponse(error="ai_disabled", ...)`
with a message pointing at **Recommended Reports** (`app/reports/recommended.py`,
`GET /api/recommended`, `POST /api/recommended/{id}/run`) — a small fixed catalog of
hand-written SQL "reports" that materialize into the exact same `ReportSpec` shape
via `report_agent.heuristic_report()`/`_materialize_report()`, with zero LLM calls.
Everything downstream of "I already have real query rows" (analytics, report
rendering, exports, PNG) works identically with or without AI.

## SQL safety pipeline

Every AI-generated (or hand-written recommended-report) SQL string passes through
`app/security/sql_guard.py::validate_sql()` before it ever reaches a database
connection:

1. Reject if a forbidden keyword appears anywhere (`INSERT/UPDATE/DELETE/DROP/
   ALTER/TRUNCATE/CREATE/GRANT/REVOKE/ATTACH/PRAGMA/EXEC/...`) — defense in depth.
2. Reject multi-statement input (`;` followed by more content).
3. Parse with `sqlglot`; reject if it isn't a single `SELECT`/`WITH`/`UNION` AST, or
   if the AST contains any forbidden construct node type anywhere in the tree
   (`exp.Insert`, `exp.Update`, `exp.Delete`, `exp.Drop`, `exp.Alter`, `exp.Create`,
   `exp.TruncateTable`, `exp.Grant`, `exp.Merge`, `exp.Command`, ...).
4. (Optional) Reject if it references a table outside the known-tables allowlist.
5. Inject/clamp a `LIMIT` to `SQL_MAX_ROWS` on the outermost statement.
6. Audit-log the outcome (`sql_audit_log` table) regardless of pass/fail.

Only after all of the above does `app/query_engine/executor.py` execute the
resulting SQL, against the "readonly" SQLAlchemy engine (a real read-only Postgres
role in production; in SQLite dev there are no roles, so this AST-level gate is the
enforced boundary — see `DATABASE.md`).

## Image generation boundary (structural, not just documented)

`app/ai/image_client.py::generate_decorative_image(title: str, theme: str) -> str | None`
is the only code path that calls an image-generation model. Its signature accepts
only two plain strings — there is no parameter through which row data, KPI values,
chart series, or table contents could be passed in, and the module has no import of
`app.query_engine`, `app.analytics`, or any `ReportSpec`/row type. The prompt builder
interpolates only `title`/`theme` into a fixed template that explicitly instructs the
model to draw abstract/decorative art and never numbers, charts, or data-like text.
See `AI_ARCHITECTURE.md` for the full rationale.

## Frontend

Two primary routes: `/` (Chat home) and `/data` (read-only schema/database
explorer). No dashboard-canvas/drag-resize builder in this MVP (explicit product
pivot, see `CLAUDE.md`). Charts render client-side via ECharts from the `ReportSpec`
JSON + real row data the backend returns — no image-generation model ever touches
chart pixels. PNG export renders the actual report DOM node client-side
(`html-to-image`); CSV/XLSX export call the backend with the report's real rows.
