from __future__ import annotations

from src.agent_platform.tools.common import ensure_graph_online, logger
from src.memory.manager import memory_manager


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

        cypher = """
        MATCH (n)
        WHERE toLower(n.name) CONTAINS toLower($query)
        RETURN n.id AS id, n.name AS name, labels(n)[0] AS label,
               n.description AS description
        LIMIT 10
        """
        results = []
        with memory_manager.neo4j.driver.session() as session:
            records = session.run(cypher, query=query)
            for record in records:
                results.append({
                    "id": record["id"],
                    "name": record["name"],
                    "label": record["label"],
                    "description": record["description"],
                })
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
        node_id = memory_manager.neo4j.add_node(
            entity_label,
            entity_name,
            {"description": fact},
        )
        return f"Successfully stored {entity_name} (ID: {node_id})"
    except Exception as e:
        return f"Error storing knowledge: {str(e)}"
