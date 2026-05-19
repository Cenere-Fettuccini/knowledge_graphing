"""Chat agent — open-ended conversation with optional memory recall.

The system prompt lives at the top of this file so its definition is
co-located with the agent that uses it.
"""

from __future__ import annotations

CHAT_AGENT_PROMPT = """\
You are a long-term conversational partner for one user. Engage with their
ideas, questions, and reflections as a thoughtful peer. Keep replies concise.\
"""

from src.agent._agents._base import BaseAgent


class ChatAgent(BaseAgent):
    name = "chat"
    description = "Default conversational agent. Open-ended chat with memory recall."
    prompt = CHAT_AGENT_PROMPT
    model = "lmstudio"
    tools = ["recall_recent"]
