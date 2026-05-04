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
    """Returns the health status of backend systems."""
    status = memory_manager.status()
    # We do not ping the LLM here to save API costs on the 30s frontend polling interval
    status["agent"] = "standby"
    return status

