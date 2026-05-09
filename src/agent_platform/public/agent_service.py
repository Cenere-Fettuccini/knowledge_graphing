from __future__ import annotations

import json
from datetime import datetime, timezone

from src.agent_platform.public.contracts import AgentRunRequest, AgentRunResult, AgentStatus
from src.core.agent import Agent, BaseAgent
from src.memory.manager import get_memory_manager


class AgentService:
    """
    Public app-facing gateway to the shared autonomous agent system.

    Apps can submit requests without needing to know about prompt assembly,
    memory retrieval, model routing, tool execution, or credit governance.
    """

    def __init__(self, agent: BaseAgent | None = None) -> None:
        self._agent = agent or Agent(memory=get_memory_manager())

    def run(self, request: AgentRunRequest) -> AgentRunResult:
        effective_prompt = self._build_effective_prompt(request)
        reply = self._agent.process_message(
            request.user_id,
            request.message,
            request.session_id,
            message_timestamp=request.message_timestamp,
            prompt_text=effective_prompt,
            store_text=request.store_text or request.message,
            store_metadata=request.store_metadata,
        )
        return AgentRunResult(
            app_id=request.app_id,
            session_id=request.session_id,
            reply=reply,
            reply_timestamp=datetime.now(timezone.utc).isoformat(),
        )

    async def arun(self, request: AgentRunRequest) -> AgentRunResult:
        effective_prompt = self._build_effective_prompt(request)
        reply = await self._agent.aprocess_message(
            request.user_id,
            request.message,
            request.session_id,
            message_timestamp=request.message_timestamp,
            prompt_text=effective_prompt,
            store_text=request.store_text or request.message,
            store_metadata=request.store_metadata,
        )
        return AgentRunResult(
            app_id=request.app_id,
            session_id=request.session_id,
            reply=reply,
            reply_timestamp=datetime.now(timezone.utc).isoformat(),
        )

    def status(self, force: bool = False) -> AgentStatus:
        health = self._agent.status(force=force)
        return AgentStatus(
            status=health["status"],
            llm=health["llm"],
            memory=health["memory"],
        )

    async def astatus(self, force: bool = False) -> AgentStatus:
        health = await self._agent.astatus(force=force)
        return AgentStatus(
            status=health["status"],
            llm=health["llm"],
            memory=health["memory"],
        )

    def get_history(self, session_id: str, limit: int = 20) -> list[dict]:
        return self._agent.get_history(session_id, limit=limit)

    def clear_session(self, session_id: str) -> None:
        self._agent.clear_session(session_id)

    async def aquota_status(self) -> list[dict]:
        """Return per-model quota headroom without exposing llm_router internals.

        Each entry: {"model": str, "project_scope": str, "headroom": float (0–100),
                     "rpm_limit": int, "rpd_limit": int}
        """
        # Import here to keep agent_service free of a hard top-level router dep
        from src.core.router import llm_router  # noqa: PLC0415

        quota = []
        for model in llm_router.models:
            headroom = llm_router.limiter.get_headroom(
                model.model_id,
                model.project_scope,
                model.rpm_limit,
                model.rpd_limit,
                model.tpm_limit,
            )
            quota.append({
                "model": model.model_id.split("/")[-1],
                "project_scope": model.project_scope,
                "headroom": round(headroom * 100, 1),
                "rpm_limit": model.rpm_limit,
                "rpd_limit": model.rpd_limit,
            })
        return quota

    @staticmethod
    def _build_effective_prompt(request: AgentRunRequest) -> str:
        if request.prompt_text:
            return request.prompt_text
        if not request.context:
            return request.message
        return (
            f"Application: {request.app_id}\n"
            f"Context: {json.dumps(request.context, ensure_ascii=True, sort_keys=True)}\n\n"
            f"User request: {request.message}"
        )


_instance: AgentService | None = None


def get_agent_service() -> AgentService:
    """Return the shared AgentService, creating it on first call."""
    global _instance
    if _instance is None:
        _instance = AgentService()
    return _instance
