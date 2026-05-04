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
        
        try:
            self.driver = GraphDatabase.driver(self._uri, auth=(self._user, self._password))
            self.driver.verify_connectivity()
        except Exception as e:
            logger.error("Failed to connect to Neo4j at %s: %s", self._uri, e)
            self.driver = None

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
        if not self.driver:
            return {"nodes": [], "edges": [], "stats": {}}
            
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

    # ── Utilities ─────────────────────────────────────────────────────────────

    def count_nodes(self) -> int:
        """Quick check of database size for status reporting."""
        if not self.driver:
            raise ConnectionError("Neo4j driver not connected")
            
        with self.driver.session() as session:
            result = session.run("MATCH (n) RETURN count(n) AS c")
            return result.single()["c"]

    def clear_database(self) -> None:
        """DANGER: Wipes the entire database. Used for tests."""
        if not self.driver:
            return
        with self.driver.session() as session:
            session.run("MATCH (n) DETACH DELETE n")
