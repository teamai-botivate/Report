# DEPLOY

Single Render Web Service, Docker environment, built from the root `Dockerfile` — no
`render.yaml`. One container runs both processes: `uvicorn` on Render's `$PORT`
(serves `/api/*`) and a Next.js standalone server on internal `127.0.0.1:3000`;
FastAPI proxies every non-`/api` request to it
(`backend/app/core/static_frontend.py`, activated via `FRONTEND_PROXY_URL`, which
the Dockerfile sets).

## Render dashboard steps

1. New Web Service → connect this repo → Environment: **Docker** → root Dockerfile.
2. Set environment variables (Render dashboard → Environment):
   - `DATABASE_URL` — your Neon Postgres connection string (console format is fine).
   - `DATABASE_URL_READONLY` — optional, a read-only Postgres role DSN.
   - `OPENAI_API_KEY`, `OPENAI_MODEL` (optional), `OPENAI_IMAGE_MODEL` (optional).
   - `SEED_SIZE` (default `medium`), `AUTO_SEED_ON_BOOT` (default `true`).
   - `CORS_ORIGINS` — your Render service's own URL (same-origin via the proxy, so
     usually not strictly needed, but set it to be safe).
   - Do **not** set `FRONTEND_PROXY_URL` yourself — the Dockerfile sets it.
3. Deploy. First boot will `create_all` the schema against Neon and auto-seed if the
   `customers` table is empty.

## Local development (no Docker)

Two separate processes, `FRONTEND_PROXY_URL` unset:
```bash
cd backend && uvicorn app.main:app --reload --port 8000
cd frontend && npm run dev
```
Both modes (Docker single-container, or separate local dev processes) are supported
by the same codebase — the only switch is whether `FRONTEND_PROXY_URL` is set.

## Known Docker build issues already fixed here

- `npm ci` can false-positive-fail on lockfile-sync checks in constrained CI
  environments — the Dockerfile uses `npm install` instead.
- The frontend build needs a `frontend/public/` directory to exist even if empty
  (kept via `frontend/public/.gitkeep`), otherwise the Next.js build/COPY step fails.
