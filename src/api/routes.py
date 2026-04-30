from fastapi import APIRouter

router = APIRouter()

# Mock data for the Explorer
MOCK_GRAPH = {
    "nodes": [
        {"id": "user", "label": "Person", "name": "Kevin"},
        {"id": "aimanager", "label": "Project", "name": "AIManager"},
        {"id": "rust", "label": "Topic", "name": "Rust"},
        {"id": "python", "label": "Topic", "name": "Python"},
        {"id": "b1", "label": "Belief", "name": "Rust worth tradeoff", "conf": 0.87, "status": "active"},
        {"id": "t1", "label": "Task", "name": "Review borrow checker", "status": "pending"},
    ],
    "edges": [
        {"source": "user", "target": "aimanager", "type": "WORKS_ON"},
        {"source": "user", "target": "rust", "type": "LEARNING"},
        {"source": "b1", "target": "rust", "type": "ABOUT"},
        {"source": "t1", "target": "rust", "type": "RELATED_TO"},
        {"source": "aimanager", "target": "python", "type": "USES"},
    ],
    "stats": {
        "nodes": 6,
        "edges": 5,
        "tasks": 1,
        "last_rumination": "2h ago"
    }
}

MOCK_NODE_DETAILS = {
    "b1": {
        "node": MOCK_GRAPH["nodes"][4],
        "beliefs": [],
        "tasks": [],
        "connections": [
            {"target": "Rust", "type": "ABOUT"}
        ]
    }
}

@router.get("/graph/overview")
async def get_overview():
    """Returns the full graph overview (mocked)."""
    return MOCK_GRAPH

@router.get("/graph/node/{node_id}")
async def get_node_detail(node_id: str):
    """Returns details for a specific node (mocked)."""
    return MOCK_NODE_DETAILS.get(node_id, {
        "node": next((n for n in MOCK_GRAPH["nodes"] if n["id"] == node_id), None),
        "beliefs": [],
        "tasks": [],
        "connections": []
    })

@router.get("/system/status")
async def get_system_status():
    """Returns the health status of backend systems (independent check)."""
    # In Step 5, this will actually ping the Neo4j driver
    # In Step 3, this will ping ChromaDB
    import random
    return {
        "neo4j": "online" if random.random() > 0.1 else "offline",
        "chroma": "online",
        "agent": "standby"
    }
