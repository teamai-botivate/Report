# SETUP

## Prerequisites

- Python 3.11 or 3.12 (3.12 recommended — several pinned dependencies, e.g. `pydantic`/`asyncpg`, have no prebuilt wheels for 3.14 yet and require a C/Rust toolchain to build from source; verified end-to-end on 3.12)
- Node.js 18+ and npm
- No Docker/Postgres required for local dev — SQLite is the default `DATABASE_URL`.

## Backend

```bash
cd backend
python -m venv .venv
. .venv/Scripts/activate        # Windows (Git Bash / PowerShell: .venv\Scripts\Activate.ps1)
pip install -r requirements.txt
```

Copy the root `.env.example` into `backend/.env` and adjust as needed (safe to leave
`OPENAI_API_KEY` blank):

```bash
cp ../.env.example .env
```

Run the API:

```bash
uvicorn app.main:app --reload --port 8000
```

On startup (`app/core/bootstrap.py`):
1. `Base.metadata.create_all` ensures every table exists (SQLite: creates `bi_platform.db` in `backend/`).
2. If `AUTO_SEED_ON_BOOT=true` (default) and the `customers` table is empty, it seeds automatically using `SEED_SIZE` (default `medium`).
3. The semantic metadata cache is refreshed.

To seed manually (e.g. after `reset_db`):

```bash
python -m scripts.seed_database          # uses SEED_SIZE from env, default medium
SEED_SIZE=large python -m scripts.seed_database   # bash
$env:SEED_SIZE="large"; python -m scripts.seed_database   # PowerShell
```

To wipe and recreate the schema:

```bash
python -m scripts.reset_db --yes
```

Run tests:

```bash
python -m pytest
```

## Frontend

```bash
cd frontend
npm install
cp .env.local.example .env.local   # NEXT_PUBLIC_API_URL defaults to http://localhost:8000
npm run dev
```

Open http://localhost:3000.

## Switching to Neon Postgres

1. Create a Neon project and copy its connection string (console format is fine,
   e.g. `postgresql://user:pass@ep-xxxx.neon.tech/dbname?sslmode=require&channel_binding=require`).
2. Set `DATABASE_URL` in `backend/.env` to that string.
3. Restart the backend — `app/core/config.py`'s `_normalize_database_url` rewrites it
   to the asyncpg-compatible form automatically; `create_all` + auto-seed run exactly
   as they do against SQLite (no code fork).
4. (Optional, recommended for production) Provision a read-only Postgres role and set
   `DATABASE_URL_READONLY` to its DSN — AI-generated analytical SELECTs then run
   against that role instead of the primary connection.

## Enabling live AI chat

Set in `backend/.env`:

```
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4.1          # optional, this is already the default
OPENAI_IMAGE_MODEL=gpt-image-2   # optional, decorative banners only
```

Restart the backend. No frontend or code changes are required — the orchestrator
detects `OPENAI_API_KEY` at request time and switches from the heuristic/recommended
pipeline to full natural-language query planning + SQL generation + report
composition automatically.

## Docker (single-container deployment)

See `DEPLOY.md`.
