# AI-Native BI Platform (chat-first MVP)

A conversational AI Business Intelligence system. The chat IS the product: ask a
business question in plain English, get back one polished report (KPIs + charts +
tables + insights) generated from real database queries, then refine it through
further conversation.

See `CLAUDE.md` for the full architecture/status record and `prompt.txt` for the
original raw requirements.

## Quick start (local, no Docker, no credentials required)

```bash
# 1. Backend
cd backend
python -m venv .venv
. .venv/Scripts/activate   # Windows; use `source .venv/bin/activate` on macOS/Linux
pip install -r requirements.txt
cp ../.env.example .env    # edit if you have real credentials; safe to leave blank
uvicorn app.main:app --reload --port 8000

# On first boot with an empty DB, the app auto-seeds SQLite with realistic demo data
# (SEED_SIZE=medium by default) — no manual seeding step required.

# 2. Frontend (separate terminal)
cd frontend
npm install
cp .env.local.example .env.local
npm run dev
```

Open http://localhost:3000 — you'll land on the Chat home screen. With no
`OPENAI_API_KEY` set, chat shows an "AI disabled" notice with one-click
**Recommended Reports** buttons that work with zero LLM calls (real seeded data,
hand-written SQL, deterministic rendering). Once you add a real `OPENAI_API_KEY` to
`backend/.env` and restart the backend, full natural-language chat/report-editing
turns on automatically — no code changes.

## Commands

| Task | Command |
|---|---|
| Install backend deps | `cd backend && pip install -r requirements.txt` |
| Run backend (dev) | `cd backend && uvicorn app.main:app --reload --port 8000` |
| Seed database | `cd backend && python -m scripts.seed_database` (reads `SEED_SIZE` env var) |
| Reset database | `cd backend && python -m scripts.reset_db --yes` |
| Run backend tests | `cd backend && python -m pytest` |
| Install frontend deps | `cd frontend && npm install` |
| Run frontend (dev) | `cd frontend && npm run dev` |
| Build frontend | `cd frontend && npm run build` |
| Lint frontend | `cd frontend && npm run lint` |

See `SETUP.md` for a more detailed walkthrough, `DEPLOY.md` for the Render/Docker
single-container deployment, and `.env.example` for every environment variable.

## What's real vs. what needs your credentials

Everything in this repo runs today, locally, on SQLite, with zero external
credentials: schema, seeding, the semantic layer, the SQL safety gate, the query
engine, deterministic analytics, heuristic/recommended reports, exports, and the
full chat + Data-explorer frontend.

To light up **live natural-language chat** and **decorative report banners** you
must supply, in `backend/.env`:

- `OPENAI_API_KEY` (+ optionally `OPENAI_MODEL`, default `gpt-4.1`)
- `OPENAI_IMAGE_MODEL` (optional, default `gpt-image-2`) — decorative banners only,
  never used to render a chart/KPI/table (see `AI_ARCHITECTURE.md`).

To run against **Neon Postgres** instead of local SQLite, set `DATABASE_URL` to your
Neon connection string (Neon-console format accepted as-is) — no code changes
required, see `DATABASE.md`.
