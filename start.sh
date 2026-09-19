#!/usr/bin/env bash
set -euo pipefail

# Next.js standalone server, internal only.
PORT=3000 node /app/frontend-standalone/server.js &

# FastAPI on Render's assigned $PORT, proxies non-/api requests to the frontend.
cd /app/backend
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
