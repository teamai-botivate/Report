from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.logging_config import configure_logging

settings = get_settings()
configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.core.bootstrap import run_bootstrap

    await run_bootstrap()
    yield


app = FastAPI(title=settings.APP_NAME, version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health():
    return {"status": "ok", "app": settings.APP_NAME}


def _include_routers() -> None:
    from app.api import chat, schema, metadata, data, exports, reports, recommended

    app.include_router(chat.router, prefix="/api")
    app.include_router(schema.router, prefix="/api")
    app.include_router(metadata.router, prefix="/api")
    app.include_router(data.router, prefix="/api")
    app.include_router(exports.router, prefix="/api")
    app.include_router(reports.router, prefix="/api")
    app.include_router(recommended.router, prefix="/api")


_include_routers()

# Optional: serve the built Next.js frontend from the same container in production.
if settings.FRONTEND_PROXY_URL:
    from app.core.static_frontend import mount_frontend_proxy

    mount_frontend_proxy(app, settings.FRONTEND_PROXY_URL)
