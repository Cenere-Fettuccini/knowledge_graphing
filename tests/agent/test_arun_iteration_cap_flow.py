"""If the LLM keeps requesting tool calls, the loop stops at the cap."""

from __future__ import annotations

import pytest

from src.agent import AgentRunError, AgentRunRequest, get_agent_service


@pytest.mark.asyncio
async def test_iteration_cap_raises_after_max_iterations(fake_llm, tool_call_response):
    """``AGENT_MAX_ITERATIONS`` (set to 4 in conftest) caps the loop.

    The fake feeds enough tool-call responses that the loop would run
    forever; we expect exactly that many LLM calls before ``AgentRunError``.
    """
    fake_llm.responses = [tool_call_response("recall_recent", '{"session_id":"s1"}') for _ in range(20)]

    with pytest.raises(AgentRunError, match="max iterations"):
        await get_agent_service().arun(
            AgentRunRequest(session_id="s1", text="loop", history=[{"role": "user", "text": "loop"}])
        )

    assert len(fake_llm.calls) == 4
