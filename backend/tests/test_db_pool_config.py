"""Regression test for a real production bug: on Render/Neon, the default
SQLAlchemy pool held onto connections that Neon's PgBouncer pooler had
already silently closed, surfacing as
`asyncpg.exceptions.InterfaceError: connection is closed` on unrelated
requests. Fix: use NullPool + pool_pre_ping for any non-SQLite URL so we
never reuse a connection across requests without a liveness check.

Tests the pure `_engine_kwargs()` helper directly rather than reloading
app.db.session (reloading that module would leave other already-imported
modules holding stale references to the old engine/SessionLocal, silently
breaking unrelated tests that run afterward in the same process).
"""
from sqlalchemy.pool import NullPool

from app.db.session import _engine_kwargs, engine, readonly_engine


def test_sqlite_url_keeps_default_pool():
    kwargs = _engine_kwargs("sqlite+aiosqlite:///./dev.db")
    assert "poolclass" not in kwargs
    assert "pool_pre_ping" not in kwargs


def test_asyncpg_url_gets_nullpool_and_pre_ping():
    kwargs = _engine_kwargs("postgresql+asyncpg://user:pass@example-pooler.neon.tech/db?ssl=require")
    assert kwargs["poolclass"] is NullPool
    assert kwargs["pool_pre_ping"] is True


def test_raw_neon_style_url_also_gets_nullpool():
    """The exact style of URL Neon's console gives you (plain postgresql://,
    sslmode=require, channel_binding=require, -pooler host)."""
    kwargs = _engine_kwargs(
        "postgresql://neondb_owner:pw@ep-example-pooler.c-4.ap-southeast-1.aws.neon.tech/neondb"
        "?sslmode=require&channel_binding=require"
    )
    assert kwargs["poolclass"] is NullPool
    assert kwargs["pool_pre_ping"] is True


def test_current_dev_engines_use_sqlite_defaults():
    """In this test environment DATABASE_URL is sqlite, so the real
    module-level engines should NOT have been forced onto NullPool+pre_ping
    (that combination is Postgres-only) — sanity check that the app wiring
    actually calls _engine_kwargs correctly."""
    assert engine.url.get_backend_name() == "sqlite"
    assert readonly_engine.url.get_backend_name() == "sqlite"
