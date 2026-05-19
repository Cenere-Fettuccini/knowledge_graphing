"""Typed exceptions raised out of the agent's public surface."""

from __future__ import annotations


class AgentRunError(RuntimeError):
    """Raised by ``AgentService.arun`` when the run cannot produce a reply.

    Covers LLM-unreachable, malformed LLM responses, and iteration-cap
    exhaustion. Callers (typically ``backend.conversation``) catch this
    to surface a degraded turn while keeping the user's message
    persisted.
    """
