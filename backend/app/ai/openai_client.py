"""Thin wrapper around the OpenAI SDK for text/structured-output calls.

Model name is fully env-driven (OPENAI_MODEL). If OPENAI_API_KEY is unset, `is_enabled()`
returns False and every agent falls back to its deterministic/heuristic path — the app
must run fully without any OpenAI credentials (see CLAUDE.md ai_disabled behavior).
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger("app.ai")
settings = get_settings()

_client = None


def is_enabled() -> bool:
    return bool(settings.OPENAI_API_KEY)


def _get_client():
    global _client
    if _client is None:
        from openai import AsyncOpenAI

        _client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


async def chat_completion(
    *,
    system: str,
    user: str,
    temperature: float = 0.2,
    max_tokens: int = 2000,
) -> str:
    """Plain free-text completion (used for the final NL explanation)."""
    if not is_enabled():
        raise RuntimeError("AI is disabled: OPENAI_API_KEY is not set.")
    client = _get_client()
    response = await client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        temperature=temperature,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return response.choices[0].message.content or ""


async def structured_completion(
    *,
    system: str,
    user: str,
    schema_name: str,
    json_schema: dict[str, Any],
    temperature: float = 0.1,
    max_tokens: int = 4000,
) -> dict[str, Any]:
    """Structured-output completion constrained to the given JSON schema.

    Used by the Query Planner, SQL Generation, Report, Report Edit, and Explanation
    (intent classification) agents so the LLM always returns strict JSON rather than
    free-form text that has to be parsed heuristically.
    """
    if not is_enabled():
        raise RuntimeError("AI is disabled: OPENAI_API_KEY is not set.")
    client = _get_client()
    response = await client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        temperature=temperature,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "schema": json_schema,
                "strict": True,
            },
        },
    )
    content = response.choices[0].message.content or "{}"
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        logger.error("Structured completion returned invalid JSON: %s", content[:500])
        raise
