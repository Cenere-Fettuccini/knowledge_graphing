"""src/core/agent.py

Stateful LangGraph ReAct agent.

Upgrade from Step 1 (stateless Gemini calls):
  - Retrieves context from ChromaDB before every LLM call:
      • Sliding-window conversation history (last N turns)
      • Top-K semantically relevant past memories (RAG)
  - Streams token-level responses back to an async callback so the Telegram
    bot can forward them as they arrive.
  - Stores every user message + agent reply in ChromaDB asynchronously
    (fire-and-forget, never blocks the response).
  - Session IDs are per-user and persist in memory for the lifetime of the
    process. A new session starts each time the bot restarts.

LangGraph note
--------------
Phase 1 uses a simple linear graph (retrieve → generate) because there are no
tools yet. The graph structure is already in place so adding tool nodes in
Step 6/8 is a matter of inserting new nodes and edges without restructuring.

Graph:
    [retrieve_context] → [generate] → END
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any, TypedDict

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, StateGraph

from src.core.config import settings
from src.core.prompts import CONTEXT_BLOCK, HISTORY_BLOCK, SYSTEM_PROMPT
from src.memory.memory_manager import MemoryManager

logger = logging.getLogger(__name__)


# ── Graph state ───────────────────────────────────────────────────────────────

class AgentState(TypedDict):
    """Mutable state threaded through every graph node."""
    user_id:       str
    session_id:    str
    turn_index:    int
    user_text:     str
    messages:      list[BaseMessage]   # full prompt sent to the LLM
    response_text: str                 # populated by the generate node


# ── Agent ─────────────────────────────────────────────────────────────────────

class Agent:
    """
    Stateful LangGraph agent with ChromaDB memory.

    One instance is shared for the lifetime of the process.
    Per-user state (session_id, turn_index) is tracked in _sessions.
    """

    def __init__(self) -> None:
        self._llm = ChatGoogleGenerativeAI(
            model=settings.llm_model,
            temperature=settings.llm_temperature,
            google_api_key=settings.google_api_key,
            streaming=True,
        )
        self._memory = MemoryManager()
        self._sessions: dict[str, dict[str, Any]] = {}  # user_id → {session_id, turn_index}
        self._graph = self._build_graph()
        logger.info("Agent initialised (model=%s, streaming=True)", settings.llm_model)

    # ── Session helpers ───────────────────────────────────────────────────────

    def _get_session(self, user_id: str) -> dict[str, Any]:
        if user_id not in self._sessions:
            active_session_id = self._memory.get_active_session(user_id)
            if active_session_id:
                self._sessions[user_id] = {
                    "session_id": active_session_id,
                    "turn_index": 0,
                }
            else:
                new_session_id = MemoryManager.new_session_id()
                self._memory.set_active_session(user_id, new_session_id)
                self._sessions[user_id] = {
                    "session_id": new_session_id,
                    "turn_index": 0,
                }
        return self._sessions[user_id]

    def _advance_turn(self, user_id: str, by: int = 2) -> None:
        """Advance turn index by 2 after each full exchange (user + assistant)."""
        self._sessions[user_id]["turn_index"] += by

    def reset_session(self, user_id: str) -> str:
        """Start a new session for the user."""
        new_session_id = MemoryManager.new_session_id()
        self._memory.set_active_session(user_id, new_session_id)
        self._sessions[user_id] = {
            "session_id": new_session_id,
            "turn_index": 0,
        }
        return new_session_id

    def pin_session(self, user_id: str, name: str) -> None:
        """Pin the current active session with a name."""
        session = self._get_session(user_id)
        self._memory.pin_session(user_id, session["session_id"], name)

    def get_pinned_sessions(self, user_id: str) -> list[dict[str, str]]:
        """Return a list of pinned sessions."""
        return self._memory.get_pinned_sessions(user_id)

    def swap_session(self, user_id: str, session_id: str) -> None:
        """Swap to a different session_id."""
        self._memory.set_active_session(user_id, session_id)
        self._sessions[user_id] = {
            "session_id": session_id,
            "turn_index": 0, # Start counting from 0 again for this session
        }

    # ── Graph nodes ───────────────────────────────────────────────────────────

    async def _retrieve_context(self, state: AgentState) -> AgentState:
        """
        Node 1: pull conversation history + relevant memories from ChromaDB,
        then construct the full message list for the LLM.
        """
        user_id   = state["user_id"]
        user_text = state["user_text"]

        # Parallel retrieval — both calls hit ChromaDB concurrently
        history_task  = asyncio.create_task(self._memory.get_recent_turns(user_id))
        relevant_task = asyncio.create_task(self._memory.search_relevant(user_id, user_text))
        history, relevant = await asyncio.gather(history_task, relevant_task)

        # Build the context strings
        history_str = _format_history(history)
        memory_str  = _format_relevant(relevant)

        # Compose the full prompt
        system_content = SYSTEM_PROMPT
        if memory_str:
            system_content += "\n\n" + CONTEXT_BLOCK.format(memories=memory_str)
        if history_str:
            system_content += "\n\n" + HISTORY_BLOCK.format(history=history_str)

        messages: list[BaseMessage] = [
            SystemMessage(content=system_content),
            HumanMessage(content=user_text),
        ]

        return {**state, "messages": messages}

    async def _generate(self, state: AgentState) -> AgentState:
        """
        Node 2: invoke the LLM and collect the full response text.

        Streaming is handled separately in process_message_stream(); this node
        is used by the non-streaming process_message() path.
        """
        response = await self._llm.ainvoke(state["messages"])
        return {**state, "response_text": response.content}

    # ── Graph construction ────────────────────────────────────────────────────

    def _build_graph(self):
        builder = StateGraph(AgentState)
        builder.add_node("retrieve_context", self._retrieve_context)
        builder.add_node("generate", self._generate)

        builder.set_entry_point("retrieve_context")
        builder.add_edge("retrieve_context", "generate")
        builder.add_edge("generate", END)

        return builder.compile()

    # ── Background storage ────────────────────────────────────────────────────

    def _store_exchange(
        self,
        user_id: str,
        session_id: str,
        turn_index: int,
        user_text: str,
        reply: str,
    ) -> None:
        """
        Fire-and-forget: store both sides of the exchange in ChromaDB.
        Errors are logged but never surface to the user.
        """
        async def _store():
            try:
                await self._memory.store_turn(
                    user_id, session_id, turn_index,     "user",      user_text
                )
                await self._memory.store_turn(
                    user_id, session_id, turn_index + 1, "assistant", reply
                )
            except Exception:
                logger.exception("Background storage failed for user_id=%s", user_id)

        asyncio.create_task(_store())

    # ── Public API ────────────────────────────────────────────────────────────

    async def process_message(self, user_id: str, text: str) -> str:
        """
        Process a message and return the complete response string.
        Used as the fallback when streaming is not available.
        """
        session = self._get_session(user_id)

        initial_state: AgentState = {
            "user_id":       user_id,
            "session_id":    session["session_id"],
            "turn_index":    session["turn_index"],
            "user_text":     text,
            "messages":      [],
            "response_text": "",
        }

        final_state = await self._graph.ainvoke(initial_state)
        reply = final_state["response_text"]

        self._store_exchange(
            user_id, session["session_id"], session["turn_index"], text, reply
        )
        self._advance_turn(user_id)

        return reply

    async def process_message_stream(
        self, user_id: str, text: str
    ) -> AsyncIterator[str]:
        """
        Process a message and yield response tokens as they arrive.

        Usage in the Telegram bot:
            async for token in agent.process_message_stream(user_id, text):
                # forward token to Telegram

        Internally:
          1. Run the retrieve_context node fully (no streaming needed there).
          2. Stream the generate node token-by-token via astream_events.
          3. After the stream is exhausted, fire-and-forget storage.
        """
        session = self._get_session(user_id)

        initial_state: AgentState = {
            "user_id":       user_id,
            "session_id":    session["session_id"],
            "turn_index":    session["turn_index"],
            "user_text":     text,
            "messages":      [],
            "response_text": "",
        }

        # Step 1: run context retrieval
        state_after_retrieval = await self._retrieve_context(initial_state)

        # Step 2: stream the LLM response
        full_reply_parts: list[str] = []

        async for event in self._llm.astream_events(
            state_after_retrieval["messages"], version="v2"
        ):
            kind = event.get("event")
            if kind == "on_chat_model_stream":
                chunk = event["data"].get("chunk")
                if chunk and hasattr(chunk, "content") and chunk.content:
                    full_reply_parts.append(chunk.content)
                    yield chunk.content

        full_reply = "".join(full_reply_parts)

        # Step 3: background storage
        self._store_exchange(
            user_id,
            session["session_id"],
            session["turn_index"],
            text,
            full_reply,
        )
        self._advance_turn(user_id)

    async def get_history(self, user_id: str, n: int = 10) -> str:
        """Retrieve formatted recent conversation history."""
        history = await self._memory.get_recent_turns(user_id, n=n)
        return _format_history(history)


# ── Formatting helpers ────────────────────────────────────────────────────────

def _format_history(turns: list[dict[str, Any]]) -> str:
    """Convert recent turns into a readable transcript string."""
    if not turns:
        return ""
    lines = []
    for t in turns:
        role   = t["metadata"].get("role", "unknown")
        prefix = "You" if role == "user" else "AIManager"
        lines.append(f"{prefix}: {t['text']}")
    return "\n".join(lines)


def _format_relevant(hits: list[dict[str, Any]]) -> str:
    """Format semantic search hits with timestamps for the system prompt."""
    if not hits:
        return ""
    lines = []
    for h in hits:
        ts     = h["metadata"].get("timestamp", "")[:10]  # date only
        sim    = h.get("similarity", 0)
        role   = h["metadata"].get("role", "unknown")
        prefix = "You" if role == "user" else "AIManager"
        lines.append(f"[{ts}] {prefix}: {h['text']}  (relevance: {sim:.2f})")
    return "\n".join(lines)
