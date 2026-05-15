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
    era_id: str | None = Query(None),
    active_self_only: bool = Query(False),
    memory: MemoryManager = Depends(get_memory_manager),
):
    return services.get_graph_overview(
        memory, limit=limit, era_id=era_id, active_self_only=active_self_only
    )


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
async def get_active_tasks(
    include_completed: bool = False,
    since: str | None = None,
    memory: MemoryManager = Depends(get_memory_manager),
):
    return services.get_active_tasks(
        memory, include_completed=include_completed, since=since
    )


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


# ── Eras (S3.1) ──────────────────────────────────────────────────────────────

@router.get("/eras")
async def list_eras(
    active_only: bool = False,
    memory: MemoryManager = Depends(get_memory_manager),
):
    return {"eras": memory.list_eras(active_only=active_only)}


@router.get("/eras/{era_id}")
async def get_era(era_id: str, memory: MemoryManager = Depends(get_memory_manager)):
    era = memory.get_era(era_id)
    if era is None:
        raise HTTPException(status_code=404, detail=f"Era {era_id} not found")
    return era


@router.post("/eras")
async def create_era(
    payload: dict = Body(...),
    memory: MemoryManager = Depends(get_memory_manager),
):
    name = (payload or {}).get("name", "")
    if not isinstance(name, str) or not name.strip():
        raise HTTPException(status_code=400, detail="`name` is required")
    try:
        return memory.upsert_era(
            name=name,
            description=payload.get("description", "") or "",
            start_date=payload.get("start_date"),
            end_date=payload.get("end_date"),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.patch("/eras/{era_id}")
async def update_era(
    era_id: str,
    payload: dict = Body(...),
    memory: MemoryManager = Depends(get_memory_manager),
):
    existing = memory.get_era(era_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Era {era_id} not found")
    return memory.upsert_era(
        era_id=era_id,
        name=payload.get("name") or existing.get("name", ""),
        description=payload.get("description", existing.get("description", "")) or "",
        start_date=payload.get("start_date", existing.get("start_date")),
        end_date=payload.get("end_date", existing.get("end_date")),
    )


@router.delete("/eras/{era_id}")
async def delete_era(era_id: str, memory: MemoryManager = Depends(get_memory_manager)):
    return {"ok": memory.delete_era(era_id)}


@router.post("/eras/{era_id}/bind/{node_id}")
async def bind_node_to_era(
    era_id: str, node_id: str,
    memory: MemoryManager = Depends(get_memory_manager),
):
    return {"ok": memory.bind_node_to_era(node_id, era_id)}


@router.delete("/eras/{era_id}/bind/{node_id}")
async def unbind_node_from_era(
    era_id: str, node_id: str,
    memory: MemoryManager = Depends(get_memory_manager),
):
    return {"ok": memory.unbind_node_from_era(node_id, era_id)}


# ── Cloud belief extraction (S3.4) ───────────────────────────────────────────

@router.post("/analyze/beliefs/extract")
async def run_belief_extraction(
    payload: dict = Body(default={}),
    memory: MemoryManager = Depends(get_memory_manager),
):
    from src.agent_platform.analyzers.cloud_belief_extraction import (
        run_belief_extraction_once,
    )
    batch_size = int((payload or {}).get("batch_size") or 25)
    return await run_belief_extraction_once(memory, batch_size=batch_size)


@router.get("/analyze/beliefs/queue")
async def get_belief_queue_depth(memory: MemoryManager = Depends(get_memory_manager)):
    return {"pending": memory.count_belief_candidates()}


# ── Schema drift monitor (S3.5) ──────────────────────────────────────────────

@router.get("/schema/drift")
async def schema_drift(
    window_days: int = Query(7, ge=1, le=365),
    memory: MemoryManager = Depends(get_memory_manager),
):
    from src.agent_platform.analyzers.schema_drift import check_drift
    return check_drift(memory, window_days=window_days)


@router.post("/schema/snapshot")
async def schema_snapshot(memory: MemoryManager = Depends(get_memory_manager)):
    from src.agent_platform.analyzers.schema_drift import take_snapshot
    return take_snapshot(memory)


# ── Pending belief queue (S4.1) ──────────────────────────────────────────────

@router.get("/beliefs/pending")
async def list_pending_beliefs(
    limit: int = Query(50, ge=1, le=500),
    memory: MemoryManager = Depends(get_memory_manager),
):
    return {"beliefs": memory.list_pending_beliefs(limit=limit)}


@router.post("/beliefs/pending")
async def create_pending_belief(
    payload: dict = Body(...),
    memory: MemoryManager = Depends(get_memory_manager),
):
    content = (payload or {}).get("content", "")
    if not isinstance(content, str) or not content.strip():
        raise HTTPException(status_code=400, detail="`content` is required")
    return memory.create_pending_belief(
        content=content,
        about_entity_id=payload.get("about_entity_id"),
        source=payload.get("source", "rumination"),
        confidence=float(payload.get("confidence", 0.6)),
    )


@router.post("/beliefs/pending/{belief_id}/approve")
async def approve_pending_belief(
    belief_id: str,
    memory: MemoryManager = Depends(get_memory_manager),
):
    return memory.approve_pending_belief(belief_id) or {"ok": False}


@router.post("/beliefs/pending/{belief_id}/edit")
async def edit_pending_belief(
    belief_id: str,
    payload: dict = Body(...),
    memory: MemoryManager = Depends(get_memory_manager),
):
    new_content = (payload or {}).get("new_content", "")
    if not isinstance(new_content, str) or not new_content.strip():
        raise HTTPException(status_code=400, detail="`new_content` is required")
    return memory.edit_pending_belief(belief_id, new_content=new_content)


@router.post("/beliefs/pending/{belief_id}/reject")
async def reject_pending_belief(
    belief_id: str,
    payload: dict | None = Body(default=None),
    memory: MemoryManager = Depends(get_memory_manager),
):
    reason = ((payload or {}).get("reason") or "").strip()
    return memory.reject_pending_belief(belief_id, reason=reason)


@router.post("/beliefs/rejections/purge")
async def purge_expired_rejections(memory: MemoryManager = Depends(get_memory_manager)):
    return {"deleted": memory.purge_expired_rejections()}


@router.get("/beliefs/rejections/active")
async def list_active_rejections(
    limit: int = Query(100, ge=1, le=500),
    memory: MemoryManager = Depends(get_memory_manager),
):
    return {"rejections": memory.list_active_rejections(limit=limit)}


# ── Contradiction detection (S4.3) ───────────────────────────────────────────

@router.post("/analyze/contradictions")
async def run_contradictions(
    payload: dict | None = Body(default=None),
    memory: MemoryManager = Depends(get_memory_manager),
):
    from src.agent_platform.analyzers.contradiction_detection import (
        run_contradiction_detection,
    )
    since = (payload or {}).get("since")
    return await run_contradiction_detection(memory, since=since)


@router.get("/beliefs/contradictions")
async def list_contradictions(
    limit: int = Query(50, ge=1, le=500),
    memory: MemoryManager = Depends(get_memory_manager),
):
    return {"contradictions": memory.list_contradictions(limit=limit)}


@router.get("/beliefs/calibration")
async def get_belief_calibration(
    memory: MemoryManager = Depends(get_memory_manager),
):
    """Approve/reject ratio per pending-belief source (CT3)."""
    return {"sources": memory.belief_calibration()}


# ── Focal-node neighborhood + era windowing (S4.5 / S4.6) ────────────────────

@router.get("/graph/neighborhood/{node_id}")
async def get_graph_neighborhood(
    node_id: str,
    depth: int = Query(1, ge=1, le=4),
    limit: int = Query(200, ge=1, le=500),
    memory: MemoryManager = Depends(get_memory_manager),
):
    return memory.graph_neighborhood(node_id, depth=depth, limit=limit)


@router.get("/eras/active-at")
async def eras_active_at(
    date: str = Query(...),
    memory: MemoryManager = Depends(get_memory_manager),
):
    """Eras whose [start_date, end_date] window contains the ISO date."""
    return {"eras": memory.eras_active_at(date)}
