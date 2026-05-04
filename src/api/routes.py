from fastapi import APIRouter
from src.memory.manager import memory_manager
from src.core.router import llm_router

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
    
    # Build quota summary for the frontend
    quota = []
    for model in llm_router.models:
        headroom = llm_router.limiter.get_headroom(
            model.model_id, model.api_key, 
            model.rpm_limit, model.rpd_limit, model.tpm_limit
        )
        quota.append({
            "model": model.model_id.split("/")[-1], # e.g. gemini-1.5-pro
            "headroom": round(headroom * 100, 1),
            "rpm_limit": model.rpm_limit,
            "rpd_limit": model.rpd_limit
        })

    return {
        "status": health["status"],
        "neo4j": "online" if "online" in health["neo4j"] else "offline",
        "chroma": "online" if "online" in health["chroma"] else "offline",
        "agent": "online",
        "quota": quota,
        "details": {
            "neo4j": health["neo4j"],
            "chroma": health["chroma"]
        }
    }

