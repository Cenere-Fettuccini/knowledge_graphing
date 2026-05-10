from src.apps.chat import services


def test_normalize_chat_context_preserves_structured_context():
    context = {
        "source_section": "financial",
        "context_type": "finance_overview",
        "context_id": "financial-manager",
        "context_summary": "Financial Manager overview",
        "context_payload": {"scope": "accounts"},
    }

    normalized = services.normalize_chat_context(context, memory=None)

    assert normalized == context


def test_build_effective_prompt_includes_context_metadata():
    context = {
        "source_section": "explorer",
        "context_type": "graph_node",
        "context_id": "belief-1",
        "context_summary": "Belief node",
        "context_payload": {"relation_summary": "SUPPORTED_BY -> Memory"},
    }

    prompt = services.build_effective_prompt("Explain this belief", context)

    assert "Source section: explorer" in prompt
    assert "Context type: graph_node" in prompt
    assert "Context id: belief-1" in prompt
    assert "Context relationships: SUPPORTED_BY -> Memory" in prompt
    assert "User request: Explain this belief" in prompt


def test_get_chat_session_returns_chronological_order_from_history():
    session_id = "session-1"

    class MockMemory:
        def get_history(self, sid, limit=100):
            if sid != session_id:
                return []
            return [
                {
                    "id": "assistant-1",
                    "text": "Reply",
                    "metadata": {"role": "assistant", "timestamp": "2026-05-09T01:02:14.684000+00:00"},
                },
                {
                    "id": "user-1",
                    "text": "Question",
                    "metadata": {"role": "user", "timestamp": "2026-05-09T01:02:14.683000+00:00"},
                },
            ]

    payload = services.get_chat_session(session_id, MockMemory())

    assert [m["role"] for m in payload["messages"]] == ["user", "assistant"]
