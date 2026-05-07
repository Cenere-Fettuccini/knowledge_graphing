"""Integration tests for the Agent core — verifies the full retrieve → generate → store loop."""

import pytest
import uuid
from langchain_core.messages import AIMessage
from src.core.agent import Agent
from src.memory.manager import MemoryManager


class _FakeLLM:
    def bind_tools(self, _tools):
        return self

    def invoke(self, messages):
        full_text = "\n".join(str(getattr(msg, "content", "")) for msg in messages)
        latest = str(messages[-1].content)

        if "What programming language do I like?" in latest and "Rust" in full_text:
            return AIMessage(content="You like Rust.")
        if "Hello, how are you?" in latest:
            return AIMessage(content="I'm doing well and ready to help.")
        return AIMessage(content=f"I heard you: {latest}")


@pytest.fixture
def agent(monkeypatch):
    """Agent backed by an isolated in-memory ChromaDB and fake LLM."""
    monkeypatch.setattr(Agent, "_get_llm_instance", lambda self, spec: _FakeLLM())
    mem = MemoryManager(persist_path=":memory:")
    return Agent(memory=mem)


def test_agent_responds(agent):
    """The agent should return a non-empty string response."""
    session = f"test_{uuid.uuid4().hex[:8]}"
    reply = agent.process_message("user1", "Hello, how are you?", session)
    assert isinstance(reply, str)
    assert len(reply) > 0


def test_agent_stores_interaction(agent):
    """After processing, both user message and reply should be in ChromaDB."""
    session = f"test_{uuid.uuid4().hex[:8]}"
    agent.process_message("user1", "My cat's name is Whiskers.", session)

    history = agent.memory.get_history(session)
    assert len(history) == 2  # user + assistant

    roles = {h["metadata"]["role"] for h in history}
    assert roles == {"user", "assistant"}

    # The user message should be findable
    texts = [h["text"] for h in history]
    assert any("Whiskers" in t for t in texts)


def test_agent_recalls_memory(agent):
    """The agent should use stored memories to inform its response."""
    session = f"test_{uuid.uuid4().hex[:8]}"

    # Teach it a fact
    agent.process_message("user1", "My favorite programming language is Rust.", session)

    # Ask about it
    reply = agent.process_message("user1", "What programming language do I like?", session)

    # The response should reference Rust (retrieved via RAG or history)
    assert "rust" in reply.lower() or "Rust" in reply


def test_ephemeral_not_in_future_context(agent):
    """Ephemeral memories should not appear after being cleared."""
    session = f"test_{uuid.uuid4().hex[:8]}"

    # Store a secret ephemerally (bypass agent, go direct to memory)
    agent.memory.store(
        "The launch code is 12345.",
        role="user",
        session_id=session,
        is_ephemeral=True,
    )

    # Verify it exists
    results = agent.memory.search("launch code", k=1, session_id=session)
    assert len(results) == 1

    # Wipe ephemeral
    agent.memory.clear_ephemeral(session_id=session)

    # Verify it's gone
    results = agent.memory.search("launch code", k=1, session_id=session)
    assert len(results) == 0
