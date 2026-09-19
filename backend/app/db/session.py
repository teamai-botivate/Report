from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.core.config import get_settings

settings = get_settings()


class Base(DeclarativeBase):
    pass


def _engine_kwargs(url: str) -> dict:
    kwargs: dict = {"echo": False, "future": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        # Neon/Postgres over pgbouncer-less serverless: NullPool + pre_ping avoids
        # stale-connection 500s seen in production (see CLAUDE.md known bug #... fix).
        kwargs["poolclass"] = NullPool
        kwargs["pool_pre_ping"] = True
        kwargs["connect_args"] = {"ssl": True} if "asyncpg" in url else {}
    return kwargs


# Primary (read/write) engine — used for app data, seeding, migrations.
engine = create_async_engine(settings.database_url_effective, **_engine_kwargs(settings.database_url_effective))
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

# Secondary read-only engine — used ONLY for AI-generated analytical SELECTs after
# they pass the sqlglot AST allowlist in app/security/sql_guard.py. In Postgres/Neon
# production this should point at a real read-only DB role via DATABASE_URL_READONLY;
# SQLite has no roles, so in dev the AST-level gate is the enforced boundary.
readonly_engine = create_async_engine(
    settings.database_url_readonly_effective, **_engine_kwargs(settings.database_url_readonly_effective)
)
ReadonlySessionLocal = async_sessionmaker(readonly_engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def get_readonly_db() -> AsyncGenerator[AsyncSession, None]:
    async with ReadonlySessionLocal() as session:
        yield session
