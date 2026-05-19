"""Tool-call flow: LLM asks for a tool, agent executes it (against real
memory), feeds the result back, LLM then returns plain text."""

from __future__ import annotations

import json

import pytest

from src.agent import AgentRunRequest, get_agent_service
from src.memory import get_memory_manager


@pytest.mark.asyncio
async def test_arun_executes_tool_then_returns_reply(fake_llm, tool_call_response, text_response):
    """LLM emits a ``recall_recent`` tool call; the agent runs it and continues."""
    memory = get_memory_manager()
    memory.append("s1", "user", "what's my favourite colour?")
    memory.append("s1", "assistant", "blue, you said earlier")

    fake_llm.responses = [
        tool_call_response("recall_recent", json.dumps({"session_id": "s1", "limit": 5})),
        text_response("your favourite colour is blue"),
    ]

    result = await get_agent_service().arun(
        AgentRunRequest(
            session_id="s1",
            text="what colour did I say?",
            history=[{"role": "user", "text": "what colour did I say?"}],
        )
    )

    assert result.reply == "your favourite colour is blue"
    assert len(fake_llm.calls) == 2

    # Second LLM call must include the tool result message containing memory.
    second_messages, _ = fake_llm.calls[1]
    tool_msgs = [m for m in second_messages if m.get("role") == "tool"]
    assert len(tool_msgs) == 1
    assert "blue" in tool_msgs[0]["content"]
    assert tool_msgs[0]["tool_call_id"] == "call_1"


@pytest.mark.asyncio
async def test_unknown_tool_returns_error_string_and_loop_continues(
    fake_llm, tool_call_response, text_response
):
    """If the LLM hallucinates a tool, the loop feeds back an error string
    and keeps going rather than crashing."""
    fake_llm.responses = [
        tool_call_response("nonexistent_tool", "{}"),
        text_response("ok, no tool"),
    ]

    result = await get_agent_service().arun(
        AgentRunRequest(session_id="s1", text="hi", history=[{"role": "user", "text": "hi"}])
    )

    assert result.reply == "ok, no tool"
    second_messages, _ = fake_llm.calls[1]
    tool_msg = next(m for m in second_messages if m.get("role") == "tool")
    assert "unknown tool" in tool_msg["content"]
