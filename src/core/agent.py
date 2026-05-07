"""Stateful LangGraph ReAct agent — the central reasoning loop."""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Dict

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from abc import ABC, abstractmethod

from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode

from src.core.config import settings
from src.core.prompts import SYSTEM_PROMPT, CONTEXT_BLOCK, HISTORY_BLOCK
from src.memory.manager import MemoryManager
from src.core.router import llm_router, ModelSpec
from src.core.state import AgentState
from src.core.tools import tools
from src.core.context import ContextManager

logger = logging.getLogger(__name__)

# ── Retry config ──────────────────────────────────────────────────────────────
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2  # seconds: 2, 4, 8


class BaseAgent(ABC):
    """Abstract interface for the AIManager agent."""

    @abstractmethod
    def status(self, force: bool = False) -> dict:
        pass

    @abstractmethod
    def process_message(self, user_id: str, text: str, session_id: str) -> str:
        pass

    @abstractmethod
    async def aprocess_message(self, user_id: str, text: str, session_id: str) -> str:
        """Async version of process_message — preferred in async contexts."""
        pass

    @abstractmethod
    def get_history(self, session_id: str, limit: int = 20) -> list[dict]:
        pass

    @abstractmethod
    def clear_session(self, session_id: str) -> None:
        pass


class Agent(BaseAgent):
    """
    Memory-aware conversational agent.

    Retrieves context from ChromaDB, builds a prompt with history + RAG,
    generates a response via Gemini, and stores the interaction.
    """

    def __init__(self, memory: MemoryManager | None = None):
        self.memory = memory or MemoryManager()
        self.context_manager = ContextManager(self.memory)
        self.router = llm_router
        self._llm_cache: Dict[str, ChatGoogleGenerativeAI] = {}
        self._health_cache = {}
        self._last_health_check = None
        self._health_ttl_seconds = 300
        self.graph = self._build_graph()

    # ── Public API ────────────────────────────────────────────────────────────

    def status(self, force: bool = False) -> dict:
        """Probe all subsystems and return live health info. Caches results."""
        now = datetime.now(timezone.utc)
        if not force and self._last_health_check:
            delta = (now - self._last_health_check).total_seconds()
            if delta < self._health_ttl_seconds:
                return self._health_cache

        info = {"status": "online", "llm": "offline", "memory": {}}

        try:
            if force or not self._health_cache:
                spec = self.router.get_best_model("QA")
                llm = self._get_llm_instance(spec)
                llm.invoke([HumanMessage(content="ping")])
                info["llm"] = "online"
            else:
                info["llm"] = self._health_cache.get("llm", "online")
        except Exception as e:
            info["llm"] = f"error ({type(e).__name__})"
            info["status"] = "degraded"

        mem_health = self.memory.status()
        info["memory"] = mem_health
        if mem_health["status"] != "online":
            info["status"] = "degraded"
        if info["llm"] != "online" and mem_health["status"] == "offline":
            info["status"] = "offline"

        self._health_cache = info
        self._last_health_check = now
        return info

    def process_message(
        self,
        user_id: str,
        text: str,
        session_id: str,
        *,
        prompt_text: str | None = None,
        store_text: str | None = None,
    ) -> str:
        """Synchronous entry point — runs the LangGraph loop."""
        effective_prompt = prompt_text or text
        persisted_text = store_text or text
        initial_state = self._build_initial_state(effective_prompt, session_id)
        try:
            final_state = self.graph.invoke(initial_state)
            reply = self._coerce_message_text(final_state["messages"][-1].content)
            self._store_interaction(persisted_text, reply, session_id)
            return reply
        except Exception as e:
            logger.error("Agent loop failed: %s", e)
            # Still store the user's message even on failure
            self._store_interaction(persisted_text, None, session_id)
            return "I'm sorry, I encountered an internal error while processing that."

    async def aprocess_message(
        self,
        user_id: str,
        text: str,
        session_id: str,
        *,
        prompt_text: str | None = None,
        store_text: str | None = None,
    ) -> str:
        """Async entry point — doesn't block the event loop."""
        effective_prompt = prompt_text or text
        persisted_text = store_text or text
        initial_state = self._build_initial_state(effective_prompt, session_id)
        try:
            final_state = await self.graph.ainvoke(initial_state)
            reply = self._coerce_message_text(final_state["messages"][-1].content)
            self._store_interaction(persisted_text, reply, session_id)
            return reply
        except Exception as e:
            logger.error("Agent loop failed: %s", e)
            self._store_interaction(persisted_text, None, session_id)
            return "I'm sorry, I encountered an internal error while processing that."

    def _build_initial_state(self, text: str, session_id: str) -> dict:
        return {
            "messages": [HumanMessage(content=text)],
            "task_type": "QA",
            "is_redacted": False,
            "session_id": session_id,
            "headroom": 1.0,
        }

    def _store_interaction(self, user_text: str, reply: str | None, session_id: str):
        """Store the conversation turn in ChromaDB."""
        ts = datetime.now(timezone.utc).isoformat()
        health = self.status(force=False)
        if "online" in health["memory"].get("chroma", ""):
            self.memory.store(user_text, role="user", session_id=session_id, timestamp=ts)
            if reply:
                self.memory.store(reply, role="assistant", session_id=session_id, timestamp=ts)

    def _coerce_message_text(self, content) -> str:
        """Convert LangChain message content into plain text for callers and memory."""
        return self.memory._coerce_text(content)

    def _get_llm_instance(self, spec: ModelSpec):
        """Get or create a LangChain LLM instance for the given spec."""
        cache_key = f"{spec.model_id}:{spec.api_key}"
        if cache_key in self._llm_cache:
            return self._llm_cache[cache_key]

        if spec.provider == "google":
            llm = ChatGoogleGenerativeAI(
                model=spec.model_id,
                google_api_key=spec.api_key,
                temperature=settings.llm_temperature,
            )
        else:
            from langchain_openai import ChatOpenAI
            llm = ChatOpenAI(
                base_url=settings.lm_studio_base_url,
                api_key="not-needed",
                model_name=settings.lm_studio_model,
                temperature=settings.llm_temperature,
            )

        self._llm_cache[cache_key] = llm
        return llm

    def get_history(self, session_id: str, limit: int = 20) -> list[dict]:
        return self.memory.get_history(session_id, limit=limit)

    def clear_session(self, session_id: str) -> None:
        self.memory.clear_ephemeral(session_id=session_id)

    # ── Graph Construction ───────────────────────────────────────────────────

    def _build_graph(self):
        workflow = StateGraph(AgentState)
        workflow.add_node("reason", self._node_reason)
        workflow.add_node("tools", ToolNode(tools))
        workflow.set_entry_point("reason")
        workflow.add_conditional_edges(
            "reason", self._should_continue,
            {"continue": "tools", "end": END},
        )
        workflow.add_edge("tools", "reason")
        return workflow.compile()

    def _node_reason(self, state: AgentState):
        """Pick a model, invoke with retry + backoff, track token usage."""
        last_msg = state["messages"][-1]
        context = self.context_manager.assemble_context(
            query=last_msg.content,
            session_id=state["session_id"],
            task_type=state["task_type"],
        )
        system_msg = self._build_system_message(
            context["history"], context["rag"], context["entities"],
        )
        full_messages = [system_msg] + list(state["messages"])

        response = None
        used_spec = None

        for attempt in range(MAX_RETRIES):
            spec = self.router.get_best_model(state["task_type"])
            llm = self._get_llm_instance(spec)
            llm_with_tools = llm.bind_tools(tools)

            try:
                response = llm_with_tools.invoke(full_messages)
                used_spec = spec
                break
            except Exception as e:
                error_str = str(e)
                is_429 = "429" in error_str or "RESOURCE_EXHAUSTED" in error_str

                if is_429:
                    logger.warning("Model %s hit 429 quota/rate limit.", spec.model_id)
                    self.router.track_429(spec.model_id, project_scope=spec.project_scope)
                    # Temporarily exhaust the internal limits so get_best_model picks a different one next loop
                    self.router.limiter.track(spec.model_id, spec.project_scope, tokens=spec.tpm_limit * 10)

                if attempt == MAX_RETRIES - 1:
                    raise

                wait = RETRY_BACKOFF_BASE ** (attempt + 1)
                logger.warning(
                    "LLM call failed (attempt %d/%d) with model %s: %s — retrying in %ds",
                    attempt + 1, MAX_RETRIES, spec.model_id, e, wait,
                )
                time.sleep(wait)

        # Track actual token usage
        if response and used_spec:
            tokens = self._extract_token_count(response)
            self.router.track_usage(used_spec.model_id, project_scope=used_spec.project_scope, tokens=tokens)

        return {"messages": [response]}

    @staticmethod
    def _extract_token_count(response) -> int:
        """Pull total token usage from LangChain response metadata."""
        meta = getattr(response, "response_metadata", {})
        usage = meta.get("usage_metadata", {})
        return usage.get("total_token_count", 0) or usage.get("total_tokens", 0)

    def _should_continue(self, state: AgentState):
        last_msg = state["messages"][-1]
        if last_msg.tool_calls:
            return "continue"
        return "end"

    def _build_system_message(self, history, rag, entities):
        from src.core.prompts import ENTITY_BLOCK
        system_parts = [SYSTEM_PROMPT]

        if entities:
            ent_lines = []
            for e in entities:
                n = e["node"]
                conn_list = [
                    f"{c['type']} -> {c['target']} ({c['target_label']})"
                    for c in e["connections"]
                ]
                ent_lines.append(
                    f"ENTITY: {n['name']} ({n['label']})\n"
                    f"Facts: {n.get('description', 'N/A')}\n"
                    f"Relations: {', '.join(conn_list)}"
                )
            system_parts.append(ENTITY_BLOCK.format(entities="\n\n".join(ent_lines)))

        if rag:
            mem_lines = [f"[{m['metadata'].get('timestamp')}] {m['text']}" for m in rag]
            system_parts.append(CONTEXT_BLOCK.format(memories="\n".join(mem_lines)))

        if history:
            hist_lines = [f"{h['metadata'].get('role')}: {h['text']}" for h in history]
            system_parts.append(HISTORY_BLOCK.format(history="\n".join(hist_lines)))

        return SystemMessage(content="\n\n".join(system_parts))
