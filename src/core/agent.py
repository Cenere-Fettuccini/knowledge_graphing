"""PydanticAI-backed agent core for AIManager."""

import logging
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Dict

from pydantic_ai import Agent as PydanticAgent
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import UsageLimits

from src.core.config import settings
from src.core.context import ContextManager
from src.core.prompts import CONTEXT_BLOCK, HISTORY_BLOCK, SYSTEM_PROMPT
from src.core.router import ModelSpec, llm_router
from src.core.tools import tools
from src.memory.manager import MemoryManager

logger = logging.getLogger(__name__)

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
    """Memory-aware conversational agent backed by PydanticAI."""

    def __init__(self, memory: MemoryManager | None = None):
        self.memory = memory or MemoryManager()
        self.context_manager = ContextManager(self.memory)
        self.router = llm_router
        self._agent_cache: Dict[str, PydanticAgent] = {}
        self._health_cache = {}
        self._last_health_check = None
        self._health_ttl_seconds = 300

    def status(self, force: bool = False) -> dict:
        """Probe all subsystems and return live health info. Caches results."""
        now = datetime.now(timezone.utc)
        if not force and self._last_health_check:
            delta = (now - self._last_health_check).total_seconds()
            if delta < self._health_ttl_seconds:
                return self._health_cache

        info = {"status": "online", "llm": "offline", "memory": {}}

        try:
            spec = self.router.get_best_model("QA")
            reply, _tokens = self._run_with_spec_sync(
                spec,
                user_prompt="ping",
                instructions="Reply with exactly the word pong.",
            )
            if reply.strip().lower():
                info["llm"] = "online"
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
        """Synchronous entry point for the agent runtime."""
        del user_id
        effective_prompt = prompt_text or text
        persisted_text = store_text or text

        try:
            reply = self._generate_reply_sync(effective_prompt, session_id)
            self._store_interaction(persisted_text, reply, session_id)
            return reply
        except Exception as e:
            logger.error("Agent loop failed: %s", e)
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
        """Async entry point for the agent runtime."""
        del user_id
        effective_prompt = prompt_text or text
        persisted_text = store_text or text

        try:
            reply = await self._generate_reply_async(effective_prompt, session_id)
            self._store_interaction(persisted_text, reply, session_id)
            return reply
        except Exception as e:
            logger.error("Agent loop failed: %s", e)
            self._store_interaction(persisted_text, None, session_id)
            return "I'm sorry, I encountered an internal error while processing that."

    def get_history(self, session_id: str, limit: int = 20) -> list[dict]:
        return self.memory.get_history(session_id, limit=limit)

    def clear_session(self, session_id: str) -> None:
        self.memory.clear_ephemeral(session_id=session_id)

    def _generate_reply_sync(self, text: str, session_id: str) -> str:
        instructions = self._build_system_prompt(text, session_id, task_type="QA")
        return self._execute_with_retries_sync(text, instructions, task_type="QA")

    async def _generate_reply_async(self, text: str, session_id: str) -> str:
        instructions = self._build_system_prompt(text, session_id, task_type="QA")
        return await self._execute_with_retries_async(text, instructions, task_type="QA")

    def _execute_with_retries_sync(self, user_prompt: str, instructions: str, task_type: str) -> str:
        for attempt in range(MAX_RETRIES):
            spec = self.router.get_best_model(task_type)
            try:
                reply, tokens = self._run_with_spec_sync(spec, user_prompt, instructions)
                self.router.track_usage(spec.model_id, project_scope=spec.project_scope, tokens=tokens)
                return reply
            except Exception as e:
                self._handle_model_failure(spec, e, attempt)
        raise RuntimeError("LLM run failed after retries")

    async def _execute_with_retries_async(self, user_prompt: str, instructions: str, task_type: str) -> str:
        for attempt in range(MAX_RETRIES):
            spec = self.router.get_best_model(task_type)
            try:
                reply, tokens = await self._run_with_spec_async(spec, user_prompt, instructions)
                self.router.track_usage(spec.model_id, project_scope=spec.project_scope, tokens=tokens)
                return reply
            except Exception as e:
                self._handle_model_failure(spec, e, attempt)
        raise RuntimeError("LLM run failed after retries")

    def _handle_model_failure(self, spec: ModelSpec, error: Exception, attempt: int) -> None:
        error_str = str(error)
        is_429 = "429" in error_str or "RESOURCE_EXHAUSTED" in error_str

        if is_429:
            logger.warning("Model %s hit 429 quota/rate limit.", spec.model_id)
            self.router.track_429(spec.model_id, project_scope=spec.project_scope)
            self.router.limiter.track(spec.model_id, spec.project_scope, tokens=spec.tpm_limit * 10)

        if attempt == MAX_RETRIES - 1:
            raise error

        wait = RETRY_BACKOFF_BASE ** (attempt + 1)
        logger.warning(
            "LLM call failed (attempt %d/%d) with model %s: %s — retrying in %ds",
            attempt + 1,
            MAX_RETRIES,
            spec.model_id,
            error,
            wait,
        )
        time.sleep(wait)

    def _run_with_spec_sync(self, spec: ModelSpec, user_prompt: str, instructions: str) -> tuple[str, int]:
        agent = self._get_agent_instance(spec)
        result = agent.run_sync(
            user_prompt,
            instructions=instructions,
            usage_limits=UsageLimits(request_limit=8),
        )
        return self.memory._coerce_text(result.output), self._extract_token_count(result)

    async def _run_with_spec_async(self, spec: ModelSpec, user_prompt: str, instructions: str) -> tuple[str, int]:
        agent = self._get_agent_instance(spec)
        result = await agent.run(
            user_prompt,
            instructions=instructions,
            usage_limits=UsageLimits(request_limit=8),
        )
        return self.memory._coerce_text(result.output), self._extract_token_count(result)

    def _get_agent_instance(self, spec: ModelSpec) -> PydanticAgent:
        cache_key = f"{spec.model_id}:{spec.api_key}:{spec.project_scope}"
        cached = self._agent_cache.get(cache_key)
        if cached is not None:
            return cached

        model = self._build_model(spec)
        agent = PydanticAgent(
            model=model,
            tools=tools,
            retries=1,
            defer_model_check=True,
            end_strategy="early",
        )
        self._agent_cache[cache_key] = agent
        return agent

    def _build_model(self, spec: ModelSpec):
        if spec.provider == "google":
            provider = GoogleProvider(api_key=spec.api_key)
            return GoogleModel(
                spec.model_id.removeprefix("models/"),
                provider=provider,
                settings={"temperature": settings.llm_temperature},
            )

        provider = OpenAIProvider(
            base_url=settings.lm_studio_base_url,
            api_key="not-needed",
        )
        return OpenAIChatModel(
            settings.lm_studio_model,
            provider=provider,
            settings={"temperature": settings.llm_temperature},
        )

    def _build_system_prompt(self, text: str, session_id: str, task_type: str) -> str:
        from src.core.prompts import ENTITY_BLOCK

        context = self.context_manager.assemble_context(
            query=text,
            session_id=session_id,
            task_type=task_type,
        )
        system_parts = [SYSTEM_PROMPT]

        entities = context["entities"]
        if entities:
            ent_lines = []
            for entity in entities:
                node = entity["node"]
                conn_list = [
                    f"{connection['type']} -> {connection['target']} ({connection['target_label']})"
                    for connection in entity["connections"]
                ]
                ent_lines.append(
                    f"ENTITY: {node['name']} ({node['label']})\n"
                    f"Facts: {node.get('description', 'N/A')}\n"
                    f"Relations: {', '.join(conn_list)}"
                )
            system_parts.append(ENTITY_BLOCK.format(entities="\n\n".join(ent_lines)))

        rag = context["rag"]
        if rag:
            mem_lines = [f"[{m['metadata'].get('timestamp')}] {m['text']}" for m in rag]
            system_parts.append(CONTEXT_BLOCK.format(memories="\n".join(mem_lines)))

        history = context["history"]
        if history:
            hist_lines = [f"{h['metadata'].get('role')}: {h['text']}" for h in history]
            system_parts.append(HISTORY_BLOCK.format(history="\n".join(hist_lines)))

        return "\n\n".join(system_parts)

    @staticmethod
    def _extract_token_count(result) -> int:
        usage = result.usage()
        return (usage.input_tokens or 0) + (usage.output_tokens or 0)

    def _store_interaction(self, user_text: str, reply: str | None, session_id: str):
        """Store the conversation turn in ChromaDB."""
        ts = datetime.now(timezone.utc).isoformat()
        health = self.status(force=False)
        if "online" in health["memory"].get("chroma", ""):
            self.memory.store(user_text, role="user", session_id=session_id, timestamp=ts)
            if reply:
                self.memory.store(reply, role="assistant", session_id=session_id, timestamp=ts)


def process_message_sync(agent: Agent, user_id: str, text: str, session_id: str) -> str:
    """Compatibility helper for sync call sites that want a named function."""
    return agent.process_message(user_id, text, session_id)


async def process_message_async(agent: Agent, user_id: str, text: str, session_id: str) -> str:
    """Compatibility helper for async call sites that want a named function."""
    return await agent.aprocess_message(user_id, text, session_id)
