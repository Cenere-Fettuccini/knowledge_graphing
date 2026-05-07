from __future__ import annotations

from langchain_core.tools import tool

from src.agent_platform.tools.common import ensure_graph_online, logger
from src.memory.manager import memory_manager


@tool
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

        entity_id = None
        if about_entity:
            cypher = """
            MATCH (e) WHERE toLower(e.name) CONTAINS toLower($name)
            RETURN e.id AS id LIMIT 1
            """
            with memory_manager.neo4j.driver.session() as session:
                record = session.run(cypher, name=about_entity).single()
                if record:
                    entity_id = record["id"]

        belief_id = memory_manager.neo4j.upsert_belief(
            content=content,
            confidence=confidence,
            about_entity_id=entity_id,
            source_text=source_text or None,
        )
        return f"Belief stored (ID: {belief_id}): '{content[:60]}'"
    except Exception as e:
        return f"Error storing belief: {str(e)}"


@tool
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

        cypher = """
        MATCH (b:Belief)
        WHERE toLower(b.content) CONTAINS toLower($q)
        RETURN b.id AS id, b.content AS content,
               b.confidence AS confidence, b.status AS status
        ORDER BY b.created_at DESC
        LIMIT 1
        """
        with memory_manager.neo4j.driver.session() as session:
            record = session.run(cypher, q=belief_query).single()

        if not record:
            return f"No beliefs found matching '{belief_query}'"

        belief_id = record["id"]
        chain = memory_manager.neo4j.get_belief_chain(belief_id)
        evidence = memory_manager.neo4j.get_belief_evidence(belief_id)
        return {
            "current": {
                "content": record["content"],
                "confidence": record["confidence"],
                "status": record["status"],
            },
            "evolution_chain": chain,
            "evidence": evidence,
        }
    except Exception as e:
        return f"Error retrieving belief trail: {str(e)}"


@tool
def evolve_belief_tool(old_belief_query: str, new_content: str, reason: str = ""):
    """
    Evolve an existing belief by creating a new version that supersedes it.
    """
    logger.info("Tool Call: evolve_belief -> %s => %s", old_belief_query, new_content[:40])
    try:
        offline = ensure_graph_online()
        if offline:
            return offline

        cypher = """
        MATCH (b:Belief {status: 'active'})
        WHERE toLower(b.content) CONTAINS toLower($q)
        RETURN b.id AS id, b.content AS content
        ORDER BY b.created_at DESC LIMIT 1
        """
        with memory_manager.neo4j.driver.session() as session:
            record = session.run(cypher, q=old_belief_query).single()

        if not record:
            return f"No active belief found matching '{old_belief_query}'"

        new_id = memory_manager.neo4j.evolve_belief(
            old_belief_id=record["id"],
            new_content=new_content,
            reason=reason,
        )
        return (
            f"Belief evolved:\n"
            f"  OLD (superseded): '{record['content'][:60]}'\n"
            f"  NEW (active): '{new_content[:60]}' (ID: {new_id})"
        )
    except Exception as e:
        return f"Error evolving belief: {str(e)}"
