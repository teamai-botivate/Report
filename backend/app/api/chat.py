"""POST /api/chat returns a job_id almost immediately; the frontend polls
GET /api/chat/jobs/{job_id}. See CLAUDE.md "Chat runs as a background job".
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.core.job_store import job_store
from app.schemas.report import ChatRequest, ChatResponse, JobEnqueueResponse, JobStatusResponse

logger = logging.getLogger("app.api.chat")
router = APIRouter(tags=["chat"])

# In-memory per-conversation history: conversation_id -> list of turn dicts
# {"role": "user"|"assistant", "message": str, "report": dict | None}
# Process-local, matching the job store's single-container assumption.
_conversations: dict[str, list[dict]] = {}


def get_conversation_history(conversation_id: str) -> list[dict]:
    return _conversations.get(conversation_id, [])


def append_turn(conversation_id: str, role: str, message: str, report: dict | None = None) -> None:
    _conversations.setdefault(conversation_id, []).append(
        {"role": role, "message": message, "report": report}
    )


async def _run_chat_job(job_id: str, message: str, conversation_id: str) -> None:
    await job_store.set_running(job_id)
    try:
        from app.agents.orchestrator import handle_chat_turn

        history = get_conversation_history(conversation_id)
        response: ChatResponse = await handle_chat_turn(message, conversation_id, history)

        append_turn(conversation_id, "user", message)
        append_turn(
            conversation_id,
            "assistant",
            response.message,
            response.report.model_dump() if response.report else None,
        )

        await job_store.set_done(job_id, response.model_dump())
    except Exception as exc:  # noqa: BLE001
        logger.exception("Chat job %s failed", job_id)
        await job_store.set_error(job_id, str(exc))


@router.post("/chat", response_model=JobEnqueueResponse)
async def post_chat(payload: ChatRequest, background_tasks: BackgroundTasks) -> JobEnqueueResponse:
    conversation_id = payload.conversation_id or str(uuid.uuid4())
    job = await job_store.create()
    background_tasks.add_task(_run_chat_job, job.id, payload.message, conversation_id)
    return JobEnqueueResponse(job_id=job.id)


@router.get("/chat/jobs/{job_id}", response_model=JobStatusResponse)
async def get_chat_job(job_id: str) -> JobStatusResponse:
    job = await job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    result = ChatResponse(**job.result) if job.result else None
    return JobStatusResponse(job_id=job.id, status=job.status, result=result, error=job.error)
