"""GET /api/schema — structural schema browser for the frontend Data explorer.
Read-only, reflects from SQLAlchemy Base.metadata (already loaded at import time
by importing app.models), so it never hits information_schema per-request.
"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["schema"])


@router.get("/schema")
async def get_schema() -> list[dict]:
    import app.models  # noqa: F401 - ensure models are registered
    from app.db.session import Base

    tables = []
    for table in Base.metadata.sorted_tables:
        fk_map = {}
        for fk in table.foreign_keys:
            fk_map[fk.parent.name] = f"{fk.column.table.name}.{fk.column.name}"

        columns = []
        for col in table.columns:
            columns.append(
                {
                    "name": col.name,
                    "type": str(col.type),
                    "is_pk": col.primary_key,
                    "is_fk": col.name in fk_map,
                    "references": fk_map.get(col.name),
                    "nullable": col.nullable,
                }
            )
        tables.append({"table": table.name, "columns": columns})
    return tables
