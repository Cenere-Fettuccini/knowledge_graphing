import sys
import os
sys.path.append(os.path.abspath("."))
from src.memory.stores.neo4j_store import Neo4jStore

# The original MOCK_GRAPH data
nodes = [
    {"id": "user", "label": "Person", "name": "Kevin"},
    {"id": "aimanager", "label": "Project", "name": "AIManager"},
    {"id": "rust", "label": "Topic", "name": "Rust"},
    {"id": "python", "label": "Topic", "name": "Python"},
    {"id": "b1", "label": "Belief", "name": "Rust worth tradeoff", "conf": 0.87, "status": "active"},
    {"id": "t1", "label": "Task", "name": "Review borrow checker", "status": "pending"},
]

edges = [
    {"source": "user", "target": "aimanager", "type": "WORKS_ON"},
    {"source": "user", "target": "rust", "type": "LEARNING"},
    {"source": "b1", "target": "rust", "type": "ABOUT"},
    {"source": "t1", "target": "rust", "type": "RELATED_TO"},
    {"source": "aimanager", "target": "python", "type": "USES"},
]

def seed_graph():
    store = Neo4jStore()
    if not store.driver:
        print("Failed to connect to Neo4j.")
        return
        
    print("Clearing existing database...")
    store.clear_database()
    
    print(f"Inserting {len(nodes)} nodes...")
    for node in nodes:
        props = {k: v for k, v in node.items() if k not in ["label", "name"]}
        store.add_node(node["label"], node["name"], props)
        
    print(f"Inserting {len(edges)} edges...")
    for edge in edges:
        store.add_edge(edge["source"], edge["target"], edge["type"])
        
    stats = store.get_graph_overview()
    print(f"Done! Inserted {stats['stats']['nodes']} nodes and {stats['stats']['edges']} edges.")
    store.close()

if __name__ == "__main__":
    seed_graph()
