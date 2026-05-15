from __future__ import annotations

from src.agent_platform.tools.common import ensure_graph_online, logger
from src.memory.manager import get_memory_manager


def search_knowledge_graph(query: str):
    """
    Search the Knowledge Graph (Neo4j) for specific entities, relationships, or facts.
    Use this when you need to understand existing connections or find structured data.
    """
    logger.info("Tool Call: search_knowledge_graph -> %s", query)
    try:
        offline = ensure_graph_online()
        if offline:
            return offline

        results = get_memory_manager().search_nodes(query, limit=10)
        return results if results else f"No entities found matching '{query}'"
    except Exception as e:
        return f"Error searching graph: {str(e)}"

# store_knowledge was retired in S0.10 — use graph_write with an EntityIntent
# (plus an EdgeIntent so the new node isn't rejected by the isolation guard).
