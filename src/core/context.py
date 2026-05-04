import logging
from typing import List, Dict, Any
from src.core.config import settings
from src.memory.manager import memory_manager

logger = logging.getLogger(__name__)

class ContextManager:
    """
    Orchestrates multi-source context retrieval for the agent's prompt.
    Combines Episodic (Chroma), Relational (Neo4j), and Session History.
    """

    def __init__(self):
        self.memory = memory_manager

    def assemble_context(self, query: str, session_id: str, task_type: str) -> Dict[str, Any]:
        """
        Dynamically builds context based on the task type and entity mentions.
        """
        # 1. Determine retrieval depth
        k_map = {
            "QA": 5,
            "REASONING": 8,
            "EXTRACTION": 2,
            "SUMMARIZATION": 3,
            "CODE": 3
        }
        k = k_map.get(task_type, 3)

        # 2. Episodic RAG (ChromaDB)
        rag_memories = []
        try:
            rag_memories = self.memory.search(query, k=k)
        except Exception as e:
            logger.error("RAG search failed: %s", e)

        # 3. Entity Linking (Neo4j)
        # We look for entities mentioned in the query that exist in the graph
        entities = []
        try:
            # Simple keyword match for now
            graph_data = self.memory.neo4j.get_graph_overview(limit=100)
            mentioned_nodes = [
                n for n in graph_data["nodes"] 
                if n["name"].lower() in query.lower()
            ]
            
            for node in mentioned_nodes:
                details = self.memory.neo4j.get_node_detail(node["id"])
                entities.append(details)
        except Exception as e:
            logger.error("Entity linking failed: %s", e)

        # 4. Session History
        history = []
        try:
            history = self.memory.get_history(session_id, limit=settings.context_window_turns)
        except Exception as e:
            logger.error("History retrieval failed: %s", e)

        return {
            "rag": rag_memories,
            "entities": entities,
            "history": history
        }

context_manager = ContextManager()
