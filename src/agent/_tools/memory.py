"""Memory-backed tools the agent loop can invoke.

These tools call into ``src.memory`` through its public factory; they
must never reach past the facade. Each tool catches its own failures
and returns them as a string the LLM can read.
"""

from __future__ import annotations

from src.log import get_logger
from src.memory import get_memory_manager

logger = get_logger(__name__)


def _format_turns(turns: list[dict]) -> str:
    if not turns:
        return "(no prior turns)"
    lines = []
    for t in reversed(turns):  # oldest-first for readability
        role = t.get("role", "?")
        text = (t.get("text") or "").strip().replace("\n", " ")
        if len(text) > 240:
            text = text[:239] + "…"
        lines.append(f"{role}: {text}")
    return "\n".join(lines)


class RecallRecentTool:
    name = "recall_recent"
    schema = {
        "type": "function",
        "function": {
            "name": "recall_recent",
            "description": (
                "Return the most recent turns from a session's active branch, "
                "oldest-first, as a plain-text transcript. Use when you need "
                "context beyond what's already in the prompt."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "The session whose history to read.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max turns to return (default 10).",
                        "default": 10,
                    },
                },
                "required": ["session_id"],
            },
        },
    }

    async def run(self, *, session_id: str, limit: int = 10) -> str:
        try:
            turns = get_memory_manager().recent_turns(session_id, limit=int(limit))
        except Exception as e:  # never crash the loop
            logger.error(
                "recall_recent_failed",
                extra={"session_id": session_id, "limit": limit},
                exc_info=True,
            )
            return f"error: {type(e).__name__}: {e}"
        return _format_turns(turns)
