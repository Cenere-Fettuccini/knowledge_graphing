from __future__ import annotations

from src.agent_platform.tools.common import ensure_graph_online, logger
from src.memory.manager import get_memory_manager


def save_belief(
    content: str,
    about_entity: str = "",
    confidence: float = 0.8,
    source_text: str = "",
):
    """
    Store a belief or opinion in the Knowledge Graph.
    A belief tracks how the user's thinking on a topic evolves over time.
    """
    logger.info("Tool Call: save_belief -> %s", content[:50])
    try:
        offline = ensure_graph_online()
        if offline:
            return offline

        memory = get_memory_manager()
        entity_id = memory.find_entity(about_entity) if about_entity else None
        belief_id = memory.upsert_belief(
            content,
            confidence,
            about_entity_id=entity_id,
            source_text=source_text or None,
        )
        return f"Belief stored (ID: {belief_id}): '{content[:60]}'"
    except Exception as e:
        return f"Error storing belief: {str(e)}"


def get_belief_trail(belief_query: str):
    """
    Search for a belief by keyword and return its full evolution chain
    and evidence (supporting and weakening conversations).
    """
    logger.info("Tool Call: get_belief_trail -> %s", belief_query)
    try:
        offline = ensure_graph_online()
        if offline:
            return offline

        memory = get_memory_manager()
        belief = memory.find_belief(belief_query)
        if not belief:
            return f"No beliefs found matching '{belief_query}'"

        trail = memory.graph_belief_trail(belief["id"])
        return {
            "current": {
                "content": belief["content"],
                "confidence": belief["confidence"],
                "status": belief["status"],
            },
            "evolution_chain": trail["chain"],
            "evidence": trail["evidence"],
        }
    except Exception as e:
        return f"Error retrieving belief trail: {str(e)}"


def evolve_belief_tool(old_belief_query: str, new_content: str, reason: str = ""):
    """
    Evolve an existing belief by creating a new version that supersedes it.
    """
    logger.info("Tool Call: evolve_belief -> %s => %s", old_belief_query, new_content[:40])
    try:
        offline = ensure_graph_online()
        if offline:
            return offline

        memory = get_memory_manager()
        old = memory.find_belief(old_belief_query, active_only=True)
        if not old:
            return f"No active belief found matching '{old_belief_query}'"

        new_id = memory.evolve_belief(old["id"], new_content, reason=reason)
        return (
            f"Belief evolved:\n"
            f"  OLD (superseded): '{old['content'][:60]}'\n"
            f"  NEW (active): '{new_content[:60]}' (ID: {new_id})"
        )
    except Exception as e:
        return f"Error evolving belief: {str(e)}"
