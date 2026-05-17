"""Thin client for an LM Studio (or any OpenAI-compatible) local LLM server.

Used by analyzers when bulk processing makes a cloud call uneconomical.
Falls back gracefully if the server is unreachable so the analyzer scheduler
can retry on the next tick instead of hard-failing.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from src.core.config import settings

logger = logging.getLogger(__name__)


class LocalLLMUnavailable(RuntimeError):
    """Raised when LM Studio (or the configured local server) cannot be reached."""


class LMStudioClient:
    """Minimal OpenAI-compatible chat client pointed at LM Studio."""

    def __init__(
        self,
        base_url: str | None = None,
        default_model: str | None = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        self._base_url = (base_url or settings.lm_studio_base_url).rstrip("/")
        self._default_model = default_model or settings.lm_studio_model
        self._timeout = timeout_seconds

    @property
    def default_model(self) -> str:
        return self._default_model

    def is_available(self) -> bool:
        """Quick probe — does the server answer ``GET /models``?"""
        try:
            self.list_models()
            return True
        except LocalLLMUnavailable:
            return False

    def list_models(self) -> list[dict[str, Any]]:
        """Return ``[{id, owned_by, ...}, ...]`` for currently-loaded models."""
        try:
            resp = httpx.get(f"{self._base_url}/models", timeout=self._timeout)
        except httpx.HTTPError as exc:
            raise LocalLLMUnavailable(f"LM Studio unreachable at {self._base_url}: {exc}") from exc
        if resp.status_code != 200:
            raise LocalLLMUnavailable(f"LM Studio returned HTTP {resp.status_code}")
        body = resp.json()
        return list(body.get("data") or [])

    def chat_completion(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        json_mode: bool = True,
    ) -> str:
        """POST a chat completion. Returns the raw text content of the first choice."""
        payload: dict[str, Any] = {
            "model": model or self._default_model,
            "messages": messages,
            "temperature": temperature,
        }
        if json_mode:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "response",
                    "strict": False,
                    "schema": {"type": "object"},
                },
            }
        try:
            resp = httpx.post(
                f"{self._base_url}/chat/completions",
                json=payload,
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise LocalLLMUnavailable(f"LM Studio request failed: {exc}") from exc
        if resp.status_code != 200:
            raise LocalLLMUnavailable(
                f"LM Studio returned HTTP {resp.status_code}: {resp.text[:200]}"
            )
        body = resp.json()
        choices = body.get("choices") or []
        if not choices:
            raise LocalLLMUnavailable("LM Studio returned no choices")
        message = choices[0].get("message") or {}
        return message.get("content", "") or ""
