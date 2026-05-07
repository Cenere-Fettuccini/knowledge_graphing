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

    def __init__(self, memory=None):
        self.memory = memory or memory_manager

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

        # 3. Entity Linking (Neo4j) — targeted Cypher search, not full scan
        entities = []
        try:
            if self.memory.neo4j.driver:
                entities = self._find_entities(query)
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

    def _find_entities(self, query: str) -> list:
        """
        Search Neo4j for entities mentioned in the query using a Cypher
        case-insensitive CONTAINS filter instead of pulling the entire graph.
        """
        # Extract candidate words (3+ chars to avoid noise)
        words = [w.strip(".,!?\"'()") for w in query.split() if len(w.strip(".,!?\"'()")) >= 3]
        if not words:
            return []

        # Build a Cypher WHERE clause that checks node names against query words
        conditions = " OR ".join([f"toLower(n.name) CONTAINS toLower($w{i})" for i in range(len(words))])
        params = {f"w{i}": w for i, w in enumerate(words)}
        
        cypher = f"""
        MATCH (n)
        WHERE {conditions}
        RETURN n.id AS id
        LIMIT 5
        """
        
        results = []
        try:
            with self.memory.neo4j.driver.session() as session:
                records = session.run(cypher, **params)
                for record in records:
                    node_id = record["id"]
                    if node_id:
                        details = self.memory.neo4j.get_node_detail(node_id)
                        if details.get("node"):
                            results.append(details)
        except Exception as e:
            logger.error("Neo4j entity search failed: %s", e)
        
        return results

context_manager = ContextManager()
