"""LLM-unreachable and malformed-response paths surface ``AgentRunError``.

The agent must never hang or crash with a provider-specific exception —
adapters wrap transport failures so the loop sees one error type.
"""

from __future__ import annotations

import httpx
import pytest

from src.agent import AgentRunError, AgentRunRequest, get_agent_service


@pytest.mark.asyncio
async def test_llm_connection_failure_propagates_typed_error(fake_llm):
    """``AgentRunError`` from the adapter propagates out of ``arun`` unchanged.

    The adapter is responsible for wrapping transport errors (see the
    LM Studio adapter tests below); the loop and service must forward
    that typed exception to the caller without converting or swallowing.
    """
    fake_llm.responses = [AgentRunError("LM Studio unavailable: refused")]

    with pytest.raises(AgentRunError, match="unavailable"):
        await get_agent_service().arun(
            AgentRunRequest(session_id="s1", text="hi", history=[{"role": "user", "text": "hi"}])
        )


@pytest.mark.asyncio
async def test_lmstudio_adapter_wraps_httpx_errors(monkeypatch):
    """The LM Studio adapter itself converts ``httpx`` failures to ``AgentRunError``."""
    from src.agent._models.lmstudio import LMStudioAdapter

    class _Boom:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            raise httpx.ConnectError("refused")

    monkeypatch.setattr("src.agent._models.lmstudio.httpx.AsyncClient", lambda *a, **k: _Boom())

    adapter = LMStudioAdapter()
    with pytest.raises(AgentRunError, match="LM Studio unavailable"):
        await adapter.chat([{"role": "user", "content": "hi"}], [])


@pytest.mark.asyncio
async def test_lmstudio_adapter_wraps_malformed_response(monkeypatch):
    """Missing ``choices`` in the LM Studio response surfaces a typed error."""
    from src.agent._models.lmstudio import LMStudioAdapter

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"unexpected": "shape"}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            return _Resp()

    monkeypatch.setattr("src.agent._models.lmstudio.httpx.AsyncClient", lambda *a, **k: _Client())

    adapter = LMStudioAdapter()
    with pytest.raises(AgentRunError, match="malformed"):
        await adapter.chat([{"role": "user", "content": "hi"}], [])
