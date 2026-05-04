"""Stateful LangGraph ReAct agent — the central reasoning loop."""

import logging
from datetime import datetime, timezone

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from abc import ABC, abstractmethod

from src.core.config import settings
from src.core.prompts import SYSTEM_PROMPT, CONTEXT_BLOCK, HISTORY_BLOCK
from src.memory.manager import MemoryManager

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """Abstract interface for the AIManager agent."""

    @abstractmethod
    def status(self, force: bool = False) -> dict:
        """Return health status of the agent and its subsystems."""
        pass

    @abstractmethod
    def process_message(self, user_id: str, text: str, session_id: str) -> str:
        """Process a message and return the response."""
        pass

    @abstractmethod
    def get_history(self, session_id: str, limit: int = 20) -> list[dict]:
        """Retrieve recent conversation history for a session."""
        pass

    @abstractmethod
    def clear_session(self, session_id: str) -> None:
        """Wipe ephemeral memory for a specific session."""
        pass


class Agent(BaseAgent):
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
        self._health_cache = {}
        self._last_health_check = None
        self._health_ttl_seconds = 300  # 5 minutes

    # ── Public API ────────────────────────────────────────────────────────────

    def status(self, force: bool = False) -> dict:
        """Probe all subsystems and return live health info. Caches results."""
        now = datetime.now(timezone.utc)
        if not force and self._last_health_check:
            delta = (now - self._last_health_check).total_seconds()
            if delta < self._health_ttl_seconds:
                return self._health_cache

        info = {
            "status": "online",
            "llm": "offline",
            "memory": {}
        }
        
        # LLM Probe
        try:
            if force or not self._health_cache:
                self.llm.invoke([HumanMessage(content="ping")])
                info["llm"] = "online"
            else:
                info["llm"] = self._health_cache.get("llm", "online")
        except Exception as e:
            info["llm"] = f"error ({type(e).__name__})"
            info["status"] = "degraded"
            
        # Memory Probe
        mem_health = self.memory.status()
        info["memory"] = mem_health
        
        if mem_health["status"] != "online":
            info["status"] = "degraded"
            
        if info["llm"] != "online" and mem_health["status"] == "offline":
            info["status"] = "offline"
        
        self._health_cache = info
        self._last_health_check = now
        return info

    def process_message(self, user_id: str, text: str, session_id: str) -> str:
        """
        Full agent loop: retrieve → build prompt → generate → store.
        Returns the assistant's response text.
        """
        # 1. Retrieve context
        # Use cached status check to avoid slow pings on every turn
        health = self.status(force=False)
        
        history_items = []
        rag_items = []
        
        try:
            if "online" in health["memory"].get("chroma", ""):
                history_items = self.memory.get_history(session_id, limit=settings.context_window_turns)
                rag_items = self.memory.search(text, k=settings.rag_top_k, session_id=None)
            else:
                logger.warning("Memory (Chroma) is offline, proceeding without context.")
        except Exception as e:
            logger.error("Failed to retrieve context: %s", e)

        # 2. Build messages
        messages = self._build_messages(text, history_items, rag_items)

        # 3. Generate
        logger.info("Generating response for user_id=%s session=%s", user_id, session_id[:8])
        if "online" not in health["llm"]:
            return "I'm sorry, but my reasoning engine (LLM) is currently offline. Please try again in a moment."

        response = self.llm.invoke(messages)
        reply = response.content

        # 4. Store both turns
        ts = datetime.now(timezone.utc).isoformat()
        try:
            if "online" in health["memory"].get("chroma", ""):
                self.memory.store(text, role="user", session_id=session_id, timestamp=ts)
                self.memory.store(reply, role="assistant", session_id=session_id, timestamp=ts)
        except Exception as e:
            logger.error("Failed to store interaction: %s", e)

        return reply

    def get_history(self, session_id: str, limit: int = 20) -> list[dict]:
        """Retrieve recent turns from the memory subsystem."""
        return self.memory.get_history(session_id, limit=limit)

    def clear_session(self, session_id: str) -> None:
        """Signal the memory manager to wipe ephemeral state for this session."""
        self.memory.clear_ephemeral(session_id=session_id)

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
