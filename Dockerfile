# Single-container deployment: uvicorn (FastAPI, $PORT) + Next.js standalone
# server (internal 127.0.0.1:3000), FastAPI reverse-proxies non-/api requests.
# See DEPLOY.md.

# ---- Frontend build stage ----
FROM node:20-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ ./
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# ---- Final image ----
FROM python:3.12-slim
WORKDIR /app

# Node runtime for the Next.js standalone server
RUN apt-get update && apt-get install -y --no-install-recommends curl gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Backend
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ ./backend/

# Frontend (standalone output)
COPY --from=frontend-build /app/frontend/.next/standalone ./frontend-standalone
COPY --from=frontend-build /app/frontend/.next/static ./frontend-standalone/.next/static
COPY --from=frontend-build /app/frontend/public ./frontend-standalone/public

ENV FRONTEND_PROXY_URL=http://127.0.0.1:3000
ENV PYTHONUNBUFFERED=1

COPY start.sh ./start.sh
RUN chmod +x ./start.sh

EXPOSE 8000
CMD ["./start.sh"]
