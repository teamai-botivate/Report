"""POST /api/export/csv and /api/export/excel — real query result rows, not
screenshot data. PNG export is deliberately client-side only (no server endpoint).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel

from app.exports.export_engine import rows_to_csv_bytes, rows_to_xlsx_bytes

router = APIRouter(prefix="/export", tags=["export"])


class ExportRequest(BaseModel):
    rows: list[dict[str, Any]]
    columns: list[str] | None = None
    filename: str | None = None


@router.post("/csv")
async def export_csv(payload: ExportRequest) -> Response:
    data = rows_to_csv_bytes(payload.rows, payload.columns)
    filename = (payload.filename or "export") + ".csv"
    return Response(
        content=data,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/excel")
async def export_excel(payload: ExportRequest) -> Response:
    data = rows_to_xlsx_bytes(payload.rows, payload.columns, sheet_title=payload.filename or "Data")
    filename = (payload.filename or "export") + ".xlsx"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
