"""Chat agent loop: build prompt → call LLM → run tool calls → iterate.

Stateless across invocations. The caller (``_AgentService.arun``) hands in
a request, an LLM adapter, and the tools list; the loop assembles the
OpenAI-style messages array, drives the LLM until it returns a plain
text reply or the iteration cap is hit, and returns the reply string.

The loop never writes to memory itself. Tools may read memory.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

from src.agent._errors import AgentRunError
from src.log import get_logger

if TYPE_CHECKING:
    from src.agent import AgentRunRequest
    from src.agent._models import LLMAdapter
    from src.agent._tools import Tool

logger = get_logger(__name__)


SYSTEM_PROMPT = (
    "You are AIManager, a helpful chat agent. Reply concisely. "
    "Use the provided tools when they would meaningfully improve the answer; "
    "otherwise reply directly."
)


def _max_iterations() -> int:
    try:
        return max(1, int(os.environ.get("AGENT_MAX_ITERATIONS", "8")))
    except ValueError:
        return 8


def _build_initial_messages(request: "AgentRunRequest") -> list[dict]:
    """Compose the OpenAI-style messages list from history.

    ``request.history`` already contains the latest user message at the
    tip (per the public contract), so we do not append ``request.text``
    again.
    """
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for turn in request.history:
        role = turn.get("role")
        text = turn.get("text", "")
        if role in {"user", "assistant"} and isinstance(text, str):
            messages.append({"role": role, "content": text})
    return messages


async def _run_one_tool_call(call: dict, tool_map: dict[str, "Tool"]) -> str:
    name = call.get("function", {}).get("name", "")
    raw_args = call.get("function", {}).get("arguments") or "{}"
    try:
        args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
    except (json.JSONDecodeError, TypeError):
        logger.warning("tool_args_unparseable", extra={"tool": name})
        args = {}
    tool = tool_map.get(name)
    if tool is None:
        return f"error: unknown tool {name!r}"
    try:
        return await tool.run(**args)
    except Exception as e:  # tools must never crash the loop
        logger.error(
            "tool_run_failed",
            extra={"tool": name, "args": args},
            exc_info=True,
        )
        return f"error: {type(e).__name__}: {e}"


async def run_agent_loop(
    request: "AgentRunRequest",
    *,
    llm: "LLMAdapter",
    tools: list["Tool"],
) -> str:
    """Drive the LLM until it returns plain text. Returns the reply.

    Raises ``AgentRunError`` if the LLM is unreachable or the iteration
    cap is hit without a text reply.
    """
    messages = _build_initial_messages(request)
    tool_schemas = [t.schema for t in tools]
    tool_map = {t.name: t for t in tools}
    cap = _max_iterations()

    for iteration in range(cap):
        response = await llm.chat(messages, tool_schemas)
        msg = response.get("message", {}) or {}
        tool_calls = msg.get("tool_calls") or []
        if tool_calls:
            messages.append(
                {
                    "role": "assistant",
                    "content": msg.get("content"),
                    "tool_calls": tool_calls,
                }
            )
            for call in tool_calls:
                result_text = await _run_one_tool_call(call, tool_map)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id", ""),
                        "content": result_text,
                    }
                )
            continue
        content = msg.get("content") or ""
        logger.info(
            "agent_reply",
            extra={
                "session_id": request.session_id,
                "iterations": iteration + 1,
                "reply_chars": len(content),
            },
        )
        return content

    logger.error(
        "agent_iteration_cap_hit",
        extra={"session_id": request.session_id, "cap": cap},
    )
    raise AgentRunError(f"max iterations ({cap}) reached without final reply")
