"""Idiomatic PydanticAI-backed agent core for AIManager."""

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict

import httpx
from pydantic_ai import Agent as PydanticAgent
from pydantic_ai import RunContext
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


@dataclass(slots=True)
class AgentRunDeps:
    """Per-run dependencies exposed to native PydanticAI hooks."""

    query: str
    session_id: str
    task_type: str
    context_manager: ContextManager


class BaseAgent(ABC):
    """Abstract interface for the AIManager agent."""

    @abstractmethod
    def status(self, force: bool = False) -> dict:
        pass

    @abstractmethod
    async def astatus(self, force: bool = False) -> dict:
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
    """Memory-aware conversational agent implemented with native PydanticAI patterns."""

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
        return self._status_impl(force=force, use_async_probe=False)

    async def astatus(self, force: bool = False) -> dict:
        """Async-safe health probe for event-loop contexts."""
        return await self._status_impl(force=force, use_async_probe=True)

    def _should_use_cached_health(self, force: bool) -> bool:
        now = datetime.now(timezone.utc)
        if not force and self._last_health_check:
            delta = (now - self._last_health_check).total_seconds()
            if delta < self._health_ttl_seconds:
                return True
        return False

    def _build_base_health_info(self) -> dict:
        return {"status": "online", "llm": "offline", "memory": {}}

    def _finalize_health_info(self, info: dict) -> dict:
        mem_health = self.memory.status()
        info["memory"] = mem_health
        if mem_health["status"] != "online":
            info["status"] = "degraded"
        if info["llm"] != "online" and mem_health["status"] == "offline":
            info["status"] = "offline"

        self._health_cache = info
        self._last_health_check = datetime.now(timezone.utc)
        return info

    def _status_impl(self, force: bool, use_async_probe: bool):
        """Shared status implementation for sync and async callers."""
        if self._should_use_cached_health(force):
            return self._health_cache

        info = self._build_base_health_info()

        if use_async_probe:
            return self._status_impl_async(info)
        return self._status_impl_sync(info)

    def _status_impl_sync(self, info: dict) -> dict:
        try:
            spec = self.router.get_best_model("QA")
            if self._probe_provider_sync(spec):
                info["llm"] = "online"
        except Exception as e:
            info["llm"] = f"error ({type(e).__name__})"
            info["status"] = "degraded"

        return self._finalize_health_info(info)

    async def _status_impl_async(self, info: dict) -> dict:
        try:
            spec = self.router.get_best_model("QA")
            if await self._probe_provider_async(spec):
                info["llm"] = "online"
        except Exception as e:
            info["llm"] = f"error ({type(e).__name__})"
            info["status"] = "degraded"

        return self._finalize_health_info(info)

    def _probe_provider_sync(self, spec: ModelSpec) -> bool:
        if spec.provider == "google":
            self._probe_google_model_sync(spec)
            return True
        if spec.provider == "local":
            self._probe_openai_compatible_sync()
            return True
        raise RuntimeError(f"unsupported provider for health probe: {spec.provider}")

    async def _probe_provider_async(self, spec: ModelSpec) -> bool:
        if spec.provider == "google":
            await self._probe_google_model_async(spec)
            return True
        if spec.provider == "local":
            await self._probe_openai_compatible_async()
            return True
        raise RuntimeError(f"unsupported provider for health probe: {spec.provider}")

    def _probe_google_model_sync(self, spec: ModelSpec) -> None:
        if not spec.api_key:
            raise RuntimeError("missing Google API key")

        response = httpx.get(
            f"https://generativelanguage.googleapis.com/v1beta/{spec.model_id}",
            params={"key": spec.api_key},
            timeout=10.0,
        )
        response.raise_for_status()

    async def _probe_google_model_async(self, spec: ModelSpec) -> None:
        if not spec.api_key:
            raise RuntimeError("missing Google API key")

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"https://generativelanguage.googleapis.com/v1beta/{spec.model_id}",
                params={"key": spec.api_key},
            )
            response.raise_for_status()

    def _probe_openai_compatible_sync(self) -> None:
        response = httpx.get(
            f"{settings.lm_studio_base_url.rstrip('/')}/models",
            headers={"Authorization": "Bearer not-needed"},
            timeout=10.0,
        )
        response.raise_for_status()

    async def _probe_openai_compatible_async(self) -> None:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{settings.lm_studio_base_url.rstrip('/')}/models",
                headers={"Authorization": "Bearer not-needed"},
            )
            response.raise_for_status()

    def process_message(
        self,
        user_id: str,
        text: str,
        session_id: str,
        *,
        prompt_text: str | None = None,
        store_text: str | None = None,
        store_metadata: dict | None = None,
    ) -> str:
        """Synchronous entry point for the agent runtime."""
        effective_prompt = prompt_text or text
        persisted_text = store_text or text
        deps = self._build_run_deps(effective_prompt, session_id, task_type="QA")
        merged_store_metadata = {"user_id": user_id, **(store_metadata or {})}

        try:
            reply = self._execute_with_retries_sync(effective_prompt, deps)
            self._store_interaction(persisted_text, reply, session_id, metadata=merged_store_metadata)
            return reply
        except Exception as e:
            logger.error("Agent loop failed: %s", e)
            self._store_interaction(persisted_text, None, session_id, metadata=merged_store_metadata)
            return "I'm sorry, I encountered an internal error while processing that."

    async def aprocess_message(
        self,
        user_id: str,
        text: str,
        session_id: str,
        *,
        prompt_text: str | None = None,
        store_text: str | None = None,
        store_metadata: dict | None = None,
    ) -> str:
        """Async entry point for the agent runtime."""
        effective_prompt = prompt_text or text
        persisted_text = store_text or text
        deps = self._build_run_deps(effective_prompt, session_id, task_type="QA")
        merged_store_metadata = {"user_id": user_id, **(store_metadata or {})}

        try:
            reply = await self._execute_with_retries_async(effective_prompt, deps)
            await self._astore_interaction(persisted_text, reply, session_id, metadata=merged_store_metadata)
            return reply
        except Exception as e:
            logger.error("Agent loop failed: %s", e)
            await self._astore_interaction(persisted_text, None, session_id, metadata=merged_store_metadata)
            return "I'm sorry, I encountered an internal error while processing that."

    def get_history(self, session_id: str, limit: int = 20) -> list[dict]:
        return self.memory.get_history(session_id, limit=limit)

    def clear_session(self, session_id: str) -> None:
        self.memory.clear_ephemeral(session_id=session_id)

    def _build_run_deps(self, query: str, session_id: str, task_type: str) -> AgentRunDeps:
        return AgentRunDeps(
            query=query,
            session_id=session_id,
            task_type=task_type,
            context_manager=self.context_manager,
        )

    def _execute_with_retries_sync(self, user_prompt: str, deps: AgentRunDeps) -> str:
        for attempt in range(MAX_RETRIES):
            spec = self.router.get_best_model(deps.task_type)
            try:
                reply, tokens = self._run_with_spec_sync(spec, user_prompt, deps)
                self.router.track_usage(spec.model_id, project_scope=spec.project_scope, tokens=tokens)
                return reply
            except Exception as e:
                self._handle_model_failure(spec, e, attempt)
        raise RuntimeError("LLM run failed after retries")

    async def _execute_with_retries_async(self, user_prompt: str, deps: AgentRunDeps) -> str:
        for attempt in range(MAX_RETRIES):
            spec = self.router.get_best_model(deps.task_type)
            try:
                reply, tokens = await self._run_with_spec_async(spec, user_prompt, deps)
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

    def _run_with_spec_sync(self, spec: ModelSpec, user_prompt: str, deps: AgentRunDeps) -> tuple[str, int]:
        agent = self._get_agent_instance(spec)
        result = agent.run_sync(
            user_prompt,
            deps=deps,
            usage_limits=UsageLimits(request_limit=8),
        )
        return self.memory._coerce_text(result.output), self._extract_token_count(result)

    async def _run_with_spec_async(self, spec: ModelSpec, user_prompt: str, deps: AgentRunDeps) -> tuple[str, int]:
        agent = self._get_agent_instance(spec)
        result = await agent.run(
            user_prompt,
            deps=deps,
            usage_limits=UsageLimits(request_limit=8),
        )
        return self.memory._coerce_text(result.output), self._extract_token_count(result)

    def _get_agent_instance(self, spec: ModelSpec) -> PydanticAgent:
        cache_key = f"{spec.model_id}:{spec.api_key}:{spec.project_scope}"
        cached = self._agent_cache.get(cache_key)
        if cached is not None:
            return cached

        agent = PydanticAgent(
            model=self._build_model(spec),
            deps_type=AgentRunDeps,
            tools=tools,
            instructions=SYSTEM_PROMPT,
            retries=1,
            defer_model_check=True,
            end_strategy="early",
        )

        @agent.system_prompt
        def build_context_prompt(ctx: RunContext[AgentRunDeps]) -> str:
            return self._build_context_prompt(ctx.deps)

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

    def _build_context_prompt(self, deps: AgentRunDeps) -> str:
        from src.core.prompts import ENTITY_BLOCK

        context = deps.context_manager.assemble_context(
            query=deps.query,
            session_id=deps.session_id,
            task_type=deps.task_type,
        )
        prompt_parts: list[str] = []

        entities = context["entities"]
        if entities:
            entity_lines = []
            for entity in entities:
                node = entity["node"]
                conn_list = [
                    f"{connection['type']} -> {connection['target']} ({connection['target_label']})"
                    for connection in entity["connections"]
                ]
                entity_lines.append(
                    f"ENTITY: {node['name']} ({node['label']})\n"
                    f"Facts: {node.get('description', 'N/A')}\n"
                    f"Relations: {', '.join(conn_list)}"
                )
            prompt_parts.append(ENTITY_BLOCK.format(entities="\n\n".join(entity_lines)))

        rag = context["rag"]
        if rag:
            memory_lines = [f"[{m['metadata'].get('timestamp')}] {m['text']}" for m in rag]
            prompt_parts.append(CONTEXT_BLOCK.format(memories="\n".join(memory_lines)))

        history = context["history"]
        if history:
            history_lines = [f"{h['metadata'].get('role')}: {h['text']}" for h in history]
            prompt_parts.append(HISTORY_BLOCK.format(history="\n".join(history_lines)))

        return "\n\n".join(prompt_parts).strip()

    @staticmethod
    def _extract_token_count(result) -> int:
        usage = result.usage()
        return (usage.input_tokens or 0) + (usage.output_tokens or 0)

    def _store_interaction(self, user_text: str, reply: str | None, session_id: str, metadata: dict | None = None):
        """Store the conversation turn in memory backends."""
        ts = datetime.now(timezone.utc).isoformat()
        metadata = metadata or {}
        self.memory.store(user_text, role="user", session_id=session_id, timestamp=ts, **metadata)
        if reply:
            self.memory.store(reply, role="assistant", session_id=session_id, timestamp=ts, **metadata)

    async def _astore_interaction(self, user_text: str, reply: str | None, session_id: str, metadata: dict | None = None):
        """Async-safe variant for storing the conversation turn in memory backends."""
        ts = datetime.now(timezone.utc).isoformat()
        metadata = metadata or {}
        self.memory.store(user_text, role="user", session_id=session_id, timestamp=ts, **metadata)
        if reply:
            self.memory.store(reply, role="assistant", session_id=session_id, timestamp=ts, **metadata)


def process_message_sync(agent: Agent, user_id: str, text: str, session_id: str) -> str:
    """Compatibility helper for sync call sites that want a named function."""
    return agent.process_message(user_id, text, session_id)


async def process_message_async(agent: Agent, user_id: str, text: str, session_id: str) -> str:
    """Compatibility helper for async call sites that want a named function."""
    return await agent.aprocess_message(user_id, text, session_id)
