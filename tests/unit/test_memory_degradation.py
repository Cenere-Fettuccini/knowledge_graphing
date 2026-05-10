"""Tests for graceful degradation signaling end-to-end.

Covers MemoryManager.snapshot_health, AgentService surfacing
memory_degraded on AgentRunResult, and chat services passing the flag
through to the response.
"""

from __future__ import annotations

import asyncio

from src.agent_platform.public.agent_service import AgentService
from src.agent_platform.public.contracts import AgentRunRequest, AgentRunResult
from src.apps.chat import services
from src.memory.manager import MemoryManager


# ── snapshot_health ─────────────────────────────────────────────────────────


class _FakeSpillover:
    def __init__(self, pending=None):
        self._pending = pending or {"chroma": 0, "neo4j": 0}

    def pending_counts(self):
        return dict(self._pending)


def _build_manager(*, status_dict, spillover_pending=None):
    manager = MemoryManager.__new__(MemoryManager)
    manager.spillover = _FakeSpillover(spillover_pending)
    manager.status = lambda: dict(status_dict)  # type: ignore[assignment]
    return manager


def test_snapshot_health_reports_clean_when_all_online():
    manager = _build_manager(
        status_dict={"status": "online", "neo4j": "online (5 nodes)", "chroma": "online (12 memories)"},
    )
    snap = manager.snapshot_health()
    assert snap["degraded"] is False
    assert snap["status"] == "online"
    assert snap["neo4j"] == "online"
    assert snap["chroma"] == "online"
    assert snap["spillover_pending"] == {"chroma": 0, "neo4j": 0}


def test_snapshot_health_marks_degraded_when_chroma_offline():
    manager = _build_manager(
        status_dict={"status": "degraded", "neo4j": "online", "chroma": "error (TimeoutError)"},
    )
    snap = manager.snapshot_health()
    assert snap["degraded"] is True
    assert snap["chroma"] == "offline"
    assert snap["neo4j"] == "online"


def test_snapshot_health_marks_degraded_when_neo4j_offline():
    manager = _build_manager(
        status_dict={"status": "degraded", "neo4j": "error", "chroma": "online"},
    )
    snap = manager.snapshot_health()
    assert snap["degraded"] is True
    assert snap["neo4j"] == "offline"


def test_snapshot_health_marks_degraded_when_spillover_pending_even_if_backends_recovered():
    """Backends came back online but spillover hasn't drained yet — still degraded."""
    manager = _build_manager(
        status_dict={"status": "online", "neo4j": "online", "chroma": "online"},
        spillover_pending={"chroma": 0, "neo4j": 3},
    )
    snap = manager.snapshot_health()
    assert snap["degraded"] is True
    assert snap["spillover_pending"]["neo4j"] == 3


def test_snapshot_health_handles_spillover_failure_gracefully():
    manager = _build_manager(
        status_dict={"status": "online", "neo4j": "online", "chroma": "online"},
    )

    class _BrokenSpillover:
        def pending_counts(self):
            raise RuntimeError("disk read failed")

    manager.spillover = _BrokenSpillover()
    snap = manager.snapshot_health()
    # Falls back to zero counts and treats backends as healthy.
    assert snap["spillover_pending"] == {"chroma": 0, "neo4j": 0}
    assert snap["degraded"] is False


# ── AgentService surfaces memory_degraded ────────────────────────────────────


class _FakeAgent:
    def __init__(self, memory):
        self.memory = memory

    async def aprocess_message(self, *args, **kwargs):
        return "agent reply"

    def process_message(self, *args, **kwargs):
        return "agent reply"


def _make_request():
    return AgentRunRequest(
        app_id="chat",
        user_id="web_user",
        session_id="s-1",
        message="hello",
    )


def test_agent_service_arun_includes_memory_degraded_when_snapshot_says_so():
    class _DegradedMemory:
        def snapshot_health(self):
            return {
                "status": "degraded",
                "chroma": "offline",
                "neo4j": "online",
                "spillover_pending": {"chroma": 2, "neo4j": 0},
                "degraded": True,
                "details": {"chroma": "error", "neo4j": "online"},
            }

    service = AgentService(agent=_FakeAgent(memory=_DegradedMemory()))
    result = asyncio.run(service.arun(_make_request()))
    assert isinstance(result, AgentRunResult)
    assert result.memory_degraded is True
    assert result.memory_health is not None
    assert result.memory_health["chroma"] == "offline"
    assert result.memory_health["spillover_pending"]["chroma"] == 2


def test_agent_service_arun_clean_run_reports_not_degraded():
    class _CleanMemory:
        def snapshot_health(self):
            return {
                "status": "online",
                "chroma": "online",
                "neo4j": "online",
                "spillover_pending": {"chroma": 0, "neo4j": 0},
                "degraded": False,
                "details": {},
            }

    service = AgentService(agent=_FakeAgent(memory=_CleanMemory()))
    result = asyncio.run(service.arun(_make_request()))
    assert result.memory_degraded is False
    assert result.memory_health["degraded"] is False


def test_agent_service_arun_tolerates_memory_without_snapshot_health():
    """Older memory implementations might not have snapshot_health — must not crash."""
    class _LegacyMemory:
        # no snapshot_health attribute
        pass

    service = AgentService(agent=_FakeAgent(memory=_LegacyMemory()))
    result = asyncio.run(service.arun(_make_request()))
    assert result.memory_degraded is False
    assert result.memory_health is None


def test_agent_service_arun_swallows_snapshot_exceptions():
    class _ThrowingMemory:
        def snapshot_health(self):
            raise RuntimeError("snapshot blew up")

    service = AgentService(agent=_FakeAgent(memory=_ThrowingMemory()))
    result = asyncio.run(service.arun(_make_request()))
    # Must not propagate — degradation reporting is best-effort.
    assert result.memory_degraded is False
    assert result.memory_health is None


# ── chat.send_chat_message passes the flag through ──────────────────────────


class _StubAgentService:
    def __init__(self, *, degraded, health):
        self._degraded = degraded
        self._health = health

    async def arun(self, request):
        return AgentRunResult(
            app_id=request.app_id,
            session_id=request.session_id,
            reply="ok",
            reply_timestamp="2026-05-11T12:00:00Z",
            memory_degraded=self._degraded,
            memory_health=self._health,
        )


def test_send_chat_message_propagates_memory_degraded_to_response():
    health = {"degraded": True, "chroma": "offline", "neo4j": "online"}
    response = asyncio.run(services.send_chat_message(
        app_id="chat",
        user_id="u",
        session_id="s-1",
        text="hello",
        memory=None,
        service=_StubAgentService(degraded=True, health=health),
    ))
    assert response["memory_degraded"] is True
    assert response["memory_health"] == health


def test_send_chat_message_clean_run_reports_no_degradation():
    response = asyncio.run(services.send_chat_message(
        app_id="chat",
        user_id="u",
        session_id="s-1",
        text="hello",
        memory=None,
        service=_StubAgentService(degraded=False, health={"degraded": False}),
    ))
    assert response["memory_degraded"] is False
    assert response["memory_health"]["degraded"] is False
