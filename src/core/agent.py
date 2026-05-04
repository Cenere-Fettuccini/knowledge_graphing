"""Stateful LangGraph ReAct agent — the central reasoning loop."""

import logging
from datetime import datetime, timezone

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from abc import ABC, abstractmethod

from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langchain_core.messages import ToolMessage

from src.core.config import settings
from src.core.prompts import SYSTEM_PROMPT, CONTEXT_BLOCK, HISTORY_BLOCK
from src.memory.manager import MemoryManager
from src.core.analyzer import TaskAnalyzer
from src.core.privacy import PrivacyFilter
from src.core.router import llm_router, ModelSpec
from src.core.state import AgentState
from src.core.tools import tools

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
        
        # Subsystems for intelligent routing
        self.analyzer = TaskAnalyzer()
        self.privacy = PrivacyFilter()
        self.router = llm_router
        
        # Cache for instantiated LLM objects to avoid re-creating them every call
        self._llm_cache: Dict[str, ChatGoogleGenerativeAI] = {}
        
        self._health_cache = {}
        self._last_health_check = None
        self._health_ttl_seconds = 300  # 5 minutes
        
        # Build the reasoning graph
        self.graph = self._build_graph()

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
        Runs the autonomous LangGraph loop: redact → analyze → reason [→ tools → reason ...]
        """
        # Initial state
        initial_state = {
            "messages": [HumanMessage(content=text)],
            "task_type": "QA",
            "is_redacted": False,
            "session_id": session_id,
            "headroom": 1.0
        }
        
        try:
            # Execute graph
            final_state = self.graph.invoke(initial_state)
            
            # Extract final response
            last_msg = final_state["messages"][-1]
            reply = last_msg.content
            
            # 7. Store interaction
            ts = datetime.now(timezone.utc).isoformat()
            health = self.status(force=False)
            if "online" in health["memory"].get("chroma", ""):
                self.memory.store(text, role="user", session_id=session_id, timestamp=ts)
                self.memory.store(reply, role="assistant", session_id=session_id, timestamp=ts)
                
            return reply
            
        except Exception as e:
            logger.error("Agent loop failed: %s", e)
            return "I'm sorry, I encountered an internal error while processing that."

    def _get_llm_instance(self, spec: ModelSpec):
        """Get or create a LangChain LLM instance for the given spec."""
        # Use composite key for caching (model + specific api_key)
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
            # Assume local SLM via LM Studio / OpenAI-compatible
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
        """Retrieve recent turns from the memory subsystem."""
        return self.memory.get_history(session_id, limit=limit)

    def clear_session(self, session_id: str) -> None:
        """Signal the memory manager to wipe ephemeral state for this session."""
        self.memory.clear_ephemeral(session_id=session_id)

    # ── Internals ─────────────────────────────────────────────────────────────

    # ── Graph Construction ───────────────────────────────────────────────────

    def _build_graph(self):
        """Construct the LangGraph state machine."""
        workflow = StateGraph(AgentState)
        
        # Define nodes
        workflow.add_node("redact", self._node_redact)
        workflow.add_node("analyze", self._node_analyze)
        workflow.add_node("reason", self._node_reason)
        workflow.add_node("tools", ToolNode(tools))
        
        # Define edges
        workflow.set_entry_point("redact")
        workflow.add_edge("redact", "analyze")
        workflow.add_edge("analyze", "reason")
        
        # Conditional edge for ReAct loop
        workflow.add_conditional_edges(
            "reason",
            self._should_continue,
            {
                "continue": "tools",
                "end": END
            }
        )
        
        workflow.add_edge("tools", "reason")
        
        return workflow.compile()

    def _node_redact(self, state: AgentState):
        """Filter PII before anything else."""
        last_msg = state["messages"][-1]
        safe_text = self.privacy.redact(last_msg.content)
        return {
            "messages": [HumanMessage(content=safe_text)],
            "is_redacted": True
        }

    def _node_analyze(self, state: AgentState):
        """Classify task type to guide routing."""
        last_msg = state["messages"][-1]
        task_type = self.analyzer.classify(last_msg.content)
        return {"task_type": task_type}

    def _node_reason(self, state: AgentState):
        """Pick a model and generate reasoning/response."""
        # Get best model based on current task type and headroom
        spec = self.router.get_best_model(state["task_type"])
        llm = self._get_llm_instance(spec)
        
        # Bind tools to the model
        llm_with_tools = llm.bind_tools(tools)
        
        # Build prompt context (RAG + History)
        last_msg = state["messages"][-1]
        history = self.memory.get_history(state["session_id"], limit=settings.context_window_turns)
        rag = self.memory.search(last_msg.content, k=settings.rag_top_k)
        
        system_msg = self._build_system_message(history, rag)
        full_messages = [system_msg] + list(state["messages"])
        
        response = llm_with_tools.invoke(full_messages)
        
        # Track usage
        self.router.track_usage(spec.model_id, api_key=spec.api_key)
        
        return {"messages": [response]}

    def _should_continue(self, state: AgentState):
        """Decide if we need to call tools or end the turn."""
        last_msg = state["messages"][-1]
        if last_msg.tool_calls:
            return "continue"
        return "end"

    def _build_system_message(self, history, rag):
        """Assemble the system prompt for the current turn."""
        system_parts = [SYSTEM_PROMPT]
        
        if rag:
            mem_lines = [f"[{m['metadata'].get('timestamp')}] {m['text']}" for m in rag]
            system_parts.append(CONTEXT_BLOCK.format(memories="\n".join(mem_lines)))
            
        if history:
            hist_lines = [f"{h['metadata'].get('role')}: {h['text']}" for h in history]
            system_parts.append(HISTORY_BLOCK.format(history="\n".join(hist_lines)))
            
        return SystemMessage(content="\n\n".join(system_parts))
