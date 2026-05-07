from __future__ import annotations

from langchain_core.tools import tool

from src.agent_platform.tools.common import logger
from src.memory.manager import memory_manager


@tool
def search_memories(query: str):
    """
    Search past conversation memories (ChromaDB) for context or history.
    Use this to recall what was discussed in previous sessions.
    """
    logger.info("Tool Call: search_memories -> %s", query)
    try:
        results = memory_manager.search(query, k=3)
        return results if results else "No similar memories found."
    except Exception as e:
        return f"Error searching memories: {str(e)}"
