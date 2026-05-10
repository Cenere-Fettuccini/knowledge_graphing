from __future__ import annotations

import uuid

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


def store_knowledge(entity_name: str, entity_label: str, fact: str):
    """
    Store a new fact or entity in the Knowledge Graph.
    Example: entity_name="Kevin", entity_label="Person", fact="Lives in London"
    """
    logger.info("Tool Call: store_knowledge -> %s is a %s", entity_name, entity_label)
    try:
        node_id = str(uuid.uuid4())
        get_memory_manager().upsert_node(
            node_id=node_id,
            labels=[entity_label],
            name=entity_name,
            properties={"description": fact},
        )
        return f"Successfully stored {entity_name} (ID: {node_id})"
    except Exception as e:
        return f"Error storing knowledge: {str(e)}"
