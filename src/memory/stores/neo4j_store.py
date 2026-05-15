"""Neo4j knowledge graph — entities, beliefs, provenance, tasks."""

import math
import uuid
import logging
import re
from datetime import datetime, timedelta, timezone
from neo4j import GraphDatabase

from src.core.config import settings

logger = logging.getLogger(__name__)


def _vector_norm(v: list[float]) -> float:
    return math.sqrt(sum(x * x for x in v))


def _cosine_similarity(
    a: list[float], b: list[float], *, norm_a: float | None = None
) -> float:
    if not a or not b:
        return 0.0
    norm_a = norm_a if norm_a is not None else _vector_norm(a)
    norm_b = _vector_norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (norm_a * norm_b)


class Neo4jStore:
    """Interface to the Neo4j Knowledge Graph."""

    EXPLORER_HIDDEN_LABELS = {"Conversation", "Note", "Thought"}
    EXPLORER_ROOT_LABELS = {"User", "Person", "Belief", "Task", "Project", "Entity"}
    USER_ROOT_LABELS = ("Person", "User")
    TEST_ID_PREFIXES = ("test_", "test-", "src_", "tgt_", "upd_", "topic_")
    TEST_SESSION_PREFIXES = ("test_", "test-", "session_", "pytest_")

    def __init__(self, uri=None, user=None, password=None):
        self._uri = uri or settings.neo4j_uri
        self._user = user or settings.neo4j_user
        self._password = password or settings.neo4j_password
        self.driver = None
        self.verify_connection()

    def verify_connection(self) -> bool:
        """Attempt to reconnect if driver is missing or disconnected."""
        if self.driver:
            try:
                self.driver.verify_connectivity()
                return True
            except Exception:
                logger.warning("Neo4j driver lost connectivity. Attempting reset.")
                self.driver.close()
                self.driver = None

        try:
            self.driver = GraphDatabase.driver(
                self._uri,
                auth=(self._user, self._password),
                notifications_disabled_categories=["UNRECOGNIZED"],
            )
            self.driver.verify_connectivity()
            return True
        except Exception as e:
            logger.error("Failed to connect to Neo4j at %s: %s", self._uri, e)
            self.driver = None
            return False

    def close(self):
        if self.driver:
            self.driver.close()

    @staticmethod
    def _slugify(value: str) -> str:
        value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
        return value or "general"

    @staticmethod
    def sanitize_label(label: str) -> str:
        """Coerce a free-form label into a Cypher-safe PascalCase identifier.

        Cypher treats ``SET n:Academic Goal`` as two tokens and aborts with a
        SyntaxError. Labels arrive straight from LLM output, so we tolerate
        ``"Academic Goal"``, ``"social-circles"``, ``"  career goal  "`` and
        produce a single identifier that compiles.
        """
        if not label or not isinstance(label, str):
            return "Entity"
        tokens = re.findall(r"[A-Za-z0-9]+", label)
        if not tokens:
            return "Entity"
        parts = [t[:1].upper() + t[1:].lower() for t in tokens]
        cleaned = re.sub(r"^[0-9]+", "", "".join(parts))
        return cleaned or "Entity"

    @classmethod
    def sanitize_labels(cls, labels: list[str]) -> list[str]:
        """Sanitize and de-duplicate a list of labels, preserving order."""
        seen: set[str] = set()
        out: list[str] = []
        for raw in labels or []:
            clean = cls.sanitize_label(raw)
            if clean and clean not in seen:
                seen.add(clean)
                out.append(clean)
        return out or ["Entity"]

    # ── Write Operations ──────────────────────────────────────────────────────

    def upsert_conversation(self, session_id: str, properties: dict = None) -> str:
        """Create or update a conversation node keyed by session_id."""
        if not self.driver:
            return ""

        props = properties or {}
        conversation_id = props.get("id", str(uuid.uuid4()))
        name = props.get("name", f"Conversation {session_id[:8]}")
        query = """
        MERGE (c:Conversation {session_id: $session_id})
        ON CREATE SET c.id = $conversation_id
        SET c.name = $name, c += $props
        RETURN c.id AS id
        """

        with self.driver.session() as session:
            record = session.run(
                query,
                session_id=session_id,
                conversation_id=conversation_id,
                name=name,
                props={**props, "session_id": session_id},
            ).single()
            return record["id"] if record else conversation_id

    @staticmethod
    def _pick_primary_label(labels: list[str]) -> str:
        if not labels:
            return "Unknown"
        # Prefer the user's root label so the centring/coloring code lights up
        # on the right node when a multi-label root (Person:User) is present.
        for preferred in ("User", "Person"):
            if preferred in labels:
                return preferred
        return labels[0]

    def _serialize_node(self, node) -> dict:
        labels = list(node.labels) if node.labels else []
        primary = self._pick_primary_label(labels)
        return {
            "id": node.get("id"),
            "label": primary,
            "labels": labels or [primary],
            "name": node.get("name", "Unnamed"),
            **{k: v for k, v in node.items() if k not in ["id", "name"]},
        }

    # ── Schema snapshot ───────────────────────────────────────────────────────

    def get_schema_snapshot(self, sample_entities: int = 25) -> dict:
        """Return labels, relationship types, and a sample of named entities.

        Fed into the analyzer's prompt so the LLM prefers reusing what's
        already in the graph instead of inventing parallel labels.
        """
        if not self.driver and not self.verify_connection():
            return {"labels": [], "relationship_types": [], "entities": []}

        with self.driver.session() as session:
            labels = [r["label"] for r in session.run("CALL db.labels() YIELD label RETURN label ORDER BY label")]
            rels = [r["rel"] for r in session.run("CALL db.relationshipTypes() YIELD relationshipType AS rel RETURN rel ORDER BY rel")]
            entities = []
            for record in session.run(
                """
                MATCH (n)
                WHERE n.name IS NOT NULL
                RETURN n.id AS id, n.name AS name, labels(n) AS labels
                ORDER BY coalesce(n.updated_at, n.created_at, n.name) DESC
                LIMIT $sample
                """,
                sample=sample_entities,
            ):
                entities.append(
                    {"id": record["id"], "name": record["name"], "labels": list(record["labels"] or [])}
                )

        return {"labels": labels, "relationship_types": rels, "entities": entities}

    # ── Multi-label upsert (used by the analyzer) ────────────────────────────

    @classmethod
    def _build_node_upsert_cypher(cls, labels: list[str]) -> str:
        if not labels:
            raise ValueError("At least one label is required.")
        # Labels are interpolated straight into Cypher, so anything other than
        # ``[A-Za-z][A-Za-z0-9]*`` either fails to parse (spaces, punctuation)
        # or opens an injection surface (semicolons, backticks).
        safe_labels = cls.sanitize_labels(labels)
        labels_clause = ":".join(safe_labels)
        return f"""
        MERGE (n {{id: $node_id}})
        ON CREATE SET n:{labels_clause}, n.created_at = $now
        SET n:{labels_clause}, n += $props, n.updated_at = $now
        RETURN n.id AS id
        """

    @staticmethod
    def _build_relationship_upsert_cypher(rel_type: str) -> tuple[str, str]:
        clean_type = re.sub(r"[^A-Z0-9_]", "_", (rel_type or "RELATED_TO").upper())
        if not clean_type:
            clean_type = "RELATED_TO"
        cypher = f"""
        MATCH (a {{id: $source_id}})
        MATCH (b {{id: $target_id}})
        MERGE (a)-[r:{clean_type}]->(b)
        ON CREATE SET r += $props, r.created_at = $now
        SET r += $props, r.updated_at = $now
        RETURN r
        """
        return clean_type, cypher

    def upsert_node_with_labels(
        self,
        *,
        node_id: str,
        labels: list[str],
        name: str,
        properties: dict | None = None,
    ) -> str:
        """Create-or-update a node with one or more labels, keyed on ``node_id``.

        If the node already exists (matched by id), additional labels are
        merged in via ``SET n:Label`` so the analyzer can layer new labels
        onto existing entities without recreating them.
        """
        if not self.driver and not self.verify_connection():
            return ""
        if not node_id:
            raise ValueError("node_id is required.")

        props = dict(properties or {})
        props["id"] = node_id
        props["name"] = name
        cypher = self._build_node_upsert_cypher(labels)
        now = datetime.now(timezone.utc).isoformat()
        with self.driver.session() as session:
            record = session.run(cypher, node_id=node_id, now=now, props=props).single()
            return record["id"] if record else node_id

    def upsert_relationship(
        self,
        *,
        source_id: str,
        target_id: str,
        rel_type: str,
        properties: dict | None = None,
    ) -> bool:
        """MERGE a relationship by (source, target, type). Returns True on success."""
        if not self.driver and not self.verify_connection():
            return False
        _, cypher = self._build_relationship_upsert_cypher(rel_type)
        props = dict(properties or {})
        now = datetime.now(timezone.utc).isoformat()
        with self.driver.session() as session:
            result = session.run(
                cypher,
                source_id=source_id,
                target_id=target_id,
                now=now,
                props=props,
            ).single()
            return result is not None

    def execute_batch(self, ops: list[tuple[str, dict]]) -> None:
        """Apply a list of ``(op_type, kwargs)`` writes in a single transaction.

        ``op_type`` is ``"node"`` (kwargs match :meth:`upsert_node_with_labels`)
        or ``"edge"`` (kwargs match :meth:`upsert_relationship`). Any failure
        rolls back the entire batch — the caller decides what to do with the
        unwritten ops (typically: spill them to disk and retry on the next
        scheduler tick).

        Raises if the driver is unreachable or any cypher fails.
        """
        if not ops:
            return
        if not self.driver and not self.verify_connection():
            raise RuntimeError("Neo4j unavailable")
        now = datetime.now(timezone.utc).isoformat()
        with self.driver.session() as session:
            with session.begin_transaction() as tx:
                for op_type, kwargs in ops:
                    if op_type == "node":
                        self._exec_node_in_tx(tx, kwargs, now)
                    elif op_type == "edge":
                        self._exec_edge_in_tx(tx, kwargs, now)
                    else:
                        raise ValueError(f"Unknown batch op type: {op_type!r}")
                tx.commit()

    def _exec_node_in_tx(self, tx, kwargs: dict, now: str) -> None:
        node_id = kwargs.get("node_id")
        if not node_id:
            raise ValueError("node_id is required.")
        cypher = self._build_node_upsert_cypher(kwargs.get("labels") or [])
        props = dict(kwargs.get("properties") or {})
        props["id"] = node_id
        props["name"] = kwargs.get("name", "")
        tx.run(cypher, node_id=node_id, now=now, props=props)

    def _exec_edge_in_tx(self, tx, kwargs: dict, now: str) -> None:
        _, cypher = self._build_relationship_upsert_cypher(kwargs.get("rel_type", ""))
        props = dict(kwargs.get("properties") or {})
        tx.run(
            cypher,
            source_id=kwargs.get("source_id", ""),
            target_id=kwargs.get("target_id", ""),
            now=now,
            props=props,
        )

    # ── User root / bootstrap ─────────────────────────────────────────────────

    def user_root_exists(self) -> bool:
        """True if a `:User` root node has been seeded."""
        if not self.driver and not self.verify_connection():
            return False
        cypher = "MATCH (u:User {is_root: true}) RETURN count(u) > 0 AS exists"
        with self.driver.session() as session:
            record = session.run(cypher).single()
            return bool(record and record["exists"])

    def get_user_root(self) -> dict | None:
        """Return the `:User` root node, or None if not yet bootstrapped."""
        if not self.driver and not self.verify_connection():
            return None
        cypher = "MATCH (u:User {is_root: true}) RETURN u LIMIT 1"
        with self.driver.session() as session:
            record = session.run(cypher).single()
            if not record or record["u"] is None:
                return None
            return self._serialize_node(record["u"])

    def bootstrap_user_root(self, name: str) -> dict:
        """Hard-wipe the graph and seed a single `:Person:User` root node."""
        if not self.driver and not self.verify_connection():
            raise RuntimeError("Neo4j is offline; cannot bootstrap user root.")

        clean_name = (name or "").strip()
        if not clean_name:
            raise ValueError("name must be a non-empty string")

        slug = self._slugify(clean_name)
        node_id = f"user:{slug}"
        now = datetime.now(timezone.utc).isoformat()
        labels_clause = ":".join(self.USER_ROOT_LABELS)

        wipe = "MATCH (n) DETACH DELETE n"
        seed = f"""
        CREATE (u:{labels_clause} {{
            id: $node_id,
            name: $name,
            slug: $slug,
            is_root: true,
            created_at: $now,
            updated_at: $now
        }})
        RETURN u
        """

        with self.driver.session() as session:
            session.run(wipe)
            record = session.run(seed, node_id=node_id, name=clean_name, slug=slug, now=now).single()
            return self._serialize_node(record["u"])

    # ── Pending belief queue (S4.1) ──────────────────────────────────────────

    REJECTED_TTL_DAYS = 30
    PERMANENT_REJECTION_THRESHOLD = 3
    # Cosine threshold for considering two rejections to be "the same idea"
    # when counting toward the permanent-rejection promotion. Matches
    # BeliefCanonicalizer's belief threshold so the two systems agree.
    REJECTION_SIMILARITY_THRESHOLD = 0.88

    def create_pending_belief(
        self,
        *,
        content: str,
        about_entity_id: str | None = None,
        source: str = "rumination",
        confidence: float = 0.6,
    ) -> dict:
        """Insert a :PendingBelief awaiting human approval."""
        if not self.driver and not self.verify_connection():
            raise RuntimeError("Neo4j offline; can't create pending belief.")
        now = datetime.now(timezone.utc).isoformat()
        belief_id = f"pending:{uuid.uuid4().hex[:12]}"
        with self.driver.session() as session:
            session.run(
                """
                CREATE (b:PendingBelief {
                    id: $id, content: $content, name: $content,
                    confidence: $conf, status: 'pending',
                    source: $source, created_at: $now, updated_at: $now
                })
                """,
                id=belief_id, content=content, conf=confidence,
                source=source, now=now,
            )
            if about_entity_id:
                session.run(
                    """
                    MATCH (b:PendingBelief {id: $bid}), (e {id: $eid})
                    MERGE (b)-[:ABOUT]->(e)
                    """,
                    bid=belief_id, eid=about_entity_id,
                )
            else:
                # Anchor to root so the reachability sweep doesn't quarantine it.
                session.run(
                    """
                    MATCH (b:PendingBelief {id: $bid}), (root:Person:User {is_root: true})
                    MERGE (b)-[:ABOUT]->(root)
                    """,
                    bid=belief_id,
                )
            rec = session.run(
                "MATCH (b:PendingBelief {id: $id}) RETURN b", id=belief_id
            ).single()
            return self._serialize_node(rec["b"]) if rec else {}

    def list_pending_beliefs(self, *, limit: int = 50) -> list[dict]:
        if not self.driver and not self.verify_connection():
            return []
        with self.driver.session() as session:
            return [
                self._serialize_node(r["b"])
                for r in session.run(
                    """
                    MATCH (b:PendingBelief {status: 'pending'})
                    WHERE NOT b:Quarantine
                    RETURN b ORDER BY b.created_at DESC LIMIT $limit
                    """,
                    limit=limit,
                )
            ]

    def approve_pending_belief(self, belief_id: str) -> dict:
        """Promote :PendingBelief -> :Belief with status='active'."""
        if not self.driver and not self.verify_connection():
            return {}
        now = datetime.now(timezone.utc).isoformat()
        with self.driver.session() as session:
            rec = session.run(
                """
                MATCH (b:PendingBelief {id: $id})
                REMOVE b:PendingBelief
                SET b:Belief, b.status = 'active', b.approved_at = $now, b.updated_at = $now
                RETURN b
                """,
                id=belief_id, now=now,
            ).single()
            return self._serialize_node(rec["b"]) if rec else {}

    def edit_pending_belief(self, belief_id: str, *, new_content: str) -> dict:
        """Edit content then promote to :Belief, recording an edit log entry."""
        if not self.driver and not self.verify_connection():
            return {}
        now = datetime.now(timezone.utc).isoformat()
        with self.driver.session() as session:
            rec = session.run(
                """
                MATCH (b:PendingBelief {id: $id})
                REMOVE b:PendingBelief
                SET b:Belief,
                    b.original_content = b.content,
                    b.content = $new_content,
                    b.name = $new_content,
                    b.status = 'active',
                    b.edited_at = $now,
                    b.approved_at = $now,
                    b.updated_at = $now
                RETURN b
                """,
                id=belief_id, new_content=new_content, now=now,
            ).single()
            return self._serialize_node(rec["b"]) if rec else {}

    def reject_pending_belief(
        self,
        belief_id: str,
        *,
        reason: str = "",
        content_embedding: list[float] | None = None,
    ) -> dict:
        """Demote :PendingBelief -> :RejectedHypothesis with a 30-day TTL.

        Counts prior rejections of the *same idea* within the TTL window. If
        an ``content_embedding`` is provided, the count is fuzzy — any prior
        rejection whose stored embedding has cosine similarity above
        ``REJECTION_SIMILARITY_THRESHOLD`` counts. With no embedding the count
        falls back to exact-string match (the pre-CT10 behaviour). Once the
        count crosses ``PERMANENT_REJECTION_THRESHOLD`` the new rejection is
        promoted to a permanent :RejectedBelief.
        """
        if not self.driver and not self.verify_connection():
            return {}
        now = datetime.now(timezone.utc)
        ttl_iso = (now + timedelta(days=self.REJECTED_TTL_DAYS)).isoformat()
        window_start_iso = (now - timedelta(days=self.REJECTED_TTL_DAYS)).isoformat()
        now_iso = now.isoformat()

        with self.driver.session() as session:
            content_row = session.run(
                "MATCH (b:PendingBelief {id: $id}) RETURN b.content AS c", id=belief_id
            ).single()
            if not content_row:
                return {}
            content = content_row["c"] or ""

            recent_count = self._count_similar_rejections(
                session,
                content=content,
                content_embedding=content_embedding,
                window_start_iso=window_start_iso,
            )

            if recent_count + 1 >= self.PERMANENT_REJECTION_THRESHOLD:
                rec = session.run(
                    """
                    MATCH (b:PendingBelief {id: $id})
                    REMOVE b:PendingBelief
                    SET b:RejectedBelief,
                        b.status = 'rejected_permanent',
                        b.rejection_reason = $reason,
                        b.rejected_at = $now,
                        b.updated_at = $now,
                        b.rejection_count = $count,
                        b.content_embedding = coalesce($embedding, b.content_embedding)
                    RETURN b
                    """,
                    id=belief_id, reason=reason, now=now_iso,
                    count=recent_count + 1, embedding=content_embedding,
                ).single()
            else:
                rec = session.run(
                    """
                    MATCH (b:PendingBelief {id: $id})
                    REMOVE b:PendingBelief
                    SET b:RejectedHypothesis,
                        b.status = 'rejected',
                        b.rejection_reason = $reason,
                        b.rejected_at = $now,
                        b.expires_at = $expires,
                        b.updated_at = $now,
                        b.content_embedding = coalesce($embedding, b.content_embedding)
                    RETURN b
                    """,
                    id=belief_id, reason=reason, now=now_iso, expires=ttl_iso,
                    embedding=content_embedding,
                ).single()
            return self._serialize_node(rec["b"]) if rec else {}

    def _count_similar_rejections(
        self,
        session,
        *,
        content: str,
        content_embedding: list[float] | None,
        window_start_iso: str,
    ) -> int:
        """Count :RejectedHypothesis nodes within the window matching the new content.

        If an embedding is supplied, uses cosine similarity against each
        stored embedding (threshold ``REJECTION_SIMILARITY_THRESHOLD``).
        Falls back to exact-string match when the embedding is missing or
        when no prior rejection in the window has a stored embedding to
        compare against.
        """
        if not content_embedding:
            row = session.run(
                """
                MATCH (h:RejectedHypothesis)
                WHERE h.content = $content AND h.rejected_at >= $window_start
                RETURN count(h) AS c
                """,
                content=content, window_start=window_start_iso,
            ).single()
            return int(row["c"]) if row else 0

        records = session.run(
            """
            MATCH (h:RejectedHypothesis)
            WHERE h.rejected_at >= $window_start
            RETURN h.content AS content, h.content_embedding AS embedding
            """,
            window_start=window_start_iso,
        )
        new_norm = _vector_norm(content_embedding)
        count = 0
        for r in records:
            other_embedding = r.get("embedding") if hasattr(r, "get") else r["embedding"]
            other_content = r["content"] or ""
            if other_embedding:
                sim = _cosine_similarity(
                    content_embedding, list(other_embedding), norm_a=new_norm
                )
                if sim >= self.REJECTION_SIMILARITY_THRESHOLD:
                    count += 1
            elif other_content == content:
                # No stored embedding (pre-CT10 rejection) — fall back to
                # exact match so old data still aggregates.
                count += 1
        return count

    def purge_expired_rejections(self) -> int:
        """DETACH DELETE :RejectedHypothesis whose expires_at is past."""
        if not self.driver and not self.verify_connection():
            return 0
        now_iso = datetime.now(timezone.utc).isoformat()
        with self.driver.session() as session:
            rec = session.run(
                """
                MATCH (h:RejectedHypothesis)
                WHERE h.expires_at < $now
                WITH collect(h) AS doomed
                FOREACH (x IN doomed | DETACH DELETE x)
                RETURN size(doomed) AS deleted
                """,
                now=now_iso,
            ).single()
            return int(rec["deleted"]) if rec else 0

    def list_active_rejections(self, *, limit: int = 100) -> list[dict]:
        """Active :RejectedHypothesis nodes (for the rumination engine's negative set)."""
        if not self.driver and not self.verify_connection():
            return []
        now_iso = datetime.now(timezone.utc).isoformat()
        with self.driver.session() as session:
            return [
                self._serialize_node(r["h"])
                for r in session.run(
                    """
                    MATCH (h:RejectedHypothesis)
                    WHERE h.expires_at >= $now
                    RETURN h ORDER BY h.rejected_at DESC LIMIT $limit
                    """,
                    now=now_iso, limit=limit,
                )
            ]

    # ── Focal-node neighborhood (S4.5) ───────────────────────────────────────

    def get_neighborhood(
        self, node_id: str, *, depth: int = 1, limit: int = 200,
    ) -> dict:
        """Variable-length neighborhood around ``node_id``.

        Returns ``{focal, nodes, edges, stats}`` in the same shape as
        ``get_explorer_graph_overview`` so the frontend can swap the
        renderer's data source without touching the layout code.
        """
        if not self.driver and not self.verify_connection():
            return {"focal": None, "nodes": [], "edges": [], "stats": {"nodes": 0, "edges": 0}}
        depth = max(1, min(int(depth), 4))  # clamp — deeper paths cost a lot
        cypher = f"""
        MATCH (focal {{id: $node_id}})
        WHERE NOT focal:Quarantine
        OPTIONAL MATCH (focal)-[r*1..{depth}]-(neighbor)
        WHERE neighbor IS NULL OR (
            NOT neighbor:Quarantine
            AND NOT any(label IN labels(neighbor) WHERE label IN $hidden_labels)
        )
        WITH focal, collect(DISTINCT neighbor) AS neighbors, collect(r) AS rel_paths
        RETURN focal,
               [n IN neighbors WHERE n IS NOT NULL][..$limit] AS neighbors,
               [path IN rel_paths | [rel IN path | {{
                   source: startNode(rel).id,
                   target: endNode(rel).id,
                   type: type(rel)
               }}]] AS edge_paths
        """
        nodes_dict = {}
        edges: list[dict] = []
        with self.driver.session() as session:
            rec = session.run(
                cypher,
                node_id=node_id, limit=limit,
                hidden_labels=list(self.EXPLORER_HIDDEN_LABELS),
            ).single()
            if rec is None or rec["focal"] is None:
                return {"focal": None, "nodes": [], "edges": [], "stats": {"nodes": 0, "edges": 0}}
            focal_data = self._serialize_node(rec["focal"])
            nodes_dict[focal_data["id"]] = focal_data
            for neighbor in rec["neighbors"] or []:
                if neighbor is None:
                    continue
                nd = self._serialize_node(neighbor)
                if not self._looks_like_test_artifact(nd):
                    nodes_dict[nd["id"]] = nd
            for path in rec["edge_paths"] or []:
                for rel in path or []:
                    if rel and rel.get("source") and rel.get("target") and rel.get("type"):
                        edges.append(dict(rel))

        # Dedupe edges by (source, target, type)
        unique_edges = list({(e["source"], e["target"], e["type"]): e for e in edges}.values())
        # Drop edges referencing nodes we filtered out
        visible_ids = set(nodes_dict)
        unique_edges = [e for e in unique_edges if e["source"] in visible_ids and e["target"] in visible_ids]

        return {
            "focal": focal_data,
            "nodes": list(nodes_dict.values()),
            "edges": unique_edges,
            "stats": {"nodes": len(nodes_dict), "edges": len(unique_edges), "depth": depth},
        }

    # ── Era windowing (S4.6) ─────────────────────────────────────────────────

    def eras_active_at(self, iso_date: str) -> list[dict]:
        """Eras whose [start_date, end_date] window contains ``iso_date``.

        end_date null is treated as "ongoing" (no upper bound).
        start_date null is treated as "unknown start" (no lower bound).
        """
        if not self.driver and not self.verify_connection():
            return []
        cypher = """
        MATCH (e:Era)
        WHERE NOT e:Quarantine
          AND (e.start_date IS NULL OR e.start_date <= $d)
          AND (e.end_date IS NULL OR e.end_date >= $d)
        RETURN e ORDER BY coalesce(e.start_date, '0000-00-00') DESC
        """
        with self.driver.session() as session:
            return [self._serialize_node(r["e"]) for r in session.run(cypher, d=iso_date)]

    # ── Contradictions (S4.3) ────────────────────────────────────────────────

    def link_contradiction(
        self, belief_a_id: str, belief_b_id: str,
        *, reason: str = "", similarity: float = 0.0, run_id: str | None = None,
    ) -> bool:
        if not self.driver and not self.verify_connection():
            return False
        if belief_a_id == belief_b_id:
            return False
        now_iso = datetime.now(timezone.utc).isoformat()
        with self.driver.session() as session:
            rec = session.run(
                """
                MATCH (a:Belief {id: $a}), (b:Belief {id: $b})
                MERGE (a)-[r:CONTRADICTS]->(b)
                ON CREATE SET r.detected_at = $now,
                              r.reason = $reason,
                              r.similarity = $sim,
                              r.run_id = $run_id
                RETURN count(r) AS linked
                """,
                a=belief_a_id, b=belief_b_id, now=now_iso,
                reason=reason, sim=similarity, run_id=run_id,
            ).single()
            return bool(rec and rec["linked"] > 0)

    def list_contradictions(self, *, limit: int = 50) -> list[dict]:
        if not self.driver and not self.verify_connection():
            return []
        cypher = """
        MATCH (a:Belief)-[r:CONTRADICTS]->(b:Belief)
        WHERE NOT a:Quarantine AND NOT b:Quarantine
        RETURN a.id AS a_id, a.content AS a_content,
               b.id AS b_id, b.content AS b_content,
               r.reason AS reason, r.similarity AS similarity,
               r.detected_at AS detected_at
        ORDER BY r.detected_at DESC
        LIMIT $limit
        """
        with self.driver.session() as session:
            return [dict(r) for r in session.run(cypher, limit=limit)]

    # ── Belief calibration (CT3) ─────────────────────────────────────────────

    def belief_calibration(self) -> list[dict]:
        """Approve/reject breakdown per pending-belief source.

        Returns one row per ``source`` value seen in the pending-belief
        pipeline, with counts for each terminal state plus an
        ``approval_rate`` that excludes still-pending items (so a fresh
        source isn't penalised for having items in flight).

        Used by the explorer's calibration panel + future model-routing
        decisions ("rumination is approved 12% of the time, maybe ease
        off the rabbit-hole pass").
        """
        if not self.driver and not self.verify_connection():
            return []
        cypher = """
        MATCH (b)
        WHERE NOT b:Quarantine
          AND (b:PendingBelief OR b:Belief OR b:RejectedHypothesis OR b:RejectedBelief)
          AND b.source IS NOT NULL
        RETURN b.source AS source,
               sum(CASE WHEN b:PendingBelief THEN 1 ELSE 0 END) AS pending,
               sum(CASE WHEN b:Belief AND b.approved_at IS NOT NULL THEN 1 ELSE 0 END) AS approved,
               sum(CASE WHEN b:RejectedHypothesis THEN 1 ELSE 0 END) AS rejected_ttl,
               sum(CASE WHEN b:RejectedBelief THEN 1 ELSE 0 END) AS rejected_permanent
        ORDER BY source
        """
        with self.driver.session() as session:
            out = []
            for r in session.run(cypher):
                approved = int(r["approved"])
                rej_ttl = int(r["rejected_ttl"])
                rej_perm = int(r["rejected_permanent"])
                decided = approved + rej_ttl + rej_perm
                out.append({
                    "source": r["source"],
                    "pending": int(r["pending"]),
                    "approved": approved,
                    "rejected_ttl": rej_ttl,
                    "rejected_permanent": rej_perm,
                    "decided": decided,
                    "approval_rate": (approved / decided) if decided else None,
                })
            return out

    # ── Schema drift counts (S3.5) ───────────────────────────────────────────

    def label_counts(self) -> dict[str, int]:
        """Return {label: node_count} across the graph, excluding quarantined."""
        if not self.driver and not self.verify_connection():
            return {}
        cypher = """
        MATCH (n)
        WHERE NOT n:Quarantine
        UNWIND labels(n) AS label
        RETURN label, count(*) AS c
        """
        with self.driver.session() as session:
            return {r["label"]: int(r["c"]) for r in session.run(cypher)}

    def rel_type_counts(self) -> dict[str, int]:
        """Return {rel_type: edge_count} across the graph."""
        if not self.driver and not self.verify_connection():
            return {}
        cypher = """
        MATCH ()-[r]->()
        RETURN type(r) AS rel_type, count(*) AS c
        """
        with self.driver.session() as session:
            return {r["rel_type"]: int(r["c"]) for r in session.run(cypher)}

    # ── Eras (S3.1) ──────────────────────────────────────────────────────────

    def list_eras(self, *, active_only: bool = False) -> list[dict]:
        if not self.driver and not self.verify_connection():
            return []
        clauses = ["NOT e:Quarantine"]
        if active_only:
            clauses.append("e.end_date IS NULL")
        cypher = f"""
        MATCH (e:Era)
        WHERE {" AND ".join(clauses)}
        RETURN e
        ORDER BY coalesce(e.start_date, e.created_at) DESC
        """
        with self.driver.session() as session:
            return [self._serialize_node(r["e"]) for r in session.run(cypher)]

    def get_era(self, era_id: str) -> dict | None:
        if not self.driver and not self.verify_connection():
            return None
        with self.driver.session() as session:
            rec = session.run(
                "MATCH (e:Era {id: $id}) RETURN e LIMIT 1", id=era_id
            ).single()
            return self._serialize_node(rec["e"]) if rec and rec["e"] is not None else None

    def upsert_era(
        self,
        *,
        era_id: str | None = None,
        name: str,
        description: str = "",
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict:
        if not self.driver and not self.verify_connection():
            raise RuntimeError("Neo4j is offline; cannot upsert era.")
        clean_name = (name or "").strip()
        if not clean_name:
            raise ValueError("Era name must be non-empty.")
        node_id = era_id or f"era:{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()
        with self.driver.session() as session:
            rec = session.run(
                """
                MERGE (e:Era {id: $id})
                ON CREATE SET e.created_at = $now
                SET e.name = $name,
                    e.description = $description,
                    e.start_date = $start_date,
                    e.end_date = $end_date,
                    e.updated_at = $now
                WITH e
                MATCH (root:Person:User {is_root: true})
                MERGE (root)-[:HAS_ERA]->(e)
                RETURN e
                """,
                id=node_id, now=now, name=clean_name, description=description,
                start_date=start_date, end_date=end_date,
            ).single()
            return self._serialize_node(rec["e"]) if rec else {}

    def delete_era(self, era_id: str) -> bool:
        if not self.driver and not self.verify_connection():
            return False
        with self.driver.session() as session:
            rec = session.run(
                """
                MATCH (e:Era {id: $id})
                DETACH DELETE e
                RETURN count(*) AS removed
                """,
                id=era_id,
            ).single()
            return bool(rec and rec["removed"] > 0)

    def bind_node_to_era(self, node_id: str, era_id: str) -> bool:
        if not self.driver and not self.verify_connection():
            return False
        with self.driver.session() as session:
            rec = session.run(
                """
                MATCH (n {id: $node_id}), (e:Era {id: $era_id})
                MERGE (n)-[r:OCCURRED_IN]->(e)
                RETURN count(r) AS linked
                """,
                node_id=node_id, era_id=era_id,
            ).single()
            return bool(rec and rec["linked"] > 0)

    def unbind_node_from_era(self, node_id: str, era_id: str) -> bool:
        if not self.driver and not self.verify_connection():
            return False
        with self.driver.session() as session:
            rec = session.run(
                """
                MATCH (n {id: $node_id})-[r:OCCURRED_IN]->(e:Era {id: $era_id})
                DELETE r
                RETURN count(r) AS removed
                """,
                node_id=node_id, era_id=era_id,
            ).single()
            return bool(rec and rec["removed"] > 0)

    def _looks_like_test_artifact(self, node_data: dict) -> bool:
        node_id = str(node_data.get("id") or "").lower()
        label = str(node_data.get("label") or "")
        return label == "TestNode" or any(node_id.startswith(prefix) for prefix in self.TEST_ID_PREFIXES)

    def get_explorer_graph_overview(
        self,
        limit: int = 100,
        *,
        era_id: str | None = None,
        active_self_only: bool = False,
    ) -> dict:
        """Return a curated graph centered on beliefs, tasks, projects, and linked entities.

        S3.2: optional era scoping. ``era_id`` restricts to nodes bound to
        that specific era via OCCURRED_IN. ``active_self_only`` restricts
        to nodes bound to any era whose ``end_date`` is null or in the
        future — the "what's live right now" view. The two filters are
        OR'd at the node level (a node visible in either filter is kept).
        """
        if not self.driver and not self.verify_connection():
            return {"nodes": [], "edges": [], "stats": {"nodes": 0, "edges": 0}}

        era_clauses = ["NOT root:Quarantine"]
        params: dict = {
            "limit": limit,
            "root_labels": list(self.EXPLORER_ROOT_LABELS),
            "hidden_labels": list(self.EXPLORER_HIDDEN_LABELS),
        }
        if era_id:
            era_clauses.append(
                "EXISTS { MATCH (root)-[:OCCURRED_IN]->(:Era {id: $era_id}) }"
            )
            params["era_id"] = era_id
        elif active_self_only:
            era_clauses.append(
                "EXISTS { MATCH (root)-[:OCCURRED_IN]->(e:Era) "
                "WHERE e.end_date IS NULL OR e.end_date >= $today }"
            )
            params["today"] = datetime.now(timezone.utc).date().isoformat()
        era_filter = " AND ".join(era_clauses)

        query = f"""
        MATCH (root)
        WHERE any(label IN labels(root) WHERE label IN $root_labels)
          AND {era_filter}
        WITH root
        ORDER BY coalesce(root.updated_at, root.created_at, root.last_updated_at, root.name) DESC
        LIMIT $limit
        OPTIONAL MATCH (root)-[r]-(neighbor)
        WHERE neighbor IS NULL OR NOT any(label IN labels(neighbor) WHERE label IN $hidden_labels)
        RETURN root, neighbor,
               type(r) AS rel_type,
               startNode(r).id AS source_id,
               endNode(r).id AS target_id
        """

        nodes_dict = {}
        edges = []

        with self.driver.session() as session:
            result = session.run(query, **params)
            for record in result:
                root = record["root"]
                if root is not None:
                    node_data = self._serialize_node(root)
                    if not self._looks_like_test_artifact(node_data):
                        nodes_dict[node_data["id"]] = node_data

                neighbor = record["neighbor"]
                if neighbor is not None:
                    node_data = self._serialize_node(neighbor)
                    if not self._looks_like_test_artifact(node_data):
                        nodes_dict[node_data["id"]] = node_data

                source_id = record["source_id"]
                target_id = record["target_id"]
                rel_type = record["rel_type"]
                if source_id and target_id and rel_type:
                    edges.append({
                        "source": source_id,
                        "target": target_id,
                        "type": rel_type,
                    })

        visible_ids = set(nodes_dict)
        unique_edges = [
            dict(t)
            for t in {
                tuple(d.items()) for d in edges
                if d["source"] in visible_ids and d["target"] in visible_ids
            }
        ]

        connected_ids = set()
        for edge in unique_edges:
            connected_ids.add(edge["source"])
            connected_ids.add(edge["target"])

        if connected_ids:
            nodes = [node for node_id, node in nodes_dict.items() if node_id in connected_ids]
        else:
            nodes = [
                node for node in nodes_dict.values()
                if node["label"] in self.EXPLORER_ROOT_LABELS
            ]

        visible_ids = {node["id"] for node in nodes}
        unique_edges = [
            edge for edge in unique_edges
            if edge["source"] in visible_ids and edge["target"] in visible_ids
        ]

        return {
            "nodes": nodes,
            "edges": unique_edges,
            "stats": {
                "nodes": len(nodes),
                "edges": len(unique_edges),
            }
        }

    TERMINAL_TASK_STATUSES = ("DONE", "CANCELLED")

    def list_active_tasks(
        self,
        *,
        include_completed: bool = False,
        since: str | None = None,
    ) -> list[dict]:
        """Return task nodes from the knowledge graph.

        By default, terminal tasks (``DONE``, ``CANCELLED``) are hidden so
        the agent and explorer see a live punch-list. Pass
        ``include_completed=True`` for the scrollback view; combine with
        ``since`` (ISO timestamp) to limit how far back the read goes.
        """
        if not self.driver and not self.verify_connection():
            return []

        clauses = ["NOT t:Quarantine"]
        params: dict = {"terminal": list(self.TERMINAL_TASK_STATUSES)}
        if not include_completed:
            clauses.append("(t.status IS NULL OR NOT t.status IN $terminal)")
        if since:
            clauses.append(
                "coalesce(t.completed_at, t.updated_at, t.created_at) >= $since"
            )
            params["since"] = since
        where_clause = " AND ".join(clauses)

        query = f"""
        MATCH (t:Task)
        WHERE {where_clause}
        RETURN t.id AS id, t.name AS name, t.status AS status,
               t.priority AS priority, t.due_date AS due_date,
               t.completed_at AS completed_at
        ORDER BY coalesce(t.completed_at, t.updated_at, t.created_at, t.name) DESC
        """

        tasks = []
        with self.driver.session() as session:
            for record in session.run(query, **params):
                tasks.append({
                    "id": record["id"],
                    "name": record["name"],
                    "status": record["status"],
                    "priority": record["priority"],
                    "due_date": record["due_date"],
                    "completed_at": record["completed_at"],
                    "label": "Task",
                })
        return tasks

    def delete_session_graph(self, session_id: str) -> bool:
        """Delete a conversation session and its turn nodes from Neo4j."""
        if not self.driver and not self.verify_connection():
            return False

        query = """
        MATCH (c:Conversation {session_id: $session_id})
        OPTIONAL MATCH (c)-[:HAS_TURN]->(t)
        DETACH DELETE c, t
        """
        try:
            with self.driver.session() as session:
                session.run(query, session_id=session_id)
            return True
        except Exception as e:
            logger.error("Failed to delete Neo4j session %s: %s", session_id, e)
            return False

    def cleanup_test_artifacts(self) -> int:
        """Delete graph data that matches our pytest/test naming conventions."""
        if not self.driver and not self.verify_connection():
            return 0

        query = """
        MATCH (n)
        WHERE
            (
                n.id IS NOT NULL AND (
                    any(prefix IN $id_prefixes WHERE toLower(n.id) STARTS WITH prefix)
                    OR (
                        any(prefix IN $session_prefixes WHERE toLower(n.id) STARTS WITH prefix)
                        AND any(label IN labels(n) WHERE label IN ['Conversation', 'Note', 'Thought'])
                    )
                )
            )
            OR (
                n.session_id IS NOT NULL
                AND any(prefix IN $session_prefixes WHERE toLower(n.session_id) STARTS WITH prefix)
            )
            OR any(label IN labels(n) WHERE label IN ['TestNode'])
        WITH collect(DISTINCT n) AS doomed
        FOREACH (node IN doomed | DETACH DELETE node)
        RETURN size(doomed) AS deleted_count
        """

        try:
            with self.driver.session() as session:
                record = session.run(
                    query,
                    id_prefixes=[prefix.lower() for prefix in self.TEST_ID_PREFIXES],
                    session_prefixes=[prefix.lower() for prefix in self.TEST_SESSION_PREFIXES],
                ).single()
            return int(record["deleted_count"]) if record else 0
        except Exception as e:
            logger.error("Failed to clean Neo4j test artifacts: %s", e)
            return 0

    def get_node_detail(self, node_id: str) -> dict:
        """Returns details for a specific node and its immediate connections."""
        if not self.driver:
            return {"node": None, "connections": []}
            
        query = """
        MATCH (n {id: $node_id})
        OPTIONAL MATCH (n)-[out_r]->(out_m)
        OPTIONAL MATCH (in_m)-[in_r]->(n)
        RETURN n, collect(DISTINCT {rel: out_r, target: out_m, dir: 'out'}) AS outgoing,
                  collect(DISTINCT {rel: in_r, target: in_m, dir: 'in'}) AS incoming
        """
        
        with self.driver.session() as session:
            result = session.run(query, node_id=node_id)
            record = result.single()
            
            if not record or not record["n"]:
                return {"node": None, "connections": []}
                
            n = record["n"]
            node_data = {
                "id": n.get("id"),
                "label": list(n.labels)[0] if n.labels else "Unknown",
                "name": n.get("name", "Unnamed"),
                **{k: v for k, v in n.items() if k not in ["id", "name"]}
            }
            
            connections = []
            
            for out_conn in record["outgoing"]:
                if out_conn["rel"] is not None and out_conn["target"] is not None:
                    target_n = out_conn["target"]
                    connections.append({
                        "id": target_n.get("id"),
                        "target": target_n.get("name", "Unnamed"),
                        "target_label": list(target_n.labels)[0] if target_n.labels else "Unknown",
                        "type": out_conn["rel"].type,
                        "direction": "out"
                    })
                    
            for in_conn in record["incoming"]:
                if in_conn["rel"] is not None and in_conn["target"] is not None:
                    source_n = in_conn["target"]
                    connections.append({
                        "id": source_n.get("id"),
                        "target": source_n.get("name", "Unnamed"),
                        "target_label": list(source_n.labels)[0] if source_n.labels else "Unknown",
                        "type": in_conn["rel"].type,
                        "direction": "in"
                    })
                    
            return {
                "node": node_data,
                "connections": connections
            }

    # ── Belief Provenance ──────────────────────────────────────────────────────

    def _normalize_relation_entries(self, entries: list[dict], side: str) -> list[dict]:
        normalized = []
        seen = set()
        for entry in entries:
            rel = entry.get("rel")
            node = entry.get("node")
            if rel is None or node is None:
                continue
            node_id = node.get("id")
            if not node_id:
                continue
            key = (node_id, rel.type, side)
            if key in seen:
                continue
            seen.add(key)
            normalized.append({
                "id": node_id,
                "name": node.get("name", "Unnamed"),
                "label": list(node.labels)[0] if node.labels else "Unknown",
                "type": rel.type,
                "direction": side,
                "relationship": dict(rel.items()),
            })
        return normalized

    def _get_conversation_timeline(self, session_id: str) -> list[dict]:
        if not self.driver or not session_id:
            return []

        cypher = """
        MATCH (c:Conversation {session_id: $session_id})-[:HAS_TURN]->(t)
        RETURN t.id AS id, labels(t)[0] AS label, t.name AS name, t.text AS text,
               t.role AS role, t.sequence AS sequence, t.timestamp AS timestamp
        ORDER BY t.sequence ASC, t.timestamp ASC
        """
        timeline = []
        with self.driver.session() as session:
            for record in session.run(cypher, session_id=session_id):
                timeline.append({
                    "id": record["id"],
                    "label": record["label"],
                    "name": record["name"],
                    "text": record["text"],
                    "role": record["role"],
                    "sequence": record["sequence"],
                    "timestamp": record["timestamp"],
                })
        return timeline

    def get_node_provenance(self, node_id: str) -> dict:
        """Return generic provenance for any node plus belief-specific trails."""
        empty = {
            "node": None,
            "incoming": [],
            "outgoing": [],
            "timeline": [],
            "chain": [],
            "evidence": {"supports": [], "weakens": []},
        }
        if not self.driver:
            return empty

        query = """
        MATCH (n {id: $node_id})
        OPTIONAL MATCH (src)-[in_r]->(n)
        OPTIONAL MATCH (n)-[out_r]->(dst)
        RETURN n,
               collect(DISTINCT {rel: in_r, node: src}) AS incoming,
               collect(DISTINCT {rel: out_r, node: dst}) AS outgoing
        """

        with self.driver.session() as session:
            record = session.run(query, node_id=node_id).single()

        if not record or not record["n"]:
            return empty

        node = record["n"]
        node_data = {
            "id": node.get("id"),
            "label": list(node.labels)[0] if node.labels else "Unknown",
            "name": node.get("name", "Unnamed"),
            **{k: v for k, v in node.items() if k not in ["id", "name"]},
        }
        session_id = node_data.get("session_id")

        return {
            "node": node_data,
            "incoming": self._normalize_relation_entries(record["incoming"], "in"),
            "outgoing": self._normalize_relation_entries(record["outgoing"], "out"),
            "timeline": self._get_conversation_timeline(session_id),
            "chain": self.get_belief_chain(node_id) if node_data["label"] == "Belief" else [],
            "evidence": self.get_belief_evidence(node_id) if node_data["label"] == "Belief" else {
                "supports": [],
                "weakens": [],
            },
        }

    def upsert_belief(
        self,
        content: str,
        confidence: float = 0.8,
        about_entity_id: str = None,
        source_session_id: str = None,
        source_text: str = None,
        belief_key: str | None = None,
        extraction_method: str | None = None,
        derived_from_belief_id: str | None = None,
    ) -> str:
        """
        Create a new :Belief node with optional evidence links.

        Provenance options:
          * ``about_entity_id`` — writes ``(b)-[:ABOUT]->(entity)``.
          * ``source_session_id`` + ``source_text`` — MERGEs a
            ``:Conversation`` node and writes ``(b)-[:EXTRACTED_FROM]->(c)``.
          * ``derived_from_belief_id`` — writes
            ``(b)-[:DEDUCED_FROM]->(seed:Belief)`` (used by rumination's
            deep pass to record which prior belief the synthesis came from).
          * ``extraction_method`` — stamped as a property on the new node
            so consumers can tell ``deep_pass`` / ``rabbit_hole`` /
            cloud-extracted beliefs apart from agent-written ones.

        Returns the belief's ID.
        """
        if not self.driver:
            return ""

        from datetime import datetime, timezone
        belief_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        cypher = """
        CREATE (b:Belief {
            id: $bid, name: $content, content: $content,
            confidence: $conf, status: 'active', created_at: $now,
            updated_at: $now, belief_key: $belief_key,
            extraction_method: $method
        })
        RETURN b.id AS id
        """
        with self.driver.session() as session:
            session.run(
                cypher,
                bid=belief_id,
                content=content,
                conf=confidence,
                now=now,
                belief_key=belief_key,
                method=extraction_method,
            )

            # Link to the entity it's about
            if about_entity_id:
                session.run("""
                    MATCH (b:Belief {id: $bid}), (e {id: $eid})
                    MERGE (b)-[:ABOUT]->(e)
                """, bid=belief_id, eid=about_entity_id)

            # Create a Conversation node and EXTRACTED_FROM link
            if source_session_id and source_text:
                conv_id = str(uuid.uuid4())
                session.run("""
                    MERGE (c:Conversation {session_id: $sid})
                    ON CREATE SET c.id = $cid, c.name = $preview,
                                  c.text = $text, c.created_at = $now
                    WITH c
                    MATCH (b:Belief {id: $bid})
                    MERGE (b)-[:EXTRACTED_FROM {session_id: $sid}]->(c)
                """, sid=source_session_id, cid=conv_id,
                     preview=source_text[:60] + "…" if len(source_text) > 60 else source_text,
                     text=source_text, now=now, bid=belief_id)

            # CT2: deep-pass synthesis links back to the seed belief so the
            # explorer's provenance view can show "this came from that".
            if derived_from_belief_id:
                session.run("""
                    MATCH (new:Belief {id: $bid}), (seed:Belief {id: $seed})
                    MERGE (new)-[r:DEDUCED_FROM]->(seed)
                    ON CREATE SET r.method = $method, r.created_at = $now
                """, bid=belief_id, seed=derived_from_belief_id,
                     method=extraction_method or "rumination", now=now)

        return belief_id

    def _find_active_belief(self, belief_key: str) -> dict | None:
        if not self.driver or not belief_key:
            return None

        cypher = """
        MATCH (b:Belief {belief_key: $belief_key, status: 'active'})
        OPTIONAL MATCH (b)-[:ABOUT]->(e)
        RETURN b.id AS id, b.content AS content, e.id AS entity_id
        ORDER BY b.created_at DESC
        LIMIT 1
        """
        with self.driver.session() as session:
            record = session.run(cypher, belief_key=belief_key).single()
            return dict(record) if record else None

    def evolve_belief(
        self,
        old_belief_id: str,
        new_content: str,
        new_confidence: float = 0.8,
        reason: str = "",
        belief_key: str | None = None,
    ) -> str:
        """
        Create a new belief that supersedes an old one.

        Sets old belief status to 'superseded', creates a new 'active' belief,
        and links them via EVOLVED_FROM. Returns the new belief's ID.
        """
        if not self.driver:
            return ""

        from datetime import datetime, timezone
        new_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        cypher = """
        MATCH (old:Belief {id: $old_id})
        SET old.status = 'superseded', old.superseded_at = $now

        CREATE (new:Belief {
            id: $new_id, name: $content, content: $content,
            confidence: $conf, status: 'active', created_at: $now,
            updated_at: $now, belief_key: coalesce($belief_key, old.belief_key)
        })
        CREATE (new)-[:EVOLVED_FROM {reason: $reason, timestamp: $now}]->(old)

        WITH old, new
        OPTIONAL MATCH (old)-[:ABOUT]->(e)
        FOREACH (_ IN CASE WHEN e IS NOT NULL THEN [1] ELSE [] END |
            MERGE (new)-[:ABOUT]->(e)
        )

        RETURN new.id AS id
        """
        with self.driver.session() as session:
            result = session.run(
                cypher, old_id=old_belief_id, new_id=new_id,
                content=new_content, conf=new_confidence,
                reason=reason, now=now, belief_key=belief_key,
            )
            record = result.single()
            return record["id"] if record else new_id

    def add_belief_evidence(
        self,
        belief_id: str,
        evidence_type: str,
        session_id: str,
        text: str,
    ) -> None:
        """
        Add a SUPPORTED_BY or WEAKENED_BY link from a belief to a conversation.

        evidence_type: 'supports' or 'weakens'
        """
        if not self.driver:
            return

        from datetime import datetime, timezone
        rel = "SUPPORTED_BY" if evidence_type == "supports" else "WEAKENED_BY"
        now = datetime.now(timezone.utc).isoformat()
        conv_id = str(uuid.uuid4())

        cypher = f"""
        MERGE (c:Conversation {{session_id: $sid}})
        ON CREATE SET c.id = $cid, c.name = $preview, c.text = $text, c.created_at = $now
        WITH c
        MATCH (b:Belief {{id: $bid}})
        MERGE (b)-[:{rel} {{timestamp: $now}}]->(c)
        """
        with self.driver.session() as session:
            session.run(
                cypher, sid=session_id, cid=conv_id,
                preview=text[:60] + "…" if len(text) > 60 else text,
                text=text, now=now, bid=belief_id,
            )

        # Recalculate confidence
        self._recalc_belief_confidence(belief_id)

    def _recalc_belief_confidence(self, belief_id: str) -> None:
        """Recalculate a belief's confidence based on its evidence edges."""
        if not self.driver:
            return

        cypher = """
        MATCH (b:Belief {id: $bid})
        OPTIONAL MATCH (b)-[:SUPPORTED_BY]->(s)
        OPTIONAL MATCH (b)-[:WEAKENED_BY]->(w)
        WITH b, count(DISTINCT s) AS supports, count(DISTINCT w) AS weakens
        SET b.confidence = CASE
            WHEN supports + weakens = 0 THEN b.confidence
            ELSE toFloat(supports) / (supports + weakens)
        END
        """
        with self.driver.session() as session:
            session.run(cypher, bid=belief_id)

    BELIEF_CHAIN_MAX_DEPTH = 20

    def get_belief_chain(self, belief_id: str, *, max_depth: int | None = None) -> list:
        """Walk the EVOLVED_FROM chain for a belief.

        Returns a list from newest to oldest: [current, predecessor, ...].

        Depth is bounded so Neo4j can't fall into a pathological traversal
        if a `:Belief` chain ever forms a cycle (shouldn't happen, but
        EVOLVED_FROM is set by an LLM-driven tool and we don't want a bad
        write to take the query down). ``max_depth`` overrides the class
        default; values are clamped to a sane upper bound (200).
        """
        if not self.driver:
            return []

        depth = self.BELIEF_CHAIN_MAX_DEPTH if max_depth is None else max(1, min(int(max_depth), 200))

        cypher = f"""
        MATCH path = (b:Belief {{id: $bid}})-[:EVOLVED_FROM*0..{depth}]->(ancestor:Belief)
        UNWIND nodes(path) AS node
        WITH DISTINCT node
        RETURN node.id AS id, node.content AS content,
               node.confidence AS confidence, node.status AS status,
               node.created_at AS created_at
        ORDER BY node.created_at DESC
        """
        results = []
        with self.driver.session() as session:
            records = session.run(cypher, bid=belief_id)
            for r in records:
                results.append({
                    "id": r["id"], "content": r["content"],
                    "confidence": r["confidence"], "status": r["status"],
                    "created_at": r["created_at"],
                })
        return results

    def get_belief_evidence(self, belief_id: str) -> dict:
        """
        Return all evidence conversations for a belief,
        grouped by type (supports / weakens).
        """
        if not self.driver:
            return {"supports": [], "weakens": []}

        cypher = """
        MATCH (b:Belief {id: $bid})
        OPTIONAL MATCH (b)-[s:SUPPORTED_BY]->(sc:Conversation)
        OPTIONAL MATCH (b)-[w:WEAKENED_BY]->(wc:Conversation)
        RETURN collect(DISTINCT {
                   id: sc.id, session_id: sc.session_id,
                   text: sc.text, timestamp: s.timestamp
               }) AS supports,
               collect(DISTINCT {
                   id: wc.id, session_id: wc.session_id,
                   text: wc.text, timestamp: w.timestamp
               }) AS weakens
        """
        with self.driver.session() as session:
            record = session.run(cypher, bid=belief_id).single()
            if not record:
                return {"supports": [], "weakens": []}

            # Filter out null entries from optional matches
            supports = [s for s in record["supports"] if s.get("id")]
            weakens = [w for w in record["weakens"] if w.get("id")]

            return {"supports": supports, "weakens": weakens}

    # ── Utilities ─────────────────────────────────────────────────────────────

    # ── Canonicalization (S2.4) ──────────────────────────────────────────────

    # Internal labels the canonicalizer should never propose merges across.
    # Beliefs get their own pass (S2.5); the rest are scaffolding/system types.
    CANONICALIZATION_HIDDEN_LABELS = frozenset({
        "MergeProposal",
        "Belief",
        "PendingBelief",
        "RejectedHypothesis",
        "RejectedBelief",
        "Era",
    })

    def list_distinct_labels(self) -> list[str]:
        """Return every label currently in the graph, sorted alphabetically."""
        if not self.driver and not self.verify_connection():
            return []
        with self.driver.session() as session:
            return [
                r["label"]
                for r in session.run(
                    "CALL db.labels() YIELD label RETURN label ORDER BY label"
                )
            ]

    def list_named_nodes_by_label(
        self,
        label: str,
        *,
        exclude_roots: bool = True,
    ) -> list[dict]:
        """Return ``[{"id", "name", "created_at"}]`` for nodes carrying ``label``.

        Skips nodes flagged ``is_root: true`` so the user-root never participates
        in canonicalization clustering, and skips nodes without a name (clustering
        them by string similarity is meaningless).
        """
        if not label or not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", label):
            raise ValueError(f"Invalid label: {label!r}")
        if not self.driver and not self.verify_connection():
            return []
        where_clauses = ["n.name IS NOT NULL"]
        if exclude_roots:
            where_clauses.append("coalesce(n.is_root, false) = false")
        where = " AND ".join(where_clauses)
        cypher = (
            f"MATCH (n:{label}) "
            f"WHERE {where} "
            "RETURN n.id AS id, n.name AS name, n.created_at AS created_at"
        )
        with self.driver.session() as session:
            return [
                {"id": r["id"], "name": r["name"], "created_at": r["created_at"]}
                for r in session.run(cypher)
            ]

    def list_active_beliefs(self, limit: int = 1000) -> list[dict]:
        """Return ``[{id, content, confidence, created_at}]`` for active beliefs.

        Used by the belief-dedup pass — superseded beliefs are excluded
        because they're already historical and can't be merged further.
        """
        if not self.driver and not self.verify_connection():
            return []
        cypher = """
        MATCH (b:Belief)
        WHERE coalesce(b.status, 'active') = 'active'
          AND b.content IS NOT NULL
        RETURN b.id AS id,
               b.content AS content,
               b.confidence AS confidence,
               b.created_at AS created_at
        ORDER BY coalesce(b.created_at, '') ASC
        LIMIT $limit
        """
        with self.driver.session() as session:
            return [
                {
                    "id": r["id"],
                    "content": r["content"],
                    "confidence": r["confidence"],
                    "created_at": r["created_at"],
                }
                for r in session.run(cypher, limit=int(limit))
            ]

    def count_node_connections(self, node_ids: list[str]) -> dict[str, int]:
        """Return ``{node_id: degree}`` (in + out) for the given ids."""
        if not node_ids or (not self.driver and not self.verify_connection()):
            return {}
        cypher = (
            "UNWIND $ids AS nid "
            "OPTIONAL MATCH (n {id: nid})-[r]-() "
            "RETURN nid AS id, count(r) AS degree"
        )
        with self.driver.session() as session:
            return {
                r["id"]: int(r["degree"] or 0)
                for r in session.run(cypher, ids=list(node_ids))
            }

    def create_merge_proposal(
        self,
        *,
        proposal_id: str,
        label: str,
        primary_id: str,
        duplicate_ids: list[str],
        scores: list[float],
        canonical_name: str,
    ) -> str:
        """Persist a pending :MergeProposal node. Replaces any existing one with the same id."""
        if not self.driver and not self.verify_connection():
            return ""
        now = datetime.now(timezone.utc).isoformat()
        cypher = """
        MERGE (p:MergeProposal {id: $proposal_id})
        SET p.label = $label,
            p.primary_id = $primary_id,
            p.duplicate_ids = $duplicate_ids,
            p.scores = $scores,
            p.canonical_name = $canonical_name,
            p.status = 'pending',
            p.created_at = coalesce(p.created_at, $now),
            p.updated_at = $now
        RETURN p.id AS id
        """
        with self.driver.session() as session:
            record = session.run(
                cypher,
                proposal_id=proposal_id,
                label=label,
                primary_id=primary_id,
                duplicate_ids=list(duplicate_ids),
                scores=[float(s) for s in scores],
                canonical_name=canonical_name,
                now=now,
            ).single()
            return record["id"] if record else proposal_id

    def list_merge_proposals(
        self,
        *,
        status: str = "pending",
        limit: int = 200,
    ) -> list[dict]:
        """List :MergeProposal nodes filtered by status (default: pending)."""
        if not self.driver and not self.verify_connection():
            return []
        cypher = """
        MATCH (p:MergeProposal {status: $status})
        OPTIONAL MATCH (primary {id: p.primary_id})
        RETURN p, primary.name AS primary_name
        ORDER BY coalesce(p.created_at, p.updated_at, '') DESC
        LIMIT $limit
        """
        proposals = []
        with self.driver.session() as session:
            for record in session.run(cypher, status=status, limit=int(limit)):
                node = record["p"]
                proposals.append({
                    "id": node.get("id"),
                    "label": node.get("label"),
                    "primary_id": node.get("primary_id"),
                    "primary_name": record["primary_name"] or node.get("canonical_name"),
                    "duplicate_ids": list(node.get("duplicate_ids") or []),
                    "scores": list(node.get("scores") or []),
                    "canonical_name": node.get("canonical_name"),
                    "status": node.get("status"),
                    "created_at": node.get("created_at"),
                    "updated_at": node.get("updated_at"),
                })
        return proposals

    def get_merge_proposal(self, proposal_id: str) -> dict | None:
        """Fetch a single :MergeProposal by id."""
        if not self.driver and not self.verify_connection():
            return None
        cypher = "MATCH (p:MergeProposal {id: $id}) RETURN p"
        with self.driver.session() as session:
            record = session.run(cypher, id=proposal_id).single()
            if not record:
                return None
            node = record["p"]
            return {
                "id": node.get("id"),
                "label": node.get("label"),
                "primary_id": node.get("primary_id"),
                "duplicate_ids": list(node.get("duplicate_ids") or []),
                "scores": list(node.get("scores") or []),
                "canonical_name": node.get("canonical_name"),
                "status": node.get("status"),
                "created_at": node.get("created_at"),
                "updated_at": node.get("updated_at"),
            }

    def dismiss_merge_proposal(self, proposal_id: str) -> bool:
        """Flip a pending proposal to ``status: dismissed`` (no graph changes)."""
        if not self.driver and not self.verify_connection():
            return False
        now = datetime.now(timezone.utc).isoformat()
        cypher = """
        MATCH (p:MergeProposal {id: $id})
        WHERE p.status = 'pending'
        SET p.status = 'dismissed', p.updated_at = $now
        RETURN p.id AS id
        """
        with self.driver.session() as session:
            record = session.run(cypher, id=proposal_id, now=now).single()
            return record is not None

    def apply_merge_proposal(self, proposal_id: str) -> dict:
        """Merge duplicate nodes into the primary and mark the proposal applied.

        Returns ``{"merged": int, "skipped": int, "rels_rewired": int}``.
        All work runs in a single transaction; any failure rolls everything
        back (including the status flip) so an interrupted merge leaves the
        graph untouched.
        """
        if not self.driver and not self.verify_connection():
            raise RuntimeError("Neo4j unavailable")
        proposal = self.get_merge_proposal(proposal_id)
        if not proposal:
            raise ValueError(f"Unknown merge proposal: {proposal_id}")
        if proposal["status"] != "pending":
            raise ValueError(
                f"Merge proposal {proposal_id} is already {proposal['status']!r}"
            )

        primary_id = proposal["primary_id"]
        duplicate_ids = [d for d in proposal["duplicate_ids"] if d and d != primary_id]
        if not duplicate_ids:
            return {"merged": 0, "skipped": 0, "rels_rewired": 0}

        stats = {"merged": 0, "skipped": 0, "rels_rewired": 0}
        now = datetime.now(timezone.utc).isoformat()
        with self.driver.session() as session:
            with session.begin_transaction() as tx:
                primary = tx.run(
                    "MATCH (n {id: $id}) RETURN n", id=primary_id
                ).single()
                if primary is None:
                    raise ValueError(f"Primary node {primary_id} not found")

                for dup_id in duplicate_ids:
                    dup_record = tx.run(
                        "MATCH (n {id: $id}) RETURN n", id=dup_id
                    ).single()
                    if dup_record is None:
                        stats["skipped"] += 1
                        continue

                    rels_in = tx.run(
                        "MATCH (src)-[r]->(dup {id: $id}) "
                        "RETURN DISTINCT type(r) AS t",
                        id=dup_id,
                    )
                    in_types = [r["t"] for r in rels_in]
                    rels_out = tx.run(
                        "MATCH (dup {id: $id})-[r]->(tgt) "
                        "RETURN DISTINCT type(r) AS t",
                        id=dup_id,
                    )
                    out_types = [r["t"] for r in rels_out]

                    for rel_type in in_types:
                        clean = re.sub(r"[^A-Z0-9_]", "_", rel_type.upper())
                        if not clean:
                            continue
                        rewire_in = f"""
                        MATCH (src)-[r:{clean}]->(dup {{id: $dup_id}})
                        WHERE src.id <> $primary_id
                        MATCH (primary {{id: $primary_id}})
                        MERGE (src)-[new_r:{clean}]->(primary)
                          ON CREATE SET new_r = properties(r), new_r.created_at = $now
                          ON MATCH  SET new_r += properties(r), new_r.updated_at = $now
                        DELETE r
                        RETURN count(new_r) AS c
                        """
                        rec = tx.run(
                            rewire_in,
                            dup_id=dup_id,
                            primary_id=primary_id,
                            now=now,
                        ).single()
                        stats["rels_rewired"] += int(rec["c"]) if rec else 0

                    for rel_type in out_types:
                        clean = re.sub(r"[^A-Z0-9_]", "_", rel_type.upper())
                        if not clean:
                            continue
                        rewire_out = f"""
                        MATCH (dup {{id: $dup_id}})-[r:{clean}]->(tgt)
                        WHERE tgt.id <> $primary_id
                        MATCH (primary {{id: $primary_id}})
                        MERGE (primary)-[new_r:{clean}]->(tgt)
                          ON CREATE SET new_r = properties(r), new_r.created_at = $now
                          ON MATCH  SET new_r += properties(r), new_r.updated_at = $now
                        DELETE r
                        RETURN count(new_r) AS c
                        """
                        rec = tx.run(
                            rewire_out,
                            dup_id=dup_id,
                            primary_id=primary_id,
                            now=now,
                        ).single()
                        stats["rels_rewired"] += int(rec["c"]) if rec else 0

                    # Capture the duplicate's name as an alternate so search and
                    # provenance can still find the merged entity by either alias.
                    tx.run(
                        """
                        MATCH (primary {id: $primary_id})
                        MATCH (dup {id: $dup_id})
                        WITH primary, dup,
                             coalesce(primary.alternate_names, []) AS aliases,
                             dup.name AS dup_name
                        SET primary.alternate_names =
                            CASE WHEN dup_name IN aliases OR dup_name IS NULL
                                 THEN aliases
                                 ELSE aliases + dup_name END,
                            primary.canonicalized_at = $now
                        DETACH DELETE dup
                        """,
                        primary_id=primary_id,
                        dup_id=dup_id,
                        now=now,
                    )
                    stats["merged"] += 1

                tx.run(
                    """
                    MATCH (p:MergeProposal {id: $id})
                    SET p.status = 'applied',
                        p.applied_at = $now,
                        p.updated_at = $now
                    """,
                    id=proposal_id,
                    now=now,
                )
                tx.commit()

        return stats

    def count_nodes(self) -> int:
        """Quick check of database size for status reporting."""
        if not self.driver and not self.verify_connection():
            raise ConnectionError("Neo4j driver not connected and could not reconnect")
            
        with self.driver.session() as session:
            result = session.run("MATCH (n) RETURN count(n) AS c")
            record = result.single()
            return record["c"] if record else 0

    def clear_database(self) -> None:
        """DANGER: Wipes the entire database. Used for tests."""
        if not self.driver:
            return
        with self.driver.session() as session:
            session.run("MATCH (n) DETACH DELETE n")
