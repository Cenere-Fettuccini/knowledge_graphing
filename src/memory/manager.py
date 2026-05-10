"""Unified facade over all memory stores — the only import other modules need."""

import json
import logging
import time
from src.core.config import settings
from src.memory.spillover import SpilloverWriter
from src.memory.stores.chroma_store import ChromaStore
from src.memory.stores.neo4j_store import Neo4jStore

logger = logging.getLogger(__name__)


class MemoryManager:
    """
    Single entry-point for all memory operations.
    Hides backend details (Chroma, Neo4j) behind a clean API.
    """

    def __init__(self, persist_path=None, spillover_dir: str | None = None):
        self.chroma = ChromaStore(persist_path=persist_path)
        self.neo4j = Neo4jStore()
        self.spillover = SpilloverWriter(spillover_dir or settings.spillover_dir)

        # Cached health status to avoid pinging backends on every call
        self._health_cache = {}
        self._health_cache_time = 0
        self._health_ttl = 60  # seconds

    def status(self) -> dict:
        """Probe all memory backends and return live health info. Cached for 60s."""
        now = time.time()
        if self._health_cache and (now - self._health_cache_time) < self._health_ttl:
            return self._health_cache
        
        info = {
            "status": "online",
            "chroma": "offline",
            "neo4j": "offline"
        }
        
        # ChromaDB check
        try:
            count = self.chroma.count()
            info["chroma"] = f"online ({count} memories)"
        except Exception as e:
            info["chroma"] = f"error ({type(e).__name__})"
            info["status"] = "degraded"
            
        # Neo4j check
        try:
            count = self.neo4j.count_nodes()
            info["neo4j"] = f"online ({count} nodes)"
        except Exception as e:
            info["neo4j"] = f"error ({type(e).__name__})"
            if info["status"] == "online": # only degrade if not already degraded/offline
                 info["status"] = "degraded"
            
        if "online" not in info["chroma"] and "online" not in info["neo4j"]:
            info["status"] = "offline"
        
        self._health_cache = info
        self._health_cache_time = now
        return info

    def _is_chroma_available(self) -> bool:
        """Lightweight check using cached health status."""
        health = self.status()
        return "online" in health.get("chroma", "")

    def _coerce_text(self, value) -> str:
        """Normalize LangChain-style structured content into plain text."""
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            parts = []
            for item in value:
                if isinstance(item, str):
                    parts.append(item)
                    continue
                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str) and text.strip():
                        parts.append(text)
                        continue
                coerced = self._coerce_text(item)
                if coerced.strip():
                    parts.append(coerced)
            return "\n".join(parts).strip()
        if isinstance(value, dict):
            text = value.get("text")
            if isinstance(text, str):
                return text
            return json.dumps(value, ensure_ascii=True, sort_keys=True)
        return str(value)

    def _prepare_chroma_metadata(self, metadata: dict) -> dict:
        """Flatten metadata into Chroma-compatible scalar/list values."""
        safe_metadata = {}
        for key, value in metadata.items():
            if isinstance(value, (str, int, float, bool)) or value is None:
                safe_metadata[key] = value
            elif isinstance(value, list):
                safe_metadata[key] = [
                    item if isinstance(item, (str, int, float, bool)) or item is None
                    else self._coerce_text(item)
                    for item in value
                ]
            else:
                safe_metadata[key] = self._coerce_text(value)
        return safe_metadata

    def store(self, text, role: str, session_id: str,
              is_ephemeral: bool = False, **extra):
        """Store a conversation turn in Chroma. Knowledge extraction is handled
        asynchronously by the analyzer pipeline — rows land here with
        ``analyzed: False`` and the scheduler picks them up on its next tick."""
        metadata = {
            "role": role,
            "session_id": session_id,
            "is_ephemeral": is_ephemeral,
            "analyzed": False,
            **extra,
        }
        normalized_text = self._coerce_text(text)
        if not normalized_text.strip():
            logger.warning("Skipping empty memory write for session %s", session_id)
            return None
        chroma_metadata = self._prepare_chroma_metadata(metadata)

        memory_id = None
        if self._is_chroma_available():
            try:
                memory_id = self.chroma.add_memory(normalized_text, chroma_metadata)
            except Exception as e:
                logger.error("Failed to store memory in Chroma: %s", e)
                self._health_cache_time = 0
                self.spillover.record_chroma_store(
                    text=normalized_text, metadata=chroma_metadata
                )
        else:
            logger.error("ChromaDB is offline; spilling memory to disk for replay.")
            self.spillover.record_chroma_store(
                text=normalized_text, metadata=chroma_metadata
            )

        return memory_id

    def search(self, query: str, k: int = 5, session_id: str | None = None,
                include_ephemeral: bool = True):
        """Semantic search across memories with optional filters."""
        if not self._is_chroma_available():
            logger.warning("ChromaDB is offline, skipping semantic search.")
            return []

        filters = []
        if session_id:
            filters.append({"session_id": session_id})
        if not include_ephemeral:
            filters.append({"is_ephemeral": False})

        if len(filters) == 1:
            where = filters[0]
        elif len(filters) > 1:
            where = {"$and": filters}
        else:
            where = None

        try:
            return self.chroma.query_memory(query, k=k, where=where)
        except Exception as e:
            logger.error("Chroma search failed: %s", e)
            self._health_cache_time = 0
            return []

    def get_history(self, session_id: str, limit: int = 20):
        """Most recent turns for a session, newest-first."""
        if not self._is_chroma_available():
            logger.warning("ChromaDB is offline, cannot retrieve history.")
            return []
            
        try:
            return self.chroma.get_recent(n=limit, session_id=session_id)
        except Exception as e:
            logger.error("Failed to retrieve history from Chroma: %s", e)
            self._health_cache_time = 0
            return []

    def clear_ephemeral(self, session_id: str | None = None):
        """Wipe all ephemeral memories, optionally scoped to one session."""
        if session_id:
            where = {"$and": [
                {"is_ephemeral": True},
                {"session_id": session_id},
            ]}
        else:
            where = {"is_ephemeral": True}
        self.chroma.delete_memories(where=where)

    def delete_session(self, session_id: str):
        """Wipe an entire session from Chroma and Neo4j."""
        chroma_ok = True
        graph_ok = True

        if self._is_chroma_available():
            try:
                self.chroma.delete_memories(where={"session_id": session_id})
            except Exception as e:
                logger.error("Failed to delete Chroma session %s: %s", session_id, e)
                chroma_ok = False
        else:
            logger.error("ChromaDB is offline, cannot delete session.")
            chroma_ok = False

        if self.neo4j.driver or self.neo4j.verify_connection():
            graph_ok = self.neo4j.delete_session_graph(session_id)

        return chroma_ok and graph_ok

    # ── Chroma session listing ────────────────────────────────────────────────

    def list_sessions(self, limit: int = 500) -> dict:
        """Return raw Chroma records for all sessions up to *limit*.

        Returns a dict with keys ``documents`` (list[str]) and ``metadatas``
        (list[dict]) — safe to iterate even when Chroma is offline.
        """
        empty: dict = {"documents": [], "metadatas": []}
        if not self._is_chroma_available():
            return empty
        try:
            result = self.chroma.collection.get(limit=limit)
            return {
                "documents": result.get("documents") or [],
                "metadatas": result.get("metadatas") or [],
            }
        except Exception as e:
            logger.error("Failed to list sessions from Chroma: %s", e)
            self._health_cache_time = 0
            return empty

    # ── Health cache control ──────────────────────────────────────────────────

    def invalidate_health_cache(self) -> None:
        """Force the next ``status()`` call to re-probe backends."""
        self._health_cache_time = 0

    # ── Knowledge graph public queries ────────────────────────────────────────

    def graph_overview(self, limit: int = 100) -> dict:
        """Return node/relationship counts and top labels from Neo4j."""
        return self.neo4j.get_explorer_graph_overview(limit=limit)

    def graph_node_detail(self, node_id: str) -> dict:
        """Return a node's properties and its connections by ID."""
        return self.neo4j.get_node_detail(node_id)

    def graph_node_provenance(self, node_id: str) -> dict:
        """Return the provenance / source chain for a node."""
        return self.neo4j.get_node_provenance(node_id)

    def graph_active_tasks(self) -> list:
        """Return active task nodes from the knowledge graph."""
        return self.neo4j.list_active_tasks()

    def graph_belief_trail(self, belief_id: str) -> dict:
        """Return the belief chain and supporting evidence for a belief node."""
        chain = self.neo4j.get_belief_chain(belief_id)
        evidence = self.neo4j.get_belief_evidence(belief_id)
        return {"chain": chain, "evidence": evidence}

    # ── Analyzer queue (Chroma) ──────────────────────────────────────────────

    def list_unanalyzed(self, limit: int = 50) -> list[dict]:
        """Return the next batch of conversation turns awaiting analysis.

        Filters to ``analyzed: false`` and excludes ephemeral rows.
        """
        if not self._is_chroma_available():
            return []
        where = {"$and": [{"analyzed": False}, {"is_ephemeral": False}]}
        return self.chroma.list_where(where=where, limit=limit)

    def count_unanalyzed(self) -> int:
        """Number of non-ephemeral Chroma rows waiting for the analyzer."""
        if not self._is_chroma_available():
            return 0
        where = {"$and": [{"analyzed": False}, {"is_ephemeral": False}]}
        return self.chroma.count_where(where=where)

    def mark_analyzed(self, memory_ids: list[str], run_id: str | None = None) -> int:
        """Stamp the given Chroma rows so the analyzer doesn't reprocess them."""
        if not memory_ids or not self._is_chroma_available():
            return 0
        patch = {"analyzed": True, "analyzer_status": "success"}
        if run_id:
            patch["analysis_run_id"] = run_id
            patch["analyzed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        return self.chroma.update_metadata(memory_ids, patch)

    def mark_failed(
        self,
        memory_ids: list[str],
        reason: str,
        run_id: str | None = None,
    ) -> int:
        """Mark rows as processed-but-failed so they leave the live queue but
        remain queryable for retry. Used by the analyzer when the LLM returns
        unusable output."""
        if not memory_ids or not self._is_chroma_available():
            return 0
        patch = {
            "analyzed": True,
            "analyzer_status": "failed",
            "analyzer_failure_reason": reason or "unknown",
            "analyzer_failed_at": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
            ),
        }
        if run_id:
            patch["analysis_run_id"] = run_id
        return self.chroma.update_metadata(memory_ids, patch)

    def list_failed(self, limit: int = 50) -> list[dict]:
        """Return Chroma rows the analyzer flagged as failed (dead-letter queue)."""
        if not self._is_chroma_available():
            return []
        where = {"analyzer_status": "failed"}
        return self.chroma.list_where(where=where, limit=limit)

    def count_failed(self) -> int:
        """Number of rows currently in the analyzer dead-letter queue."""
        if not self._is_chroma_available():
            return 0
        return self.chroma.count_where(where={"analyzer_status": "failed"})

    def retry_failed(self, memory_ids: list[str] | None = None) -> int:
        """Reset failed rows so the analyzer picks them up on the next tick.

        With ``memory_ids=None`` retries every failed row. Returns the number
        of rows whose metadata was reset.
        """
        if not self._is_chroma_available():
            return 0
        if memory_ids is None:
            failed = self.list_failed(limit=10_000)
            memory_ids = [row["id"] for row in failed]
        if not memory_ids:
            return 0
        patch = {
            "analyzed": False,
            "analyzer_status": "pending",
            "analyzer_failure_reason": "",
            "analyzer_failed_at": "",
        }
        return self.chroma.update_metadata(memory_ids, patch)

    # ── Analyzer graph writes (Neo4j) ────────────────────────────────────────

    def graph_schema_snapshot(self) -> dict:
        """Snapshot of labels / relationship types / sample entities for prompts."""
        return self.neo4j.get_schema_snapshot()

    def upsert_node(
        self,
        *,
        node_id: str,
        labels: list[str],
        name: str,
        properties: dict | None = None,
    ) -> str:
        """Create-or-update a multi-label node, keyed on stable id.

        On Neo4j connection failure the operation is spilled to disk so it
        can be replayed once the graph backend recovers. Returns ``node_id``
        in that case so callers see a stable identifier.
        """
        try:
            result = self.neo4j.upsert_node_with_labels(
                node_id=node_id, labels=labels, name=name, properties=properties
            )
        except Exception as e:
            logger.error("Neo4j upsert_node raised; spilling: %s", e)
            self.spillover.record_neo4j_node(
                node_id=node_id, labels=labels, name=name, properties=properties
            )
            self._health_cache_time = 0
            return node_id

        if not result:
            logger.warning("Neo4j upsert_node returned empty; spilling for replay.")
            self.spillover.record_neo4j_node(
                node_id=node_id, labels=labels, name=name, properties=properties
            )
            self._health_cache_time = 0
            return node_id
        return result

    def upsert_relationship(
        self,
        *,
        source_id: str,
        target_id: str,
        rel_type: str,
        properties: dict | None = None,
    ) -> bool:
        """MERGE a typed relationship between two existing nodes.

        On Neo4j connection failure the operation is spilled to disk so the
        next replay can reapply it.
        """
        try:
            ok = self.neo4j.upsert_relationship(
                source_id=source_id,
                target_id=target_id,
                rel_type=rel_type,
                properties=properties,
            )
        except Exception as e:
            logger.error("Neo4j upsert_relationship raised; spilling: %s", e)
            self.spillover.record_neo4j_relationship(
                source_id=source_id,
                target_id=target_id,
                rel_type=rel_type,
                properties=properties,
            )
            self._health_cache_time = 0
            return False

        if not ok:
            logger.warning("Neo4j upsert_relationship returned False; spilling for replay.")
            self.spillover.record_neo4j_relationship(
                source_id=source_id,
                target_id=target_id,
                rel_type=rel_type,
                properties=properties,
            )
            self._health_cache_time = 0
        return ok

    # ── Spillover replay ─────────────────────────────────────────────────────

    def replay_spillover(self) -> dict[str, int]:
        """Drain pending spillover writes back into Chroma/Neo4j.

        Designed to be called from the analyzer scheduler tick. Records
        whose target backend is still offline are left on disk for the
        next attempt.
        """
        chroma_apply = self._make_chroma_apply() if self._is_chroma_available() else None
        neo4j_apply = self._make_neo4j_apply() if self.is_graph_online() else None
        return self.spillover.replay(
            chroma_apply=chroma_apply, neo4j_apply=neo4j_apply
        )

    def _make_chroma_apply(self):
        def apply(record: dict) -> bool:
            if record.get("op") != "chroma.store":
                return False
            payload = record.get("payload") or {}
            text = payload.get("text", "")
            metadata = payload.get("metadata") or {}
            if not text:
                return True  # nothing to do; treat as drained
            try:
                self.chroma.add_memory(text, dict(metadata))
                return True
            except Exception as e:
                logger.warning("Chroma replay failed: %s", e)
                return False
        return apply

    def _make_neo4j_apply(self):
        def apply(record: dict) -> bool:
            op = record.get("op")
            payload = record.get("payload") or {}
            try:
                if op == "neo4j.upsert_node":
                    result = self.neo4j.upsert_node_with_labels(
                        node_id=payload["node_id"],
                        labels=payload["labels"],
                        name=payload["name"],
                        properties=payload.get("properties") or {},
                    )
                    return bool(result)
                if op == "neo4j.upsert_relationship":
                    return bool(self.neo4j.upsert_relationship(
                        source_id=payload["source_id"],
                        target_id=payload["target_id"],
                        rel_type=payload["rel_type"],
                        properties=payload.get("properties") or {},
                    ))
            except Exception as e:
                logger.warning("Neo4j replay failed for op=%s: %s", op, e)
                return False
            return False
        return apply

    # ── Bootstrap ────────────────────────────────────────────────────────────

    def user_root_exists(self) -> bool:
        """True if the explorer has been bootstrapped with a `:User` root."""
        return self.neo4j.user_root_exists()

    def get_user_root(self) -> dict | None:
        """Return the seeded `:User` root node, or None if not yet bootstrapped."""
        return self.neo4j.get_user_root()

    def bootstrap_user_root(self, name: str) -> dict:
        """Hard-wipe the graph and seed a `:Person:User` root.

        Chroma is not touched — historical conversations remain queued for the
        analyzer to re-process against the freshly-seeded graph.
        """
        return self.neo4j.bootstrap_user_root(name)

    # ── Rumination support ────────────────────────────────────────────────────

    def get_recent_memories(self, n: int = 100) -> list[dict]:
        """Most recent *n* Chroma entries across all sessions, newest-first."""
        if not self._is_chroma_available():
            return []
        try:
            return self.chroma.get_recent(n=n)
        except Exception as e:
            logger.error("Failed to get recent memories: %s", e)
            return []

    def get_unanalyzed_beliefs(self, limit: int = 10) -> list[dict]:
        """Return Belief nodes from Neo4j that haven't been deep-analyzed yet."""
        if not self.neo4j.driver:
            return []
        query = """
        MATCH (b:Belief)
        WHERE b.deep_analyzed IS NULL OR b.deep_analyzed = false
        RETURN b.id AS id, b.content AS content, b.confidence AS confidence
        LIMIT $limit
        """
        try:
            records, _, _ = self.neo4j.driver.execute_query(query, limit=limit)
            return [
                {"id": r["id"], "content": r["content"], "confidence": r["confidence"]}
                for r in records
            ]
        except Exception as e:
            logger.error("Failed to fetch unanalyzed beliefs: %s", e)
            return []

    def mark_belief_deep_analyzed(self, belief_id: str) -> None:
        """Stamp a Belief node so the deep-pass engine doesn't reprocess it."""
        if not self.neo4j.driver:
            return
        query = """
        MATCH (b:Belief {id: $id})
        SET b.deep_analyzed = true, b.last_deep_analyzed = $now
        """
        try:
            self.neo4j.driver.execute_query(
                query, id=belief_id,
                now=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            )
        except Exception as e:
            logger.error("Failed to mark belief %s as deep-analyzed: %s", belief_id, e)

    def upsert_belief(
        self,
        content: str,
        confidence: float = 0.8,
        *,
        about_entity_id: str | None = None,
        source_text: str | None = None,
    ) -> str:
        """Create a Belief node, optionally linked to an entity and source text."""
        try:
            return self.neo4j.upsert_belief(
                content,
                confidence,
                about_entity_id=about_entity_id,
                source_text=source_text,
            )
        except Exception as e:
            logger.error("Failed to upsert belief: %s", e)
            return ""

    def is_graph_online(self) -> bool:
        """True if Neo4j is reachable (uses the 60s cached health status)."""
        return "online" in self.status().get("neo4j", "")

    def find_entity(self, name: str) -> str | None:
        """Return the id of the first node whose name contains *name*, or None."""
        results = self.search_nodes(name, limit=1)
        return results[0]["id"] if results else None

    def find_belief(self, keyword: str, *, active_only: bool = False) -> dict | None:
        """Return the most recent Belief whose content contains *keyword*, or None."""
        if not self.neo4j.driver:
            return None
        status_clause = "AND b.status = 'active'" if active_only else ""
        cypher = f"""
        MATCH (b:Belief)
        WHERE toLower(b.content) CONTAINS toLower($keyword) {status_clause}
        RETURN b.id AS id, b.content AS content,
               b.confidence AS confidence, b.status AS status
        ORDER BY b.created_at DESC LIMIT 1
        """
        try:
            records, _, _ = self.neo4j.driver.execute_query(cypher, keyword=keyword)
            if not records:
                return None
            r = records[0]
            return {
                "id": r["id"],
                "content": r["content"],
                "confidence": r["confidence"],
                "status": r["status"],
            }
        except Exception as e:
            logger.error("Failed to find belief for keyword '%s': %s", keyword, e)
            return None

    def evolve_belief(self, old_id: str, new_content: str, reason: str = "") -> str:
        """Supersede an existing Belief and return the new belief's id."""
        try:
            return self.neo4j.evolve_belief(old_id, new_content, reason=reason)
        except Exception as e:
            logger.error("Failed to evolve belief %s: %s", old_id, e)
            return ""

    def search_nodes(self, query: str, limit: int = 10) -> list[dict]:
        """Name-contains search across all graph nodes."""
        if not self.neo4j.driver:
            return []
        cypher = """
        MATCH (n)
        WHERE toLower(n.name) CONTAINS toLower($query)
        RETURN n.id AS id, n.name AS name,
               labels(n)[0] AS label, n.description AS description
        LIMIT $limit
        """
        try:
            records, _, _ = self.neo4j.driver.execute_query(cypher, query=query, limit=limit)
            return [
                {
                    "id": r["id"],
                    "name": r["name"],
                    "label": r["label"],
                    "description": r["description"],
                }
                for r in records
            ]
        except Exception as e:
            logger.error("Node search failed for query '%s': %s", query, e)
            return []

    def update_task(
        self, title_fragment: str, new_status: str = "", notes: str = ""
    ) -> str:
        """Update a Task node matched by a title fragment. Returns a status string."""
        if not self.neo4j.driver:
            return "Graph is offline."
        set_parts = ["t.updated_at = $now"]
        params: dict = {
            "title": title_fragment,
            "now": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        if new_status:
            set_parts.append("t.status = $status")
            params["status"] = new_status.upper()
        if notes:
            set_parts.append("t.notes = $notes")
            params["notes"] = notes
        cypher = f"""
        MATCH (t:Task)
        WHERE toLower(t.name) CONTAINS toLower($title)
        SET {", ".join(set_parts)}
        RETURN t.name AS name, t.status AS status
        LIMIT 1
        """
        try:
            records, _, _ = self.neo4j.driver.execute_query(cypher, **params)
            if records:
                return f"Updated '{records[0]['name']}' → {records[0]['status']}"
            return f"No task found matching '{title_fragment}'"
        except Exception as e:
            logger.error("Failed to update task '%s': %s", title_fragment, e)
            return f"Error: {e}"


_instance: MemoryManager | None = None


def get_memory_manager() -> MemoryManager:
    """Return the shared MemoryManager, creating it on first call."""
    global _instance
    if _instance is None:
        _instance = MemoryManager()
    return _instance
