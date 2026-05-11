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


@router.post("/bulk/import")
async def run_bulk_import(
    payload: dict = Body(...),
    memory: MemoryManager = Depends(get_memory_manager),
):
    path = (payload or {}).get("path")
    fmt = (payload or {}).get("format", "jsonl")
    source = (payload or {}).get("source")
    chunk_size = (payload or {}).get("chunk_size", 1000)
    chunk_overlap = (payload or {}).get("chunk_overlap", 100)
    if not isinstance(path, str) or not path.strip():
        raise HTTPException(status_code=400, detail="`path` is required and must be a non-empty string")
    if fmt not in ("jsonl", "directory"):
        raise HTTPException(status_code=400, detail="`format` must be 'jsonl' or 'directory'")
    if source is not None and not isinstance(source, str):
        raise HTTPException(status_code=400, detail="`source` must be a string if provided")
    if not isinstance(chunk_size, int) or chunk_size <= 0 or chunk_size > 10000:
        raise HTTPException(status_code=400, detail="`chunk_size` must be an integer in 1..10000")
    if not isinstance(chunk_overlap, int) or chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise HTTPException(status_code=400, detail="`chunk_overlap` must be a non-negative integer less than chunk_size")
    return services.run_bulk_import(
        memory,
        path=path,
        format=fmt,
        source=source,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )


@router.post("/canonicalize/run")
async def run_canonicalization(
    payload: dict | None = Body(default=None),
    memory: MemoryManager = Depends(get_memory_manager),
):
    payload = payload or {}
    target = payload.get("target", "entities")
    if target not in ("entities", "beliefs"):
        raise HTTPException(
            status_code=400,
            detail="target must be 'entities' or 'beliefs'",
        )
    threshold = payload.get("threshold")
    if threshold is not None and (
        not isinstance(threshold, (int, float)) or not 0.0 < float(threshold) <= 1.0
    ):
        raise HTTPException(
            status_code=400,
            detail="threshold must be a number in (0.0, 1.0] if provided",
        )
    return services.run_canonicalization(
        memory,
        target=target,
        threshold=float(threshold) if threshold is not None else None,
    )


@router.get("/canonicalize/proposals")
async def get_canonicalize_proposals(
    status: str = Query("pending", pattern="^(pending|applied|dismissed)$"),
    limit: int = Query(200, ge=1, le=1000),
    memory: MemoryManager = Depends(get_memory_manager),
):
    return services.list_merge_proposals(memory, status=status, limit=limit)


@router.post("/canonicalize/apply/{proposal_id}")
async def apply_canonicalize_proposal(
    proposal_id: str,
    memory: MemoryManager = Depends(get_memory_manager),
):
    try:
        return services.apply_merge_proposal(memory, proposal_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/canonicalize/dismiss/{proposal_id}")
async def dismiss_canonicalize_proposal(
    proposal_id: str,
    memory: MemoryManager = Depends(get_memory_manager),
):
    return services.dismiss_merge_proposal(memory, proposal_id)


@router.get("/system/status")
async def get_system_status(
    memory: MemoryManager = Depends(get_memory_manager),
    service: AgentService = Depends(get_agent_service),
):
    return await services.get_system_status(memory, service)
