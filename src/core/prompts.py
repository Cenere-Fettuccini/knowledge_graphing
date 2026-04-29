"""System prompt templates and context-injection blocks."""

SYSTEM_PROMPT = """You are AIManager, a personal AI assistant.
Your goal is to be helpful, concise, and memory-aware."""

CONTEXT_BLOCK = """Here are relevant past memories:
{memories}"""

HISTORY_BLOCK = """Here is the recent conversation history:
{history}"""
