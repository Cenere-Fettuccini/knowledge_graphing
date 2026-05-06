import time
from fastapi import APIRouter, Body
from src.memory.manager import memory_manager
from src.core.router import llm_router
from src.core.limits_store import (
    import_from_paste, load_limits, load_mismatch_log, get_limit_for_model
)

router = APIRouter()

@router.get("/graph/overview")
async def get_overview():
    """Returns the full graph overview from Neo4j."""
    return memory_manager.neo4j.get_graph_overview(limit=100)

@router.get("/graph/node/{node_id}")
async def get_node_detail(node_id: str):
    """Returns details for a specific node from Neo4j."""
    return memory_manager.neo4j.get_node_detail(node_id)

@router.get("/tasks/active")
async def get_active_tasks():
    """Returns all active tasks from Neo4j."""
    overview = memory_manager.neo4j.get_graph_overview(limit=100)
    tasks = [n for n in overview["nodes"] if n["label"] == "Task"]
    return tasks

@router.get("/graph/belief/{belief_id}/trail")
async def get_belief_trail(belief_id: str):
    """Returns the full evolution chain and evidence for a belief."""
    chain = memory_manager.neo4j.get_belief_chain(belief_id)
    evidence = memory_manager.neo4j.get_belief_evidence(belief_id)
    return {"chain": chain, "evidence": evidence}

@router.get("/system/status")
async def get_system_status():
    """Returns the health status of backend systems in a frontend-friendly format."""
    # The status endpoint is explicitly for health checks — always use fresh data
    memory_manager._health_cache_time = 0
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


@router.get("/credits")
async def get_credits():
    """Returns detailed per-model API usage and limits for the credits dashboard."""
    now = time.time()
    models_data = []
    tracked_ids = set()

    for model in llm_router.models:
        short_id = model.model_id.split("/")[-1]
        tracked_ids.add(short_id)
        state = llm_router.limiter._get_state(model.model_id, model.api_key)

        # Prune stale windows in-memory (mirrors limiter logic, non-mutating read)
        rpm_used = len([t for t in state.used_rpm if now - t < 60])
        rpd_used = len([t for t in state.used_rpd if now - t < 86400])
        tpm_used = sum(e["tokens"] for e in state.used_tpm if now - e["ts"] < 60)

        headroom = llm_router.limiter.get_headroom(
            model.model_id, model.api_key,
            model.rpm_limit, model.rpd_limit, model.tpm_limit
        )

        masked_key = f"****{model.api_key[-4:]}" if len(model.api_key) > 4 else "Unauthenticated"
        group_name = "Local Models" if model.provider == "local" else f"{model.provider.capitalize()} API ({masked_key})"

        models_data.append({
            "model": short_id,
            "model_id": model.model_id,
            "provider": model.provider,
            "group": group_name,
            "headroom": round(headroom * 100, 1),
            "rpm": {"used": rpm_used, "limit": model.rpm_limit},
            "rpd": {"used": rpd_used, "limit": model.rpd_limit},
            "tpm": {"used": tpm_used, "limit": model.tpm_limit},
        })

    # Include untracked models from AI Studio limits override
    overrides = load_limits()
    for short_id, limits in overrides.items():
        if short_id not in tracked_ids:
            models_data.append({
                "model": short_id,
                "model_id": f"models/{short_id}",
                "provider": "google",
                "group": "Untracked (Override Limits)",
                "headroom": 100.0,
                "rpm": {"used": 0, "limit": limits.get("rpm_limit") or 0},
                "rpd": {"used": 0, "limit": limits.get("rpd_limit") or 0},
                "tpm": {"used": 0, "limit": limits.get("tpm_limit") or 0},
            })

    return {"models": models_data, "timestamp": now}


@router.post("/credits/limits/import")
async def import_limits(body: dict = Body(...)):
    """Parse raw AI Studio rate-limits paste and persist as limits_override.json."""
    raw_text = body.get("text", "")
    if not raw_text.strip():
        return {"ok": False, "error": "No text provided", "matched": []}
    updated, matched = import_from_paste(raw_text)
    # Hot-reload router so new limits are used immediately (no restart needed)
    llm_router.reload_limits()
    return {"ok": True, "matched": matched, "total_models": len(updated)}


@router.get("/credits/mismatches")
async def get_mismatches():
    """Return logged 429 events for mismatch analysis on the credits dashboard."""
    events = load_mismatch_log()
    # Annotate each event with override vs stored delta
    overrides = load_limits()
    for ev in events:
        mid = ev["model_id"].split("/")[-1]
        override = overrides.get(mid, {})
        ev["override_limits"] = {
            "rpm": override.get("rpm_limit"),
            "tpm": override.get("tpm_limit"),
            "rpd": override.get("rpd_limit"),
        }
    return {"events": events[-50:]}  # last 50
