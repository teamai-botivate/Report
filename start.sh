#!/usr/bin/env bash
set -euo pipefail

# Next.js standalone server, internal only. HOSTNAME must be set explicitly —
# the standalone server.js defaults to binding "localhost" on some Next
# versions, which is NOT the same interface as 127.0.0.1 inside every
# container network namespace and causes the FastAPI proxy's ConnectError.
HOSTNAME=127.0.0.1 PORT=3000 node /app/frontend-standalone/server.js &

# Wait for the frontend to actually accept connections before FastAPI starts
# proxying to it, so the first real request doesn't race Next's own startup.
for i in $(seq 1 30); do
  if curl -sf "http://127.0.0.1:3000" -o /dev/null; then
    break
  fi
  sleep 0.5
done

# FastAPI on Render's assigned $PORT, proxies non-/api requests to the frontend.
cd /app/backend
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
