"""Decorative-only image generation client (Image Agent, item 11 in CLAUDE.md agents list).

STRUCTURAL ENFORCEMENT OF THE "NEVER DATA-BEARING" RULE
=========================================================
This is not just a documented convention — it is enforced by the function signature
itself. `generate_decorative_image()` below accepts ONLY:
    - title: str        (a short report/dashboard title, e.g. "September Sales Overview")
    - theme: str         (a style keyword, e.g. "sales", "finance", "executive", "empty_state")
There is NO parameter through which row data, KPI values, chart series, table
contents, or any numeric business value can be passed in. The prompt builder
(`_build_prompt`) only ever interpolates `title` and `theme` into a fixed template
that explicitly instructs the image model to draw abstract shapes/patterns/icons and
NEVER any numbers, charts, graphs, tables, or text resembling data. There is no code
path anywhere in this module that imports app.query_engine, app.analytics, or any
ReportSpec/row type — attempting to pass a dict/list/DataFrame as `title` or `theme`
would fail type-checking intent immediately (both are typed `str`).

If a future contributor is tempted to "let the banner also show the top KPI number",
that MUST happen client-side by overlaying real DOM text on top of this decorative
image — never by feeding data into this function. See CLAUDE.md stack decisions
("AI provider (image)") for the product rule this encodes.
"""
from __future__ import annotations

import logging

from app.core.config import get_settings

logger = logging.getLogger("app.ai.image")
settings = get_settings()

_ALLOWED_THEMES = {
    "sales", "purchase", "hr", "inventory", "production",
    "order_to_delivery", "tasks", "finance", "executive",
    "empty_state", "generic",
}

_client = None


def is_enabled() -> bool:
    return bool(settings.OPENAI_API_KEY)


def _get_client():
    global _client
    if _client is None:
        from openai import AsyncOpenAI

        _client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


def _build_prompt(title: str, theme: str) -> str:
    """The ONLY inputs are a title string and a theme keyword — see module docstring."""
    safe_title = (title or "Business Report").strip()[:120]
    safe_theme = theme if theme in _ALLOWED_THEMES else "generic"
    return (
        f"A minimalist, abstract, premium corporate banner illustration for a business "
        f"intelligence report titled '{safe_title}' with a {safe_theme} theme. "
        "Soft gradients, geometric shapes, subtle icons related to the theme. "
        "STRICT CONSTRAINTS: do NOT draw any numbers, digits, percentages, currency "
        "symbols, charts, graphs, bar/line/pie shapes that resemble data visualizations, "
        "tables, grids of data, or any readable text. Purely decorative, abstract, "
        "non-data-bearing artwork suitable as a header background image."
    )


async def generate_decorative_image(title: str, theme: str = "generic") -> str | None:
    """Generate a decorative-only banner/illustration image and return its URL.

    Returns None if AI is disabled or generation fails (callers must treat the banner
    as optional — the report itself never depends on this succeeding).

    Signature is intentionally narrow: (title: str, theme: str) -> str | None.
    Do not widen this signature to accept row data, query results, or numeric values.
    """
    if not is_enabled():
        return None
    if not isinstance(title, str) or not isinstance(theme, str):
        # Defensive: refuse anything that isn't a plain string, in case a caller
        # tries to pass a dict/list of data through by mistake.
        logger.warning("generate_decorative_image called with non-string args; refusing.")
        return None

    prompt = _build_prompt(title, theme)
    try:
        client = _get_client()
        response = await client.images.generate(
            model=settings.OPENAI_IMAGE_MODEL,
            prompt=prompt,
            size="1536x1024",
            n=1,
        )
        if not response.data:
            return None
        image = response.data[0]
        # gpt-image-* models always return base64 image bytes via `b64_json`
        # and leave `url` unset — unlike the older DALL-E models, which
        # return a hosted `url` and no `b64_json`. Verified live: a real
        # call against gpt-image-1 came back with url=None every time,
        # silently discarding a genuinely generated image. Support both
        # response shapes so the banner actually displays regardless of
        # which image model is configured.
        url = getattr(image, "url", None)
        if url:
            return url
        b64 = getattr(image, "b64_json", None)
        if b64:
            return f"data:image/png;base64,{b64}"
        return None
    except Exception:  # noqa: BLE001 - banner is optional, never fail the report over it
        logger.exception("Decorative image generation failed (non-fatal).")
        return None
