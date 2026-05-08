from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.core.agent import Agent


class FakeMemory:
    def __init__(self) -> None:
        self.stored: list[tuple[str, str, str, str]] = []

    def status(self) -> dict:
        return {
            "status": "online",
            "chroma": "online (0 memories)",
            "neo4j": "offline",
        }

    def store(self, text, role: str, session_id: str, timestamp: str, **_extra):
        self.stored.append((role, str(text), session_id, timestamp))

    def _coerce_text(self, value) -> str:
        return "" if value is None else str(value)


@pytest.mark.asyncio
async def test_astatus_uses_async_probe(monkeypatch):
    agent = Agent(memory=FakeMemory())
    spec = SimpleNamespace(model_id="fake-model", project_scope="test")
    probe_calls: list[object] = []

    monkeypatch.setattr(agent.router, "get_best_model", lambda _task_type: spec)

    def fail_sync_probe(*_args, **_kwargs):
        raise AssertionError("sync probe should not run in async status")

    async def fake_provider_probe(actual_spec):
        probe_calls.append(actual_spec)
        return True

    monkeypatch.setattr(agent, "_run_with_spec_sync", fail_sync_probe)
    monkeypatch.setattr(agent, "_run_with_spec_async", fail_sync_probe)
    monkeypatch.setattr(agent, "_probe_provider_async", fake_provider_probe)

    health = await agent.astatus(force=True)

    assert health["status"] == "online"
    assert health["llm"] == "online"
    assert probe_calls == [spec]


@pytest.mark.asyncio
async def test_aprocess_message_stores_without_sync_status(monkeypatch):
    memory = FakeMemory()
    agent = Agent(memory=memory)

    async def fake_execute(_prompt, _deps):
        return "async reply"

    def fail_sync_status(*_args, **_kwargs):
        raise AssertionError("sync status should not run in async message flow")

    async def fake_async_status(*_args, **_kwargs):
        return {
            "status": "online",
            "llm": "online",
            "memory": {
                "status": "online",
                "chroma": "online (0 memories)",
                "neo4j": "offline",
            },
        }

    monkeypatch.setattr(agent, "_execute_with_retries_async", fake_execute)
    monkeypatch.setattr(agent, "status", fail_sync_status)
    monkeypatch.setattr(agent, "astatus", fake_async_status)

    reply = await agent.aprocess_message("user-1", "hello", "session-1")

    assert reply == "async reply"
    assert [item[0] for item in memory.stored] == ["user", "assistant"]
