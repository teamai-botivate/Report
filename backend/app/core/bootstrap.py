"""Startup bootstrap: create tables, auto-seed if empty, refresh semantic metadata cache.

Idempotent: a second boot against an already-seeded database is a fast no-op.
"""
from __future__ import annotations

import logging

from sqlalchemy import select, text

from app.core.config import get_settings
from app.db.session import Base, engine, AsyncSessionLocal

logger = logging.getLogger("app.bootstrap")
settings = get_settings()


async def _database_is_empty() -> bool:
    async with AsyncSessionLocal() as session:
        try:
            # customers is a core master table present from the first migration onward.
            result = await session.execute(text("SELECT COUNT(*) FROM customers"))
            count = result.scalar_one()
            return count == 0
        except Exception:  # noqa: BLE001 - table may not exist yet
            return True


async def run_bootstrap() -> None:
    import app.models  # noqa: F401 - ensure all models are registered on Base.metadata

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database schema ensured (create_all).")

    if settings.AUTO_SEED_ON_BOOT:
        empty = await _database_is_empty()
        if empty:
            logger.info("Database is empty — auto-seeding (SEED_SIZE=%s)...", settings.SEED_SIZE)
            from scripts.seed_database import seed_all

            await seed_all(settings.SEED_SIZE)
            logger.info("Auto-seed complete.")
        else:
            logger.info("Database already has data — skipping auto-seed.")

    try:
        from app.semantic_layer.metadata_cache import refresh_metadata_cache

        await refresh_metadata_cache()
        logger.info("Semantic metadata cache refreshed.")
    except Exception:  # noqa: BLE001
        logger.exception("Metadata cache refresh failed (non-fatal at boot).")
