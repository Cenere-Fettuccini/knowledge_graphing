from __future__ import annotations

from src.agent_platform.public.agent_service import agent_service
from src.core.router import llm_router
from src.memory.manager import memory_manager


def get_graph_overview() -> dict:
    return memory_manager.neo4j.get_graph_overview(limit=100)


def get_node_detail(node_id: str) -> dict:
    return memory_manager.neo4j.get_node_detail(node_id)


def get_node_provenance(node_id: str) -> dict:
    return memory_manager.neo4j.get_node_provenance(node_id)


def get_active_tasks() -> list[dict]:
    overview = memory_manager.neo4j.get_graph_overview(limit=100)
    return [n for n in overview["nodes"] if n["label"] == "Task"]


def get_belief_trail(belief_id: str) -> dict:
    chain = memory_manager.neo4j.get_belief_chain(belief_id)
    evidence = memory_manager.neo4j.get_belief_evidence(belief_id)
    return {"chain": chain, "evidence": evidence}


async def get_system_status() -> dict:
    memory_manager._health_cache_time = 0
    health = memory_manager.status()

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
