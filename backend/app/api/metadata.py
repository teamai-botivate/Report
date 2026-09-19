"""GET /api/metadata — semantic layer info (business descriptions, measures)."""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["metadata"])


@router.get("/metadata")
async def get_metadata() -> dict:
    try:
        from app.semantic_layer.metadata_cache import get_cached_metadata

        cached = get_cached_metadata()
        if cached:
            return cached
    except Exception:  # noqa: BLE001
        pass

    try:
        from app.semantic_layer.dictionary import MEASURES, TABLE_DESCRIPTIONS

        return {
            "measures": [m.__dict__ if hasattr(m, "__dict__") else m for m in MEASURES],
            "tables": TABLE_DESCRIPTIONS,
        }
    except Exception:  # noqa: BLE001
        return {"measures": [], "tables": {}}


@router.post("/metadata/refresh")
async def refresh_metadata() -> dict:
    from app.semantic_layer.metadata_cache import refresh_metadata_cache

    await refresh_metadata_cache()
    return {"status": "refreshed"}
