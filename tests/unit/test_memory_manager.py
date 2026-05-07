from src.memory.manager import MemoryManager


def test_coerce_text_extracts_text_from_content_blocks():
    manager = MemoryManager.__new__(MemoryManager)

    value = [
        {"type": "text", "text": "Your name is Kevin.", "extras": {"signature": "abc"}},
        {"type": "text", "text": "You like tea."},
    ]

    assert manager._coerce_text(value) == "Your name is Kevin.\nYou like tea."


def test_coerce_text_handles_plain_string():
    manager = MemoryManager.__new__(MemoryManager)

    assert manager._coerce_text("hello") == "hello"
