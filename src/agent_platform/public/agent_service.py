from __future__ import annotations

import json

from src.agent_platform.public.contracts import AgentRunRequest, AgentRunResult, AgentStatus
from src.core.agent import Agent, BaseAgent
from src.memory.manager import memory_manager


class AgentService:
    """
    Public app-facing gateway to the shared autonomous agent system.

    Apps can submit requests without needing to know about prompt assembly,
    memory retrieval, model routing, tool execution, or credit governance.
    """

    def __init__(self, agent: BaseAgent | None = None) -> None:
        self._agent = agent or Agent(memory=memory_manager)

    def run(self, request: AgentRunRequest) -> AgentRunResult:
        effective_prompt = self._build_effective_prompt(request)
        reply = self._agent.process_message(
            request.user_id,
            request.message,
            request.session_id,
            prompt_text=effective_prompt,
            store_text=request.store_text or request.message,
        )
        return AgentRunResult(
            app_id=request.app_id,
            session_id=request.session_id,
            reply=reply,
        )

    async def arun(self, request: AgentRunRequest) -> AgentRunResult:
        effective_prompt = self._build_effective_prompt(request)
        reply = await self._agent.aprocess_message(
            request.user_id,
            request.message,
            request.session_id,
            prompt_text=effective_prompt,
            store_text=request.store_text or request.message,
        )
        return AgentRunResult(
            app_id=request.app_id,
            session_id=request.session_id,
            reply=reply,
        )

    def status(self, force: bool = False) -> AgentStatus:
        health = self._agent.status(force=force)
        return AgentStatus(
            status=health["status"],
            llm=health["llm"],
            memory=health["memory"],
        )

    def get_history(self, session_id: str, limit: int = 20) -> list[dict]:
        return self._agent.get_history(session_id, limit=limit)

    def clear_session(self, session_id: str) -> None:
        self._agent.clear_session(session_id)

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


agent_service = AgentService()
