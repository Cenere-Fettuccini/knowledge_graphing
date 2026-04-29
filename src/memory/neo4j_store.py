"""src/memory/neo4j_store.py

Neo4j Knowledge Graph backend.
Provides basic entity/relation operations and handles Conversation tracking.
"""

import logging
from typing import Any

from neo4j import GraphDatabase, exceptions

from src.core.config import settings

logger = logging.getLogger(__name__)

class Neo4jStore:
    def __init__(self) -> None:
        self._driver = None
        try:
            self._driver = GraphDatabase.driver(
                settings.neo4j_uri,
                auth=(settings.neo4j_user, settings.neo4j_password)
            )
            # Ensure constraints
            with self._driver.session() as session:
                session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (e:Entity) REQUIRE e.id IS UNIQUE")
                session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (u:User) REQUIRE u.id IS UNIQUE")
                session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (c:Conversation) REQUIRE c.id IS UNIQUE")
            logger.info("Neo4jStore connected successfully")
        except exceptions.ServiceUnavailable:
            logger.warning("Could not connect to Neo4j at %s. Graph features will be disabled.", settings.neo4j_uri)
        except Exception as e:
            logger.error("Error connecting to Neo4j: %s", e)

    def close(self) -> None:
        if self._driver:
            self._driver.close()

    @property
    def is_connected(self) -> bool:
        if not self._driver:
            return False
        try:
            self._driver.verify_connectivity()
            return True
        except Exception:
            return False

    # ── Sessions / Conversations ──────────────────────────────────────────────

    def get_or_create_user(self, user_id: str) -> None:
        if not self.is_connected: return
        with self._driver.session() as session:
            session.run("MERGE (u:User {id: $user_id})", user_id=user_id)

    def register_session(self, user_id: str, session_id: str) -> None:
        """Create a Conversation node and link it to the User."""
        if not self.is_connected: return
        self.get_or_create_user(user_id)
        query = """
        MATCH (u:User {id: $user_id})
        MERGE (c:Conversation {id: $session_id})
        MERGE (u)-[:OWNS_CONVERSATION]->(c)
        """
        with self._driver.session() as session:
            session.run(query, user_id=user_id, session_id=session_id)

    def set_active_session(self, user_id: str, session_id: str) -> None:
        """Mark this session as the active one for the user."""
        if not self.is_connected: return
        self.register_session(user_id, session_id)
        query = """
        MATCH (u:User {id: $user_id})
        OPTIONAL MATCH (u)-[r:HAS_ACTIVE_SESSION]->(:Conversation)
        DELETE r
        WITH u
        MATCH (c:Conversation {id: $session_id})
        MERGE (u)-[:HAS_ACTIVE_SESSION]->(c)
        """
        with self._driver.session() as session:
            session.run(query, user_id=user_id, session_id=session_id)

    def get_active_session(self, user_id: str) -> str | None:
        """Retrieve the active session ID for the user."""
        if not self.is_connected: return None
        query = """
        MATCH (u:User {id: $user_id})-[:HAS_ACTIVE_SESSION]->(c:Conversation)
        RETURN c.id AS session_id
        """
        with self._driver.session() as session:
            result = session.run(query, user_id=user_id).single()
            return result["session_id"] if result else None

    def pin_session(self, user_id: str, session_id: str, name: str) -> None:
        """Pin a conversation with a human-readable name."""
        if not self.is_connected: return
        query = """
        MATCH (u:User {id: $user_id})-[:OWNS_CONVERSATION]->(c:Conversation {id: $session_id})
        MERGE (u)-[p:PINNED_CONVERSATION {name: $name}]->(c)
        """
        with self._driver.session() as session:
            session.run(query, user_id=user_id, session_id=session_id, name=name)

    def get_pinned_sessions(self, user_id: str) -> list[dict[str, str]]:
        """List all pinned sessions for the user."""
        if not self.is_connected: return []
        query = """
        MATCH (u:User {id: $user_id})-[p:PINNED_CONVERSATION]->(c:Conversation)
        RETURN c.id AS session_id, p.name AS name
        """
        with self._driver.session() as session:
            results = session.run(query, user_id=user_id)
            return [{"session_id": r["session_id"], "name": r["name"]} for r in results]

    # ── Basic Knowledge Graph Operations ──────────────────────────────────────

    def upsert_entity(self, entity_id: str, label: str, properties: dict[str, Any]) -> None:
        if not self.is_connected: return
        # A basic implementation for Step 5
        query = f"""
        MERGE (e:{label} {{id: $id}})
        SET e += $properties
        """
        with self._driver.session() as session:
            session.run(query, id=entity_id, properties=properties)
