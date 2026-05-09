from src.memory.knowledge_extractor import extract_knowledge_signals


def test_extract_knowledge_signals_prefers_context_anchor_for_opinions():
    signals = extract_knowledge_signals(
        "I think showing all of the data is pretty useless.",
        context={
            "context_summary": "Explorer Graph (System)",
            "context_payload": {"node": {"label": "Entity"}},
        },
    )

    assert signals
    signal = signals[0]
    assert signal.entity_name == "Explorer Graph"
    assert signal.kind in {"opinion", "evaluation"}


def test_extract_knowledge_signals_captures_favorite_preferences():
    signals = extract_knowledge_signals("My favorite programming language is Rust.")

    assert len(signals) == 1
    assert signals[0].entity_name == "Programming Language"
    assert signals[0].kind == "preference"
    assert "rust" in signals[0].content.lower()
