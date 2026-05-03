"""Stateful LangGraph ReAct agent — the central reasoning loop."""

import logging
from datetime import datetime, timezone

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from src.core.config import settings
from src.core.prompts import SYSTEM_PROMPT, CONTEXT_BLOCK, HISTORY_BLOCK
from src.memory.manager import MemoryManager

logger = logging.getLogger(__name__)


class Agent:
    """
    Memory-aware conversational agent.

    Retrieves context from ChromaDB, builds a prompt with history + RAG,
    generates a response via Gemini, and stores the interaction.
    """

    def __init__(self, memory: MemoryManager | None = None):
        self.memory = memory or MemoryManager()
        self.llm = ChatGoogleGenerativeAI(
            model=settings.llm_model,
            google_api_key=settings.google_api_key,
            temperature=settings.llm_temperature,
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def status(self) -> dict:
        """Probe all subsystems and return live health info."""
        info = {"llm": "offline", "memory": {}}
        # LLM
        try:
            self.llm.invoke([HumanMessage(content="ping")])
            info["llm"] = f"online ({settings.llm_model})"
        except Exception as e:
            info["llm"] = f"error ({type(e).__name__})"
        # Memory
        info["memory"] = self.memory.status()
        return info

    def process_message(self, user_id: str, text: str, session_id: str) -> str:
        """
        Full agent loop: retrieve → build prompt → generate → store.
        Returns the assistant's response text.
        """
        # 1. Retrieve context
        history_items = self.memory.get_history(session_id, limit=settings.context_window_turns)
        rag_items = self.memory.search(text, k=settings.rag_top_k, session_id=None)

        # 2. Build messages
        messages = self._build_messages(text, history_items, rag_items)

        # 3. Generate
        logger.info("Generating response for user_id=%s session=%s", user_id, session_id[:8])
        response = self.llm.invoke(messages)
        reply = response.content

        # 4. Store both turns
        ts = datetime.now(timezone.utc).isoformat()
        self.memory.store(text, role="user", session_id=session_id, timestamp=ts)
        self.memory.store(reply, role="assistant", session_id=session_id, timestamp=ts)

        return reply

    # ── Internals ─────────────────────────────────────────────────────────────

    def _build_messages(
        self,
        user_text: str,
        history_items: list[dict],
        rag_items: list[dict],
    ) -> list:
        """Assemble the LLM message list: system + context + history + user."""
        messages = []

        # System prompt
        system_parts = [SYSTEM_PROMPT]

        # RAG memories (cross-session semantic matches)
        if rag_items:
            mem_lines = []
            for m in rag_items:
                ts = m["metadata"].get("timestamp", "unknown time")
                role = m["metadata"].get("role", "unknown")
                mem_lines.append(f"[{ts}] ({role}): {m['text']}")
            system_parts.append(CONTEXT_BLOCK.format(memories="\n".join(mem_lines)))

        # Recent conversation history (current session)
        if history_items:
            hist_lines = []
            for h in history_items:
                role = h["metadata"].get("role", "unknown")
                hist_lines.append(f"{role}: {h['text']}")
            system_parts.append(HISTORY_BLOCK.format(history="\n".join(hist_lines)))

        messages.append(SystemMessage(content="\n\n".join(system_parts)))

        # Replay recent history as proper message objects for better LLM understanding
        if history_items:
            for h in history_items[-6:]:  # Last 6 turns as message objects
                role = h["metadata"].get("role", "user")
                if role == "user":
                    messages.append(HumanMessage(content=h["text"]))
                else:
                    messages.append(AIMessage(content=h["text"]))

        # Current user message
        messages.append(HumanMessage(content=user_text))

        return messages
