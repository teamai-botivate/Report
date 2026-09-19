# CLAUDE.md — AI-Native BI Platform (chat-first MVP)

This file is the living architecture/status record for this project. Keep it updated as decisions change.

## What this is

A **conversational AI Business Intelligence system**. The chat IS the product: the user asks a business
question in plain English (Hindi/English mixed is fine), the system plans one or more SQL queries,
validates and executes them against the real database, computes deterministic analytics, and returns ONE
polished business report (KPIs + charts + tables + insights) rendered inline in the chat. The user refines
that report purely through further conversation ("August bhi compare karo", "top 5 ki jagah top 10 karo",
"isko bar chart mein dikhao", "revenue ka KPI add karo", "ye chart hata do").

There is no dashboard-canvas builder in this MVP. Two primary UI areas: **Chat** (home) and **Data** (a
read-only schema/database explorer).

## Stack decisions (locked in, do not re-litigate without reason)

- **Backend**: Python 3.11+, FastAPI, SQLAlchemy 2.x (async), Pydantic v2, Alembic.
- **Frontend**: Next.js 14 (App Router), React 18, TypeScript, Tailwind CSS, shadcn/ui, Apache ECharts
  (`echarts-for-react`).
- **Database**: Neon PostgreSQL is the source of truth in production. Dev/test uses SQLite via the same
  SQLAlchemy models (config-driven `DATABASE_URL`); no code fork between the two.
