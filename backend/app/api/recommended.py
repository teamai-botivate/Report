"""GET /api/recommended, POST /api/recommended/{id}/run — zero-LLM one-click reports.
See app/reports/recommended.py for the catalog and CLAUDE.md "Recommended Reports".
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException

from app.reports.recommended import list_catalog, run_recommended
from app.schemas.report import ChatResponse

router = APIRouter(prefix="/recommended", tags=["recommended"])


@router.get("")
async def get_recommended() -> list[dict]:
    return list_catalog()


@router.post("/{report_id}/run")
async def post_run_recommended(report_id: str) -> ChatResponse:
    try:
        report = await run_recommended(report_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    conversation_id = str(uuid.uuid4())
    from app.api.chat import append_turn

    append_turn(conversation_id, "assistant", f"Here is the {report.title} report.", report.model_dump())

    return ChatResponse(
        conversation_id=conversation_id,
        message=f"Here is the {report.title} report.",
        intent="ANALYSIS",
        report=report,
    )
