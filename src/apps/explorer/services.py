from __future__ import annotations

from src.agent_platform.public.agent_service import AgentService
from src.memory.manager import MemoryManager


def get_graph_overview(memory: MemoryManager, limit: int = 100) -> dict:
    return memory.graph_overview(limit=limit)


def get_node_detail(node_id: str, memory: MemoryManager) -> dict:
    return memory.graph_node_detail(node_id)


def get_node_provenance(node_id: str, memory: MemoryManager) -> dict:
    return memory.graph_node_provenance(node_id)


def get_active_tasks(memory: MemoryManager) -> list[dict]:
    return memory.graph_active_tasks()


def get_belief_trail(belief_id: str, memory: MemoryManager) -> dict:
    return memory.graph_belief_trail(belief_id)


async def get_system_status(memory: MemoryManager, service: AgentService) -> dict:
    memory.invalidate_health_cache()
    health = memory.status()

    quota = await service.aquota_status()
    agent_status = await service.astatus(force=True)
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
