import logging
from datetime import datetime
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
    try:
        if not memory_manager.neo4j.driver:
            return "Knowledge Graph is currently offline."
        
        # Use Cypher CONTAINS for server-side filtering
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
            for r in records:
                results.append({
                    "id": r["id"], "name": r["name"],
                    "label": r["label"], "description": r["description"]
                })
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
        results = memory_manager.search(query, k=3)
        return results if results else "No similar memories found."
    except Exception as e:
        return f"Error searching memories: {str(e)}"

@tool
def get_current_time():
    """
    Returns the current local date and time.
    Use this when the user asks about the time, date, or relative events (e.g., 'tomorrow', 'next week').
    """
    from datetime import datetime
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"The current local time is {now}"

@tool
def create_task(title: str, due_date: str = None, priority: str = "medium"):
    """
    Create a new task or goal for the user.
    Example: title="Finish project", due_date="2024-05-10", priority="high"
    """
    logger.info(f"Tool Call: create_task -> {title}")
    try:
        properties = {
            "status": "TODO",
            "due_date": due_date,
            "priority": priority,
            "created_at": datetime.now().isoformat()
        }
        node_id = memory_manager.neo4j.add_node("Task", title, properties)
        return f"Task created: '{title}' (ID: {node_id})"
    except Exception as e:
        return f"Error creating task: {str(e)}"

# List of tools to be used by the agent
tools = [search_knowledge_graph, store_knowledge, search_memories, get_current_time, create_task]
