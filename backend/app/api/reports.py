"""GET /api/reports/{id} — fetch a previously generated report by its ReportSpec id.

Reports are not given their own persistent store in this MVP; they live inside the
in-memory conversation history in app/api/chat.py. This endpoint does a best-effort
scan of that history so a frontend can deep-link/reload a report within the same
process lifetime.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/{report_id}")
async def get_report(report_id: str) -> dict:
    from app.api.chat import _conversations

    for turns in _conversations.values():
        for turn in turns:
            report = turn.get("report")
            if report and report.get("id") == report_id:
                return report
    raise HTTPException(status_code=404, detail="Report not found (process may have restarted)")
