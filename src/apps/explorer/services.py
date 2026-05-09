from __future__ import annotations

from src.agent_platform.public.agent_service import AgentService
from src.core.router import llm_router
from src.memory.manager import MemoryManager


def get_graph_overview(memory: MemoryManager) -> dict:
    return memory.neo4j.get_explorer_graph_overview(limit=100)


def get_node_detail(node_id: str, memory: MemoryManager) -> dict:
    return memory.neo4j.get_node_detail(node_id)


def get_node_provenance(node_id: str, memory: MemoryManager) -> dict:
    return memory.neo4j.get_node_provenance(node_id)


def get_active_tasks(memory: MemoryManager) -> list[dict]:
    return memory.neo4j.list_active_tasks()


def get_belief_trail(belief_id: str, memory: MemoryManager) -> dict:
    chain = memory.neo4j.get_belief_chain(belief_id)
    evidence = memory.neo4j.get_belief_evidence(belief_id)
    return {"chain": chain, "evidence": evidence}


async def get_system_status(memory: MemoryManager, service: AgentService) -> dict:
    memory._health_cache_time = 0
    health = memory.status()

    quota = []
    for model in llm_router.models:
        headroom = llm_router.limiter.get_headroom(
            model.model_id,
            model.project_scope,
            model.rpm_limit,
            model.rpd_limit,
            model.tpm_limit,
        )
        quota.append({
            "model": model.model_id.split("/")[-1],
            "project_scope": model.project_scope,
            "headroom": round(headroom * 100, 1),
            "rpm_limit": model.rpm_limit,
            "rpd_limit": model.rpd_limit,
        })

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
