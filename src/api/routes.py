from fastapi import APIRouter
from src.memory.manager import memory_manager

router = APIRouter()

@router.get("/graph/overview")
async def get_overview():
    """Returns the full graph overview from Neo4j."""
    return memory_manager.neo4j.get_graph_overview(limit=100)

@router.get("/graph/node/{node_id}")
async def get_node_detail(node_id: str):
    """Returns details for a specific node from Neo4j."""
    return memory_manager.neo4j.get_node_detail(node_id)

@router.get("/system/status")
async def get_system_status():
    """Returns the health status of backend systems in a frontend-friendly format."""
    # We pull from memory_manager for the dashboard to avoid heavy LLM pings
    health = memory_manager.status()
    
    # We return a format that graph explorer's panel.js expects:
    # { "neo4j": "online", "chroma": "online", "agent": "online", "messages": {...} }
    return {
        "status": health["status"],
        "neo4j": "online" if "online" in health["neo4j"] else "offline",
        "chroma": "online" if "online" in health["chroma"] else "offline",
        "agent": "online", # API is up
        "details": {
            "neo4j": health["neo4j"],
            "chroma": health["chroma"]
        }
    }

