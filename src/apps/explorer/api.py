from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from src.agent_platform.public.agent_service import AgentService, get_agent_service
from src.apps.explorer import services
from src.memory.manager import MemoryManager, get_memory_manager

router = APIRouter()


@router.get("/bootstrap/status")
async def get_bootstrap_status(memory: MemoryManager = Depends(get_memory_manager)):
    return services.get_bootstrap_status(memory)


@router.post("/bootstrap")
async def bootstrap_user(
    payload: dict = Body(...),
    memory: MemoryManager = Depends(get_memory_manager),
):
    name = (payload or {}).get("name", "")
    if not isinstance(name, str) or not name.strip():
        raise HTTPException(status_code=400, detail="`name` is required and must be a non-empty string.")
    try:
        return services.bootstrap_user(name, memory)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


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


@router.get("/analyze/status")
async def get_analyzer_status(memory: MemoryManager = Depends(get_memory_manager)):
    return services.get_analyzer_status(memory)


@router.get("/analyze/models")
async def list_analyzer_models(memory: MemoryManager = Depends(get_memory_manager)):
    return services.list_analyzer_models(memory)


@router.post("/analyze/run")
async def run_analyzer(
    payload: dict | None = Body(default=None),
    memory: MemoryManager = Depends(get_memory_manager),
):
    payload = payload or {}
    batch_size = payload.get("batch_size", 20)
    model = payload.get("model")
    if not isinstance(batch_size, int) or batch_size <= 0 or batch_size > 200:
        raise HTTPException(status_code=400, detail="batch_size must be an integer in 1..200")
    if model is not None and not isinstance(model, str):
        raise HTTPException(status_code=400, detail="model must be a string if provided")
    return services.run_analyzer(memory, batch_size=batch_size, model=model)


@router.get("/analyze/failed")
async def list_analyzer_failures(
    limit: int = Query(50, ge=1, le=500),
    memory: MemoryManager = Depends(get_memory_manager),
):
    return services.list_analyzer_failures(memory, limit=limit)


@router.post("/analyze/retry-failed")
async def retry_analyzer_failures(
    payload: dict | None = Body(default=None),
    memory: MemoryManager = Depends(get_memory_manager),
):
    payload = payload or {}
    memory_ids = payload.get("memory_ids")
    if memory_ids is not None and not (
        isinstance(memory_ids, list)
        and all(isinstance(x, str) for x in memory_ids)
    ):
        raise HTTPException(
            status_code=400,
            detail="memory_ids must be a list of strings if provided",
        )
    return services.retry_analyzer_failures(memory, memory_ids=memory_ids)


@router.get("/system/status")
async def get_system_status(
    memory: MemoryManager = Depends(get_memory_manager),
    service: AgentService = Depends(get_agent_service),
):
    return await services.get_system_status(memory, service)
