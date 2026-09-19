"""In-memory, process-local async job store for the chat background-job pattern.

Why: a complex multi-query chat turn can trigger several sequential OpenAI calls
(intent classification, query planning, one SQL-generation call per node, report
composition, explanation), which can take long enough that a hosting proxy in front
of the app drops the connection before a single blocking POST /api/chat finishes.
POST /api/chat returns a job_id almost immediately; the frontend polls
GET /api/chat/jobs/{job_id} until status is "done" or "error".

This store is in-memory and per-process, which is correct for a single-container
deployment. It would need to become a shared store (e.g. a DB table) if this
service were ever horizontally scaled to multiple instances.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from app.core.config import get_settings

settings = get_settings()

JobStatus = Literal["pending", "running", "done", "error"]


@dataclass
class Job:
    id: str
    status: JobStatus = "pending"
    result: Any = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = asyncio.Lock()

    async def create(self) -> Job:
        job = Job(id=str(uuid.uuid4()))
        async with self._lock:
            self._jobs[job.id] = job
            self._gc_locked()
        return job

    async def set_running(self, job_id: str) -> None:
        async with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id].status = "running"
                self._jobs[job_id].updated_at = time.time()

    async def set_done(self, job_id: str, result: Any) -> None:
        async with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id].status = "done"
                self._jobs[job_id].result = result
                self._jobs[job_id].updated_at = time.time()

    async def set_error(self, job_id: str, error: str) -> None:
        async with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id].status = "error"
                self._jobs[job_id].error = error
                self._jobs[job_id].updated_at = time.time()

    async def get(self, job_id: str) -> Job | None:
        async with self._lock:
            return self._jobs.get(job_id)

    def _gc_locked(self) -> None:
        cutoff = time.time() - settings.JOB_TTL_SECONDS
        stale = [jid for jid, j in self._jobs.items() if j.updated_at < cutoff]
        for jid in stale:
            del self._jobs[jid]


job_store = JobStore()
