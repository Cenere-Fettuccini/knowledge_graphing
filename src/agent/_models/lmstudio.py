"""LM Studio adapter — OpenAI-compatible chat completions over HTTP.

LM Studio exposes an OpenAI-style ``/v1/chat/completions`` endpoint. We
post the conversation + tool schema and translate the single returned
choice into the loop's ``{"message": {...}}`` shape.

All transport/protocol failures are wrapped in ``AgentRunError`` so the
loop sees one exception type regardless of which adapter is active.
"""

from __future__ import annotations

import os

import httpx

from src.agent._errors import AgentRunError
from src.log import get_logger

logger = get_logger(__name__)


def _base_url() -> str:
    return os.environ.get("LM_STUDIO_BASE_URL", "http://localhost:1234/v1").rstrip("/")


def _model() -> str:
    return os.environ.get("LM_STUDIO_MODEL", "")


def _request_timeout() -> float:
    try:
        return float(os.environ.get("LM_STUDIO_TIMEOUT_SECONDS", "60"))
    except ValueError:
        return 60.0


class LMStudioAdapter:
    """OpenAI-compatible client against the configured LM Studio endpoint."""

    async def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        payload: dict = {"model": _model(), "messages": messages}
        if tools:
            payload["tools"] = tools
        url = f"{_base_url()}/chat/completions"
        try:
            async with httpx.AsyncClient(timeout=_request_timeout()) as client:
                r = await client.post(url, json=payload)
                r.raise_for_status()
                data = r.json()
        except (httpx.HTTPError, ValueError) as e:
            logger.error(
                "lmstudio_request_failed",
                extra={"url": url, "error": str(e)},
                exc_info=True,
            )
            raise AgentRunError(f"LM Studio unavailable: {e}") from e

        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as e:
            logger.error(
                "lmstudio_response_malformed",
                extra={"url": url, "keys": list(data) if isinstance(data, dict) else None},
            )
            raise AgentRunError(f"LM Studio returned malformed response: {e}") from e

        return {"message": message}
