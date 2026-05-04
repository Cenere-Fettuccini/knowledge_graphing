import logging
from typing import List, Dict, Any
from langchain_core.tools import tool
from src.memory.manager import memory_manager

logger = logging.getLogger(__name__)

@tool
def search_knowledge_graph(query: str):
    """
    Search the Knowledge Graph (Neo4j) for specific entities, relationships, or facts.
    Use this when you need to understand existing connections or find structured data.
    """
    logger.info(f"Tool Call: search_knowledge_graph -> {query}")
    # For now, we perform a simple keyword search on node names
    # In the future, this can be upgraded to full Cypher generation
    try:
        overview = memory_manager.neo4j.get_graph_overview(limit=50)
        # Filter nodes locally for simple search
        results = [n for n in overview["nodes"] if query.lower() in n.get("name", "").lower()]
        return results if results else f"No entities found matching '{query}'"
    except Exception as e:
        return f"Error searching graph: {str(e)}"

@tool
def store_knowledge(entity_name: str, entity_label: str, fact: str):
    """
    Store a new fact or entity in the Knowledge Graph.
    Example: entity_name="Kevin", entity_label="Person", fact="Lives in London"
    """
    logger.info(f"Tool Call: store_knowledge -> {entity_name} is a {entity_label}")
    try:
        node_id = memory_manager.neo4j.add_node(entity_label, entity_name, {"description": fact})
        return f"Successfully stored {entity_name} (ID: {node_id})"
    except Exception as e:
        return f"Error storing knowledge: {str(e)}"

@tool
def search_memories(query: str):
    """
    Search past conversation memories (ChromaDB) for context or history.
    Use this to recall what was discussed in previous sessions.
    """
    logger.info(f"Tool Call: search_memories -> {query}")
    try:
        results = memory_manager.chroma.search(query, n_results=3)
        return results if results else "No similar memories found."
    except Exception as e:
        return f"Error searching memories: {str(e)}"

# List of tools to be used by the agent
tools = [search_knowledge_graph, store_knowledge, search_memories]
