import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter, Body
from src.memory.manager import memory_manager
from src.core.router import llm_router
from src.core.agent import Agent
from src.core.limits_store import (
    import_from_paste, load_limits, load_mismatch_log, get_limit_for_model
)

router = APIRouter()
web_agent = Agent(memory=memory_manager)


def _session_sort_key(item: dict) -> tuple[int, str]:
    ts = item.get("last_timestamp") or ""
    try:
        return (1, datetime.fromisoformat(ts.replace("Z", "+00:00")).isoformat())
    except Exception:
        return (0, ts)


def _build_session_preview(memories: list[dict]) -> str:
    for memory in memories:
        if memory.get("metadata", {}).get("role") == "user" and memory.get("text"):
            return memory["text"][:80]
    if memories:
        return memories[0].get("text", "")[:80]
    return "Empty conversation"


def _derive_model_function(model_id: str, capabilities: dict) -> str:
    """
    Derive a human-readable primary function label from a model's capability scores.
    Returns the highest-scoring task type, or a composite label for balanced models.
    """
    if not capabilities:
        return "General"

    sorted_caps = sorted(capabilities.items(), key=lambda x: x[1], reverse=True)
    top_score = sorted_caps[0][1]
    top_tasks = [task for task, score in sorted_caps if score >= top_score - 0.05]

    label_map = {
        "QA": "Q&A",
        "REASONING": "Reasoning",
        "EXTRACTION": "Extraction",
        "SUMMARIZATION": "Summarization",
        "CODE": "Code",
    }

    if len(top_tasks) >= 4:
        return "General Purpose"
    if len(top_tasks) == 1:
        return label_map.get(top_tasks[0], top_tasks[0])
    return " · ".join(label_map.get(t, t) for t in top_tasks[:2])


@router.get("/graph/overview")
async def get_overview():
    """Returns the full graph overview from Neo4j."""
    return memory_manager.neo4j.get_graph_overview(limit=100)

@router.get("/graph/node/{node_id}")
async def get_node_detail(node_id: str):
    """Returns details for a specific node from Neo4j."""
    return memory_manager.neo4j.get_node_detail(node_id)


@router.get("/chat/sessions")
async def get_chat_sessions():
    """List known conversation sessions from episodic memory."""
    if not memory_manager._is_chroma_available():
        return {"sessions": []}

    try:
        results = memory_manager.chroma.collection.get(limit=500)
    except Exception:
        return {"sessions": []}

    docs = results.get("documents") or []
    metas = results.get("metadatas") or []

    grouped: dict[str, list[dict]] = defaultdict(list)
    for idx, text in enumerate(docs):
        metadata = metas[idx] or {}
        session_id = metadata.get("session_id")
        if not session_id:
            continue
        grouped[session_id].append({
            "text": text,
            "metadata": metadata,
        })

    sessions = []
    for session_id, memories in grouped.items():
        memories.sort(key=lambda m: m.get("metadata", {}).get("timestamp", ""), reverse=True)
        sessions.append({
            "session_id": session_id,
            "turn_count": len(memories),
            "last_timestamp": memories[0].get("metadata", {}).get("timestamp"),
            "preview": _build_session_preview(memories),
        })

    sessions.sort(key=_session_sort_key, reverse=True)
    return {"sessions": sessions}


@router.get("/chat/session/{session_id}")
async def get_chat_session(session_id: str):
    """Return the stored history for a browser or Telegram conversation session."""
    history = memory_manager.get_history(session_id, limit=100)
    ordered = list(reversed(history))
    return {
        "session_id": session_id,
        "messages": [
            {
                "id": item.get("id"),
                "role": item.get("metadata", {}).get("role", "assistant"),
                "text": item.get("text", ""),
                "timestamp": item.get("metadata", {}).get("timestamp"),
            }
            for item in ordered
        ]
    }


@router.post("/chat/session")
async def create_chat_session(body: dict = Body(default={})):
    """Create a new browser chat session ID."""
    label = body.get("label", "browser")
    session_id = f"{label}_{uuid.uuid4().hex[:10]}"
    return {"session_id": session_id}


@router.delete("/chat/session/{session_id}")
async def delete_chat_session(session_id: str):
    """Delete all stored memories for a browser or Telegram conversation session."""
    ok = memory_manager.delete_session(session_id)
    if ok:
        return {"ok": True, "session_id": session_id}
    return {"ok": False, "session_id": session_id, "error": "Failed to delete session"}


@router.post("/chat/message")
async def post_chat_message(body: dict = Body(...)):
    """Send a browser chat message through the existing agent."""
    session_id = body.get("session_id")
    text = (body.get("message") or "").strip()
    anchor_node_id = body.get("anchor_node_id")

    if not session_id:
        return {"ok": False, "error": "Missing session_id"}
    if not text:
        return {"ok": False, "error": "Empty message"}

    effective_text = text
    anchor = None

    if anchor_node_id:
        detail = memory_manager.neo4j.get_node_detail(anchor_node_id)
        node = detail.get("node") if detail else None
        if node:
            connections = detail.get("connections", [])[:8]
            relation_summary = ", ".join(
                f"{c['type']} -> {c['target']}" for c in connections
            ) or "No direct connections listed."
            anchor = {
                "id": node.get("id"),
                "label": node.get("label"),
                "name": node.get("name"),
            }
            effective_text = (
                "Use this graph node as the anchor for the conversation.\n"
                f"Node: {node.get('name')} ({node.get('label')})\n"
                f"Details: {node}\n"
                f"Connections: {relation_summary}\n\n"
                f"User request: {text}"
            )

    reply = await web_agent.aprocess_message(
        "web_user",
        text,
        session_id,
        prompt_text=effective_text,
        store_text=text,
    )
    return {
        "ok": True,
        "session_id": session_id,
        "reply": reply,
        "anchor": anchor,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

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
            "model": model.model_id.split("/")[-1],
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
            # headroom is always real measured data — never a default
            "headroom": round(headroom * 100, 1),
            "function": _derive_model_function(short_id, model.capabilities),
            "capabilities": model.capabilities,
            "rpm": {"used": rpm_used, "limit": model.rpm_limit},
            "rpd": {"used": rpd_used, "limit": model.rpd_limit},
            "tpm": {"used": tpm_used, "limit": model.tpm_limit},
        })

    # Include untracked models from AI Studio limits override.
    # These have NO live usage data — headroom is null, not 100%.
    overrides = load_limits()
    for short_id, limits in overrides.items():
        if short_id not in tracked_ids:
            models_data.append({
                "model": short_id,
                "model_id": f"models/{short_id}",
                "provider": "google",
                "group": "Untracked (Limits Only)",
                # null = no live data, distinguished from 0% (exhausted)
                "headroom": None,
                "function": "Untracked",
                "capabilities": {},
                "rpm": {"used": None, "limit": limits.get("rpm_limit") or 0},
                "rpd": {"used": None, "limit": limits.get("rpd_limit") or 0},
                "tpm": {"used": None, "limit": limits.get("tpm_limit") or 0},
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
