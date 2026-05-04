"""Integration tests for the Neo4j Store."""

import pytest
import uuid
from src.memory.stores.neo4j_store import Neo4jStore


@pytest.fixture(scope="module")
def neo4j_store():
    """Provides a connected Neo4jStore, clears it before and after tests."""
    store = Neo4jStore()
    if not store.driver:
        pytest.skip("Neo4j is not running. Start local Neo4j to run these tests.")
        
    store.clear_database()
    yield store
    store.clear_database()
    store.close()


def test_add_and_retrieve_node(neo4j_store):
    """Test creating a node and retrieving it in the overview."""
    node_id = f"test_node_{uuid.uuid4().hex[:8]}"
    neo4j_store.add_node("TestNode", "Alpha", {"id": node_id, "score": 99})
    
    overview = neo4j_store.get_graph_overview()
    nodes = overview["nodes"]
    
    # Find our node
    test_node = next((n for n in nodes if n["id"] == node_id), None)
    assert test_node is not None
    assert test_node["label"] == "TestNode"
    assert test_node["name"] == "Alpha"
    assert test_node["score"] == 99


def test_add_and_retrieve_edge(neo4j_store):
    """Test creating an edge between two nodes and verifying it exists."""
    id1 = f"src_{uuid.uuid4().hex[:8]}"
    id2 = f"tgt_{uuid.uuid4().hex[:8]}"
    
    neo4j_store.add_node("Person", "Alice", {"id": id1})
    neo4j_store.add_node("Concept", "Graph", {"id": id2})
    
    neo4j_store.add_edge(id1, id2, "KNOWS_ABOUT")
    
    # 1. Check overview
    overview = neo4j_store.get_graph_overview()
    edges = overview["edges"]
    
    test_edge = next((e for e in edges if e["source"] == id1 and e["target"] == id2), None)
    assert test_edge is not None
    assert test_edge["type"] == "KNOWS_ABOUT"
    
    # 2. Check node details (outgoing from Alice)
    detail1 = neo4j_store.get_node_detail(id1)
    assert detail1["node"]["id"] == id1
    assert len(detail1["connections"]) == 1
    conn1 = detail1["connections"][0]
    assert conn1["direction"] == "out"
    assert conn1["type"] == "KNOWS_ABOUT"
    assert conn1["id"] == id2
    
    # 3. Check node details (incoming to Graph)
    detail2 = neo4j_store.get_node_detail(id2)
    assert len(detail2["connections"]) == 1
    conn2 = detail2["connections"][0]
    assert conn2["direction"] == "in"
    assert conn2["type"] == "KNOWS_ABOUT"
    assert conn2["id"] == id1


def test_node_update(neo4j_store):
    """Test that adding a node with the same ID updates it."""
    node_id = f"upd_{uuid.uuid4().hex[:8]}"
    
    # Create
    neo4j_store.add_node("Item", "OldName", {"id": node_id, "version": 1})
    
    # Update
    neo4j_store.add_node("Item", "NewName", {"id": node_id, "version": 2, "new_prop": True})
    
    detail = neo4j_store.get_node_detail(node_id)
    assert detail["node"]["name"] == "NewName"
    assert detail["node"]["version"] == 2
    assert detail["node"]["new_prop"] is True
