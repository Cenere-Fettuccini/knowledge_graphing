from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from src.agent_platform.public.agent_service import AgentService, get_agent_service
from src.apps.explorer import services
from src.memory.manager import MemoryManager, get_memory_manager

router = APIRouter()


@router.get("/graph/overview")
async def get_overview(
    limit: int = Query(100, ge=1, le=1000),
    memory: MemoryManager = Depends(get_memory_manager),
):
    return services.get_graph_overview(memory, limit=limit)


@router.get("/graph/node/{node_id}")
async def get_node_detail(
    node_id: str,
    memory: MemoryManager = Depends(get_memory_manager),
):
    return services.get_node_detail(node_id, memory)


@router.get("/graph/node/{node_id}/provenance")
async def get_node_provenance(
    node_id: str,
    memory: MemoryManager = Depends(get_memory_manager),
):
    return services.get_node_provenance(node_id, memory)


@router.get("/tasks/active")
async def get_active_tasks(memory: MemoryManager = Depends(get_memory_manager)):
    return services.get_active_tasks(memory)


@router.get("/graph/belief/{belief_id}/trail")
async def get_belief_trail(
    belief_id: str,
    memory: MemoryManager = Depends(get_memory_manager),
):
    return services.get_belief_trail(belief_id, memory)


@router.get("/system/status")
async def get_system_status(
    memory: MemoryManager = Depends(get_memory_manager),
    service: AgentService = Depends(get_agent_service),
):
    return await services.get_system_status(memory, service)
