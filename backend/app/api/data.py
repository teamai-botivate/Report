"""GET /api/data/preview — read-only data preview for the Data explorer.
Uses the readonly engine + a hard-coded, injection-safe table allowlist derived
from Base.metadata (never string-formats user input into SQL).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select, text

from app.db.session import ReadonlySessionLocal
from app.core.config import get_settings

router = APIRouter(tags=["data"])
settings = get_settings()


def _known_tables() -> set[str]:
    import app.models  # noqa: F401
    from app.db.session import Base

    return {t.name for t in Base.metadata.sorted_tables}


@router.get("/data/preview")
async def preview_table(table: str = Query(...), limit: int = Query(50, le=500), offset: int = Query(0, ge=0)) -> dict:
    known = _known_tables()
    if table not in known:
        raise HTTPException(status_code=404, detail=f"Unknown table: {table}")

    async with ReadonlySessionLocal() as session:
        # table name is validated against the known-tables allowlist above, so this
        # is not string-interpolating unvalidated user input.
        count_result = await session.execute(text(f"SELECT COUNT(*) FROM {table}"))
        total_count = count_result.scalar_one()

        rows_result = await session.execute(
            text(f"SELECT * FROM {table} LIMIT :limit OFFSET :offset"),
            {"limit": min(limit, settings.SQL_MAX_ROWS), "offset": offset},
        )
        rows = [dict(r._mapping) for r in rows_result.fetchall()]
        columns = list(rows[0].keys()) if rows else [c["name"] for c in _columns_for(table)]

    return {
        "table": table,
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "total_count": total_count,
    }


def _columns_for(table: str) -> list[dict]:
    import app.models  # noqa: F401
    from app.db.session import Base

    t = Base.metadata.tables.get(table)
    if t is None:
        return []
    return [{"name": c.name, "type": str(c.type)} for c in t.columns]
