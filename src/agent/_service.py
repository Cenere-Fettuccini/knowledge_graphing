"""Concrete ``_AgentService`` — one singleton per registered agent name.

The class is private. Public consumers see only the ``AgentService``
Protocol and the ``get_agent_service(name)`` factory. Each name
corresponds to a ``BaseAgent`` subclass registered under ``_agents/``;
the service for that name binds the agent's prompt to a model and a
tool subset (both resolved through their registries) and exposes
``arun`` against that triple.

A per-name singleton lets every agent type cache its wiring without
crosstalk (the chat agent and a future graph-builder agent both have
their own ``_AgentService`` instance).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import ClassVar

from src.agent import AgentRunRequest, AgentRunResult
from src.agent._agents import get_agent_def
from src.agent._agents._base import BaseAgent
from src.agent._errors import AgentRunError
from src.agent._loop import run_agent_loop
from src.agent._models import get_model
from src.agent._models._base import BaseModel
from src.agent._tools import get_tool
from src.agent._tools._base import BaseTool
from src.log import get_logger

logger = get_logger(__name__)


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class _AgentService:
    """Concrete implementation. One instance per registered agent name."""

    _instances: ClassVar[dict[str, "_AgentService"]] = {}

    def __init__(
        self,
        _key: object,
        *,
        agent_def: type[BaseAgent],
        model: BaseModel,
        tools: list[BaseTool],
    ) -> None:
        if _key is not _SINGLETON_KEY:
            raise RuntimeError(
                "_AgentService is a singleton — use _AgentService.get(name)"
            )
        self._agent_def = agent_def
        self._model = model
        self._tools = tools

    @classmethod
    def get(cls, agent_name: str) -> "_AgentService":
        if agent_name not in cls._instances:
            agent_def = get_agent_def(agent_name)
            model = get_model(agent_def.model)
            tools = [get_tool(t) for t in agent_def.tools]
            cls._instances[agent_name] = cls(
                _SINGLETON_KEY, agent_def=agent_def, model=model, tools=tools
            )
            logger.info(
                "agent_service_initialised",
                extra={
                    "agent": agent_name,
                    "model": agent_def.model,
                    "tools": list(agent_def.tools),
                },
            )
        return cls._instances[agent_name]

    @classmethod
    def reset_for_tests(cls) -> None:
        """Drop every cached agent service. Test seam."""
        cls._instances.clear()

    def identify(self) -> dict:
        """Self-description: which agent + model + tool set this service binds."""
        return {
            "kind": "agent_service",
            "agent": self._agent_def.identify(),
            "model": self._model.identify(),
            "tools": [t.identify() for t in self._tools],
        }

    async def arun(self, request: AgentRunRequest) -> AgentRunResult:
        try:
            reply = await run_agent_loop(
                request,
                prompt=self._agent_def.prompt,
                llm=self._model,
                tools=self._tools,
            )
        except AgentRunError:
            logger.error(
                "agent_run_failed",
                extra={
                    "session_id": request.session_id,
                    "agent": self._agent_def.name,
                },
                exc_info=True,
            )
            raise
        return AgentRunResult(
            reply=reply,
            session_id=request.session_id,
            reply_timestamp=_now_iso(),
        )


_SINGLETON_KEY = object()
