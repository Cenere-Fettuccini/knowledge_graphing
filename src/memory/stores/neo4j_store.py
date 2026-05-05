"""Neo4j knowledge graph — entities, beliefs, provenance, tasks."""

import uuid
import logging
from neo4j import GraphDatabase

from src.core.config import settings

logger = logging.getLogger(__name__)


class Neo4jStore:
    """Interface to the Neo4j Knowledge Graph."""

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
            self.driver = GraphDatabase.driver(self._uri, auth=(self._user, self._password))
            self.driver.verify_connectivity()
            return True
        except Exception as e:
            logger.error("Failed to connect to Neo4j at %s: %s", self._uri, e)
            self.driver = None
            return False

    def close(self):
        if self.driver:
            self.driver.close()

    # ── Write Operations ──────────────────────────────────────────────────────

    def add_node(self, label: str, name: str, properties: dict = None) -> str:
        """Create or update a node. Returns its unique ID."""
        if not self.driver:
            return ""
            
        props = properties or {}
        node_id = props.get("id", str(uuid.uuid4()))
        props["id"] = node_id
        props["name"] = name
        
        query = f"""
        MERGE (n:{label} {{id: $node_id}})
        ON CREATE SET n += $props, n.name = $name
        ON MATCH SET n += $props, n.name = $name
        RETURN n.id AS id
        """
        
        with self.driver.session() as session:
            result = session.run(query, node_id=node_id, name=name, props=props)
            record = result.single()
            return record["id"] if record else node_id

    def add_edge(self, source_id: str, target_id: str, rel_type: str, properties: dict = None) -> None:
        """Create a relationship between two existing nodes by their IDs."""
        if not self.driver:
            return
            
        props = properties or {}
        # Ensure relation type is upper case and valid syntax
        rel_type = rel_type.upper().replace(" ", "_")
        
        query = f"""
        MATCH (a {{id: $source_id}})
        MATCH (b {{id: $target_id}})
        MERGE (a)-[r:{rel_type}]->(b)
        ON CREATE SET r += $props
        ON MATCH SET r += $props
        """
        
        with self.driver.session() as session:
            session.run(query, source_id=source_id, target_id=target_id, props=props)

    # ── Read Operations (Explorer API format) ──────────────────────────────────

    def get_graph_overview(self, limit: int = 100) -> dict:
        """Returns nodes and edges formatted for the 3D Explorer."""
        if not self.driver and not self.verify_connection():
            return {"nodes": [], "edges": [], "stats": {"nodes": 0, "edges": 0}}
            
        query = """
        MATCH (n)
        OPTIONAL MATCH (n)-[r]->(m)
        RETURN n, r, m
        LIMIT $limit
        """
        
        nodes_dict = {}
        edges = []
        
        with self.driver.session() as session:
            result = session.run(query, limit=limit)
            for record in result:
                n = record["n"]
                if n and n.get("id") not in nodes_dict:
                    # Extract the first label
                    label = list(n.labels)[0] if n.labels else "Unknown"
                    nodes_dict[n.get("id")] = {
                        "id": n.get("id"),
                        "label": label,
                        "name": n.get("name", "Unnamed"),
                        **{k: v for k, v in n.items() if k not in ["id", "name"]}
                    }
                
                r = record["r"]
                m = record["m"]
                if r is not None and m is not None:
                    # Ensure m is also recorded
                    if m.get("id") not in nodes_dict:
                        label = list(m.labels)[0] if m.labels else "Unknown"
                        nodes_dict[m.get("id")] = {
                            "id": m.get("id"),
                            "label": label,
                            "name": m.get("name", "Unnamed"),
                            **{k: v for k, v in m.items() if k not in ["id", "name"]}
                        }
                        
                    edges.append({
                        "source": n.get("id"),
                        "target": m.get("id"),
                        "type": r.type
                    })
                    
        # Deduplicate edges just in case
        unique_edges = [dict(t) for t in {tuple(d.items()) for d in edges}]

        return {
            "nodes": list(nodes_dict.values()),
            "edges": unique_edges,
            "stats": {
                "nodes": len(nodes_dict),
                "edges": len(unique_edges),
            }
        }

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

    def upsert_belief(
        self,
        content: str,
        confidence: float = 0.8,
        about_entity_id: str = None,
        source_session_id: str = None,
        source_text: str = None,
    ) -> str:
        """
        Create a new :Belief node with optional evidence links.

        If about_entity_id is provided, creates an ABOUT relationship.
        If source_session_id is provided, creates a :Conversation node
        and an EXTRACTED_FROM relationship.

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
            confidence: $conf, status: 'active', created_at: $now
        })
        RETURN b.id AS id
        """
        with self.driver.session() as session:
            session.run(cypher, bid=belief_id, content=content, conf=confidence, now=now)

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

        return belief_id

    def evolve_belief(
        self,
        old_belief_id: str,
        new_content: str,
        new_confidence: float = 0.8,
        reason: str = "",
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
            confidence: $conf, status: 'active', created_at: $now
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
                reason=reason, now=now,
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

    def get_belief_chain(self, belief_id: str) -> list:
        """
        Walk the EVOLVED_FROM chain for a belief.
        Returns a list from newest to oldest: [current, predecessor, ...]
        """
        if not self.driver:
            return []

        cypher = """
        MATCH path = (b:Belief {id: $bid})-[:EVOLVED_FROM*0..20]->(ancestor:Belief)
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
