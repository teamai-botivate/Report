"""Shared pytest fixtures: an isolated in-memory SQLite app for API tests."""
import asyncio
import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
os.environ.setdefault("AUTO_SEED_ON_BOOT", "false")
# Force AI (text + image) off for the automated suite, overriding any real
# key loaded from backend/.env for local dev. Without this, every test that
# reaches report_agent._attach_images_safely / attach_report_images (e.g.
# test_recommended_reports.py, which runs every recommended report end to
# end) would make real network calls to the OpenAI image API per
# KPI/chart/table — slow, flaky against rate limits, and burns real quota
# on every `pytest` run. The suite must stay free and deterministic; live
# AI/image behavior is verified manually against a real key, not here.
os.environ["OPENAI_API_KEY"] = ""

import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest_asyncio.fixture
async def client():
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


async def post_chat_and_wait(client: AsyncClient, payload: dict, *, timeout: float = 10.0) -> dict:
    """POST /api/chat now returns a job_id immediately and runs the actual
    pipeline as a background task (see app/api/chat.py) so a sufficiently
    complex question can't be cut off by a hosting proxy's per-request
    timeout. Tests want the finished ChatResponse, so this helper submits
    the job and polls GET /api/chat/jobs/{job_id} until it's done/error.
    """
    create_resp = await client.post("/api/chat", json=payload)
    assert create_resp.status_code == 200, create_resp.text
    job_id = create_resp.json()["job_id"]

    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        status_resp = await client.get(f"/api/chat/jobs/{job_id}")
        assert status_resp.status_code == 200, status_resp.text
        body = status_resp.json()
        if body["status"] in ("done", "error"):
            return body
        if asyncio.get_event_loop().time() > deadline:
            raise TimeoutError(f"Chat job {job_id} did not finish within {timeout}s (last status: {body})")
        await asyncio.sleep(0.02)
