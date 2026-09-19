"""In-process metadata cache: combines structural facts reflected from
`Base.metadata` (table names, columns, types, PKs, FKs) with the
hand-written business dictionary in `dictionary.py` (descriptions,
synonyms, measures).

This exists so the AI agents never need to hit `information_schema` or
reflect the live DB schema on every request: the cache is built once (at
process startup, via `refresh_metadata_cache()`, already called from
`app/core/bootstrap.py`) and served from memory afterwards.

Kept intentionally dependency-light: `refresh_metadata_cache()` is async
only because it is invoked from an async bootstrap context, but it does
not need a DB connection — all structural facts come from `Base.metadata`,
which is populated at import time by SQLAlchemy declarative mapping, not by
talking to the database.
"""
from __future__ import annotations

import logging
from typing import Any

from app.semantic_layer import dictionary

logger = logging.getLogger("app.semantic_layer.metadata_cache")

# Module-level in-process cache. Empty-safe: `get_cached_metadata()` returns
# `{}` if `refresh_metadata_cache()` has not run yet in this process.
_CACHE: dict[str, Any] = {}


def _reflect_structural_metadata() -> dict[str, dict[str, Any]]:
    """Build {table_name: {columns, primary_key, foreign_keys}} from
    `Base.metadata`. Imports `app.models` first to guarantee every model
    module has registered its table on `Base.metadata` before we read it.
    """
    import app.models  # noqa: F401 - ensure all 62 tables are registered
    from app.db.session import Base

    structural: dict[str, dict[str, Any]] = {}
    for table_name, table in Base.metadata.tables.items():
        columns: list[dict[str, Any]] = []
        primary_key: list[str] = []
        foreign_keys: list[dict[str, str]] = []

        for column in table.columns:
            columns.append(
                {
                    "name": column.name,
                    "type": str(column.type),
                    "nullable": bool(column.nullable),
                }
            )
            if column.primary_key:
                primary_key.append(column.name)
            for fk in column.foreign_keys:
                foreign_keys.append(
                    {
                        "column": column.name,
                        "references_table": fk.column.table.name,
                        "references_column": fk.column.name,
                    }
                )

        structural[table_name] = {
            "columns": columns,
            "primary_key": primary_key,
            "foreign_keys": foreign_keys,
        }

    return structural


def _build_metadata() -> dict[str, Any]:
    """Pure builder (no caching side effects) so it can be reused by both
    `refresh_metadata_cache()` and the lazy-build path in `retrieval.py`.
    """
    try:
        structural = _reflect_structural_metadata()
    except Exception:  # noqa: BLE001 - retrieval must still work without a DB/engine
        logger.exception("Structural metadata reflection failed; falling back to dictionary-only metadata.")
        structural = {}

    tables: dict[str, dict[str, Any]] = {}
    for table_name, info in dictionary.TABLES.items():
        struct = structural.get(table_name, {"columns": [], "primary_key": [], "foreign_keys": []})
        column_names = [c["name"] for c in struct["columns"]] or list(info.columns.keys())

        tables[table_name] = {
            "name": table_name,
            "module": info.module,
            "description": info.description,
            "synonyms": list(info.synonyms),
            "columns": column_names,
            "column_details": struct["columns"],
            "column_descriptions": {
                col_name: {"description": col.description, "synonyms": list(col.synonyms)}
                for col_name, col in info.columns.items()
            },
            "primary_key": struct["primary_key"],
            "foreign_keys": struct["foreign_keys"],
        }

    # Include any table that exists structurally but has no hand-written
    # dictionary entry yet, so the cache never silently drops a real table.
    for table_name, struct in structural.items():
        if table_name not in tables:
            tables[table_name] = {
                "name": table_name,
                "module": "unknown",
                "description": "",
                "synonyms": [],
                "columns": [c["name"] for c in struct["columns"]],
                "column_details": struct["columns"],
                "column_descriptions": {},
                "primary_key": struct["primary_key"],
                "foreign_keys": struct["foreign_keys"],
            }

    measures = [
        {
            "name": m.name,
            "expression": m.expression,
            "synonyms": list(m.synonyms),
            "format": m.format,
            "description": m.description,
        }
        for m in dictionary.MEASURES
    ]

    return {"tables": tables, "measures": measures}


async def refresh_metadata_cache() -> None:
    """Build/refresh the in-memory semantic metadata cache.

    Called once at startup from `app/core/bootstrap.py`. Safe to call again
    at any time (e.g. after a schema change) to rebuild the cache.
    """
    global _CACHE
    _CACHE = _build_metadata()
    logger.info(
        "Semantic metadata cache refreshed: %d tables, %d measures.",
        len(_CACHE["tables"]),
        len(_CACHE["measures"]),
    )


def get_cached_metadata() -> dict[str, Any]:
    """Return whatever is currently cached. Empty-safe: returns `{}` if
    `refresh_metadata_cache()` has not run yet in this process.
    """
    return _CACHE
