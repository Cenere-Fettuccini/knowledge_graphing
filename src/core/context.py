import logging
from typing import List, Dict, Any
from src.core.config import settings
from src.memory.manager import get_memory_manager

logger = logging.getLogger(__name__)

class ContextManager:
    """
    Orchestrates multi-source context retrieval for the agent's prompt.
    Combines Episodic (Chroma), Relational (Neo4j), and Session History.
    """

    def __init__(self, memory=None):
        self.memory = memory or get_memory_manager()

    def assemble_context(self, query: str, session_id: str, task_type: str) -> Dict[str, Any]:
        """
        Dynamically builds context based on the task type and entity mentions.
        """
        k_map = {
            "QA": 5,
            "REASONING": 8,
            "EXTRACTION": 2,
            "SUMMARIZATION": 3,
            "CODE": 3
        }
        k = k_map.get(task_type, 3)

        rag_memories = []
        try:
            rag_memories = self.memory.search(query, k=k)
        except Exception as e:
            logger.error("RAG search failed: %s", e)

        entities = []
        try:
            if self.memory.is_graph_online():
                entities = self._find_entities(query)
        except Exception as e:
            logger.error("Entity linking failed: %s", e)

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

    def _find_entities(self, query: str) -> list:
        """
        Search the graph for entities mentioned in the query and return their details.
        """
        words = [w.strip(".,!?\"'()") for w in query.split() if len(w.strip(".,!?\"'()")) >= 3]
        if not words:
            return []

        seen_ids: set[str] = set()
        results = []
        for word in words:
            for node in self.memory.search_nodes(word, limit=5):
                node_id = node.get("id")
                if node_id and node_id not in seen_ids:
                    seen_ids.add(node_id)
                    details = self.memory.graph_node_detail(node_id)
                    if details.get("node"):
                        results.append(details)
        return results
