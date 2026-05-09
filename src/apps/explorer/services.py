from __future__ import annotations

from src.agent_platform.public.agent_service import agent_service
from src.memory.manager import memory_manager


def get_graph_overview() -> dict:
    return memory_manager.graph_overview(limit=100)


def get_node_detail(node_id: str) -> dict:
    return memory_manager.graph_node_detail(node_id)


def get_node_provenance(node_id: str) -> dict:
    return memory_manager.graph_node_provenance(node_id)


def get_active_tasks() -> list[dict]:
    return memory_manager.graph_active_tasks()


def get_belief_trail(belief_id: str) -> dict:
    return memory_manager.graph_belief_trail(belief_id)


async def get_system_status() -> dict:
    memory_manager.invalidate_health_cache()
    health = memory_manager.status()

    quota = await agent_service.aquota_status()
    agent_status = await agent_service.astatus(force=True)
    return {
        "status": health["status"],
        "neo4j": "online" if "online" in health["neo4j"] else "offline",
        "chroma": "online" if "online" in health["chroma"] else "offline",
        "agent": "online" if agent_status.status == "online" else agent_status.status,
        "quota": quota,
        "details": {
            "neo4j": health["neo4j"],
            "chroma": health["chroma"],
            "llm": agent_status.llm,
        },
    }
