"""Concrete ``_AgentService`` — the singleton behind ``get_agent_service``.

The class is private. Public consumers see only the ``AgentService``
Protocol exported from ``__init__.py``. The single instance is built on
the first call to ``_AgentService.get()``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import ClassVar

from src.agent import AgentRunRequest, AgentRunResult
from src.agent._errors import AgentRunError
from src.agent._loop import run_agent_loop
from src.agent._models import get_llm
from src.agent._tools import get_tools
from src.log import get_logger

logger = get_logger(__name__)


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class _AgentService:
    """Concrete implementation. Construct only via ``_AgentService.get()``."""

    _instance: ClassVar["_AgentService | None"] = None

    def __init__(self, _key: object) -> None:
        if _key is not _SINGLETON_KEY:
            raise RuntimeError(
                "_AgentService is a singleton — use _AgentService.get()"
            )

    @classmethod
    def get(cls) -> "_AgentService":
        if cls._instance is None:
            cls._instance = cls(_SINGLETON_KEY)
            logger.info("agent_service_initialised")
        return cls._instance

    @classmethod
    def reset_for_tests(cls) -> None:
        """Drop the cached singleton. Test seam (mirrors ``_MemoryManager``)."""
        cls._instance = None

    async def arun(self, request: AgentRunRequest) -> AgentRunResult:
        try:
            reply = await run_agent_loop(
                request,
                llm=get_llm(),
                tools=get_tools(),
            )
        except AgentRunError:
            logger.error(
                "agent_run_failed",
                extra={"session_id": request.session_id},
                exc_info=True,
            )
            raise
        return AgentRunResult(
            reply=reply,
            session_id=request.session_id,
            reply_timestamp=_now_iso(),
        )


_SINGLETON_KEY = object()