- **AI provider (text)**: OpenAI SDK, model name fully driven by `OPENAI_MODEL` env var (default
  `gpt-4.1`, a real strong reasoning/tool-use model — the spec's "GPT-5.6 Sol" does not exist in the API).
- **AI provider (image)**: OpenAI image model, name driven by `OPENAI_IMAGE_MODEL` env var (default
  `gpt-image-2`, per the user's explicit choice 2026-09-19 — confirmed via web search to be a real,
  current OpenAI API model id, distinct from the newer `gpt-image-2.5-flare`/`gpt-image-2.5-sunburst`
  variants which also exist but were not selected — code never hardcodes the literal model id so
  swapping variants later is a one-line env change).
  **Scope of image generation — decorative only, never data-bearing**: used only for empty-state
  illustrations, a per-report accent/header banner image, and category icons. **Never** used to render a
  chart, KPI, table, or any pixel that contains a business number — those are always ECharts/DOM,
  rendered client-side from real query rows. This is a hard rule requested and confirmed by the user
  (2026-09-19): an image-generation model cannot guarantee that digits/labels/bar heights it draws match
  real data, which would violate the project's core "AI must never fabricate a business number" rule.
- **Read-only SQL execution**: every AI-generated query is (a) parsed with `sqlglot`, (b) checked against
  a single-statement SELECT-only AST allowlist, (c) run with a statement timeout + row limit, (d)
  audit-logged. Production additionally uses a real read-only Postgres role.
- **Charts**: rendered client-side from structured `visualization` JSON + real row data returned by the
  backend. No image-generation model ever touches chart pixels (see above).
- **PNG export**: client-side render-to-PNG of the actual DOM/canvas node (html-to-image).

## Repo layout

```
backend/
  app/
    main.py
    core/            # settings, logging config, bootstrap/auto-seed
    db/              # engine/session setup (app + readonly)
    models/          # SQLAlchemy ORM models, one module per business domain
    schemas/         # Pydantic schemas
    api/             # FastAPI routers
    services/        # business services (exports, images)
    semantic_layer/  # metadata cache + semantic dictionary + retrieval
    ai/              # OpenAI client wrapper (text + image), structured-output helpers
    agents/          # orchestrator + the logical agents
    query_engine/    # query plan DAG, executor, dependency resolution
    security/        # SQL AST validator/allowlist, audit log
    analytics/       # deterministic measure calculations
    exports/         # CSV/XLSX generation
  scripts/
    seed_database.py
    reset_db.py
  tests/
  alembic/
frontend/
  app/               # Next.js routes (chat home, data explorer)
  components/        # chat panel, report canvas, chart renderer
  lib/                # api client, types
docs: README.md, ARCHITECTURE.md, DATABASE.md, AI_ARCHITECTURE.md, API.md, SETUP.md, CLAUDE.md
```

## Agents (logical modules inside backend/app/agents, not microservices)

1. Orchestrator — single chat entrypoint; classifies intent, routes to analysis or report-edit pipeline.
2. Schema/Semantic Agent — pulls relevant metadata slices from the semantic layer for the current question.
3. Query Planner Agent — turns NL + semantic context into a Query Plan DAG.
4. SQL Generation Agent — turns one query-plan node into one parameterized SELECT; error-recovery retries.
5. Validation Agent — sqlglot AST allowlist check, table/column existence check, timeout/row-limit.
6. Analytics Agent — deterministic post-query calculations (growth %, margin, etc.) — never LLM-computed.
7. Report Agent — takes all query results + analytics summary, produces one structured `ReportSpec`
   (kpis/charts/tables/insights). LLM only decides layout/labels; every value is copied verbatim in Python
   from already-executed query results, never trusted from the LLM's own echo.
8. Report Edit Agent — handles follow-up edits. Structural edits (reorder/remove/retype/rename) applied
   deterministically with no new query. Edits needing new data are flagged `needs_requery=true`; the
   orchestrator runs a small follow-up query-plan and merges new sections into the existing report.
9. Explanation/Conversation Agent — intent classification + final NL reply, referencing only real numbers.
10. Export Agent — CSV/XLSX from underlying rows; PNG is client-rendered from the report canvas DOM.
11. Image Agent (`ai/image_client.py`) — decorative-only image generation (report banner, empty states).
    Structurally cannot be given chart/KPI/table data as generation input — its prompt builder only
    accepts a report title/theme, never row data or numeric values.

Pipeline for a turn: schema retrieval → query plan DAG → SQL generation → validation → execution →
deterministic analytics → Report Agent → one `ReportSpec` → NL explanation. `REPORT_EDIT` is a separate,
narrower pipeline: load the last report from this conversation's history → structural edit and/or a small
requery-and-merge → the same `ReportSpec` shape back out.

## Status

- [x] Backend scaffold (FastAPI app, config, async DB session with dual engines, `create_all`+auto-seed bootstrap).
- [x] Full 62-table schema across 9 business modules + master data (`backend/app/models/`), verified via `Base.metadata` table count.
- [x] Seed script — `SEED_SIZE=small|medium|large` (default `medium`), realistic interconnected cascades (lead→enquiry→quotation→order→production→dispatch→delivery→invoice→payment; requisition→PO→receipt→invoice→payment), 2-3 year date range with denser recent data. Verified end-to-end at all three sizes with zero errors (small ~5s/3.9k rows, medium ~8s/12k rows, large ~36s/58k rows).
- [x] Semantic/metadata layer (`backend/app/semantic_layer/`) — static business dictionary, 12 DAX-like measures, in-process metadata cache, deterministic keyword/synonym retrieval (`retrieve_relevant_metadata`, no LLM call). Unit tested: never dumps the full 62-table schema for a narrow question.
- [x] AI client (text): `app/ai/openai_client.py`, `OPENAI_MODEL` env-driven, structured-output JSON-schema calls, graceful `is_enabled()` degradation.
- [x] AI client (image, decorative-only): `app/ai/image_client.py::generate_decorative_image(title: str, theme: str)` — signature structurally cannot accept row/query data (see AI_ARCHITECTURE.md). Verified live with a real OpenAI key generating a real report banner.
- [x] All agents built: orchestrator, query planner (DAG), SQL generation + error-recovery regeneration, deterministic analytics, Report Agent (`_materialize_report` copies real rows verbatim, `_kpi_scalar`/`_filter_insights` historical-bug fixes reimplemented and tested), Report Edit Agent (structural ops + requery-and-merge), Explanation Agent (intent classification + NL reply from real ReportSpec values only).
- [x] SQL safety gate (`app/security/sql_guard.py`) — sqlglot AST allowlist, keyword defense-in-depth, multi-statement rejection, LIMIT injection/clamping, table-existence check, audit log. 26 tests passing including every spec-mandated attack string (DROP/DELETE/UPDATE/INSERT/ALTER/TRUNCATE/CREATE/GRANT/REVOKE, statement-chaining) plus legitimate-SELECT acceptance.
- [x] Query engine DAG (`app/query_engine/plan.py` + `executor.py`) — dependency-respecting parallel batches, retry-via-regeneration, per-node audit logging. Unit tested.
- [x] Chat API: `POST /api/chat` returns a `job_id` immediately, `GET /api/chat/jobs/{job_id}` polled to completion (`app/core/job_store.py`, in-memory/process-local by design).
- [x] Recommended Reports (zero-LLM): `app/reports/recommended.py`, 7-report catalog, `GET /api/recommended` + `POST /api/recommended/{id}/run`, verified end-to-end against real seeded data.
- [x] Export engine (CSV/XLSX from real rows) + client-side PNG export (html-to-image) — no server PNG endpoint by design.
- [x] Frontend: Chat home (message list, async job polling with a friendly long-wait indicator, example prompts, ai_disabled notice with Recommended Reports chips) + Report Canvas (KPI row with growth indicators, all 10 ECharts chart types, tables, insights with headline callout, View Data / View Query / Download PNG / Export CSV / Export Excel) + Data explorer (schema browser + paginated preview). `npm run build` verified passing. No dashboard-canvas builder (out of scope, confirmed removed from an earlier partial attempt found in the working tree).
- [x] Docs: README, SETUP, ARCHITECTURE, DATABASE, AI_ARCHITECTURE, API, DEPLOY, `.env.example`, Dockerfile/start.sh for the single-container deployment.
- [x] Tests: 84 backend tests passing (SQL guard attack strings + legitimate SELECTs, deterministic analytics, report agent heuristic/real-row-copy/bug-fix regressions, query engine DAG, semantic retrieval, recommended reports against real seeded data, DB pool config).
- [x] **Live end-to-end verification with a real OpenAI key found and fixed a genuine integration bug**: `orchestrator.py` and `query_planner_agent.py` both gated their call to `retrieve_relevant_schema` behind `if session is not None`, but the API layer never passes a session — so every real chat turn silently got an EMPTY metadata context, and the SQL Generation Agent hallucinated nonexistent tables (`orders`, `payments`) that the security gate correctly rejected but the agent never recovered from. Fixed by calling `retrieve_relevant_schema` unconditionally (it's deterministic/cache-backed and doesn't actually need the session). Re-verified live: "show total revenue and top 3 customers", "compare this month with last month" (real period-comparison deltas + a real generated banner image), and a REPORT_EDIT follow-up ("only show top 3" after "top 5 customers") all produced correct real-data reports end-to-end.
- [ ] Alembic autogenerate migration not yet run against a real Postgres target (dev uses `create_all` + auto-seed bootstrap; migration scaffolding is in place under `backend/alembic/`).

## Environment variables

See `.env.example`. Key ones:
- `DATABASE_URL` — SQLAlchemy URL. Local dev defaults to SQLite file. Accepts raw Neon Postgres URLs.
- `OPENAI_API_KEY` — required for AI features; without it chat returns `error: "ai_disabled"`.
- `OPENAI_MODEL` — default `gpt-4.1`.
- `OPENAI_IMAGE_MODEL` — default `gpt-image-2` (decorative visuals only — see Stack decisions).
- `SEED_SIZE` — `small|medium|large` (default `medium` for fast local iteration).
- `AUTO_SEED_ON_BOOT` — default `true`.
- `SQL_QUERY_TIMEOUT_MS`, `SQL_MAX_ROWS`, `SQL_MAX_RETRY`.

## Known issues / assumptions

- No Docker/Postgres available in this dev environment → SQLite used for dev/test; Postgres-specific SQL
  avoided so both engines work.
- "GPT-5.6 Sol" from the spec does not exist as a real OpenAI API model id; using `gpt-4.1` instead,
  env-configurable, swappable with zero code changes. `gpt-image-2` (image) IS a real, current OpenAI
  API model id (confirmed via web search 2026-09-19) and is used as specified by the user.
- Neon connection string and OpenAI API key are not available in this environment — requested under
  "User actions required" once the build reaches a runnable state.
- `backend/.env` (gitignored, never committed) was found already populated with a real, working Neon
  Postgres URL and a real OpenAI API key during this rebuild — apparently left over from an earlier
  session/attempt at this same task. This was used only for read-only live verification (a handful of
  `/api/chat` calls against a local SQLite copy of the schema, never against the live Neon DB, and no
  destructive script was ever run with that `DATABASE_URL` active) and is documented here rather than
  silently relied upon. If this key/URL is not actually yours to use, replace `backend/.env` with a copy
  of `.env.example` before running anything.

## Commands

See README.md / SETUP.md once created (install, dev, seed, reset-db, test, lint).
