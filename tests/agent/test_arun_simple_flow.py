"""Plain-text reply path: one LLM call, no tools, returned as the reply."""

from __future__ import annotations

import pytest

from src.agent import AgentRunRequest, AgentService, get_agent_service


@pytest.mark.asyncio
async def test_arun_returns_plain_text_reply(fake_llm, text_response):
    """A single non-tool LLM response is forwarded verbatim as the reply."""
    fake_llm.responses = [text_response("hello back")]

    service = get_agent_service()
    result = await service.arun(
        AgentRunRequest(
            session_id="s1",
            text="hello",
            history=[{"role": "user", "text": "hello"}],
        )
    )

    assert result.reply == "hello back"
    assert result.session_id == "s1"
    assert result.reply_timestamp is not None
    assert len(fake_llm.calls) == 1

    # History flowed into the prompt as a user message after the system prompt.
    sent_messages, _ = fake_llm.calls[0]
    assert sent_messages[0]["role"] == "system"
    assert {"role": "user", "content": "hello"} in sent_messages


@pytest.mark.asyncio
async def test_arun_singleton_returns_same_instance():
    """``get_agent_service`` is a process-wide singleton like the other services."""
    a = get_agent_service()
    b = get_agent_service()
    assert a is b
    assert isinstance(a, AgentService)
