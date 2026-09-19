"""Reverse-proxy every non-/api request to the Next.js standalone server.

Used only in the single-container Docker deployment (see DEPLOY.md). Activated when
FRONTEND_PROXY_URL is set (the Dockerfile sets it to http://127.0.0.1:3000).
Local development runs `next dev` and `uvicorn --reload` as two separate processes
with FRONTEND_PROXY_URL unset, so this code path is inert in dev.
"""
from __future__ import annotations

import httpx
from fastapi import FastAPI, Request, Response


def mount_frontend_proxy(app: FastAPI, target_base_url: str) -> None:
    client = httpx.AsyncClient(base_url=target_base_url, timeout=30.0)

    @app.middleware("http")
    async def _proxy_to_frontend(request: Request, call_next):
        if request.url.path.startswith("/api"):
            return await call_next(request)

        url = httpx.URL(path=request.url.path, query=request.url.query.encode("utf-8"))
        headers = dict(request.headers)
        headers.pop("host", None)
        body = await request.body()

        try:
            upstream = await client.request(
                request.method, url, headers=headers, content=body
            )
        except httpx.ConnectError:
            return Response("Frontend service unavailable", status_code=502)

        response_headers = dict(upstream.headers)
        response_headers.pop("content-encoding", None)
        response_headers.pop("content-length", None)
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            headers=response_headers,
        )
