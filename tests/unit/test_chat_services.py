from src.apps.chat import services


def test_normalize_chat_context_preserves_structured_context():
    context = {
        "source_section": "financial",
        "context_type": "finance_overview",
        "context_id": "financial-manager",
        "context_summary": "Financial Manager overview",
        "context_payload": {"scope": "accounts"},
    }

    normalized = services.normalize_chat_context(context)

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
