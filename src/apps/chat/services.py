from __future__ import annotations

import uuid
from collections import OrderedDict, defaultdict
from datetime import datetime, timezone

from src.agent_platform.public.agent_service import AgentService
from src.agent_platform.public.contracts import AgentRunRequest
from src.memory.manager import MemoryManager

# Per-session client_msg_id -> previous response cache for retry dedupe.
# Capped at 50 entries per session, LRU eviction. In-process only — if the
# server restarts between the first and the retried send, the message will
# be re-processed; that's acceptable for a single-user local app.
_DEDUPE_CAP_PER_SESSION = 50
_dedupe_cache: dict[str, "OrderedDict[str, dict]"] = defaultdict(OrderedDict)


def _dedupe_lookup(session_id: str, client_msg_id: str | None) -> dict | None:
    if not client_msg_id:
        return None
    bucket = _dedupe_cache.get(session_id)
    if not bucket or client_msg_id not in bucket:
        return None
    bucket.move_to_end(client_msg_id)
    return bucket[client_msg_id]


def _dedupe_record(session_id: str, client_msg_id: str | None, response: dict) -> None:
    if not client_msg_id:
        return
    bucket = _dedupe_cache[session_id]
    bucket[client_msg_id] = response
    bucket.move_to_end(client_msg_id)
    while len(bucket) > _DEDUPE_CAP_PER_SESSION:
        bucket.popitem(last=False)


def build_graph_context(anchor_node_id: str, memory: MemoryManager) -> dict | None:
    detail = memory.graph_node_detail(anchor_node_id)
    node = detail.get("node") if detail else None
    if not node:
        return None

    connections = detail.get("connections", [])[:8]
    relation_summary = ", ".join(
        f"{c['type']} -> {c['target']}" for c in connections
    ) or "No direct connections listed."
    return {
        "source_section": "explorer",
        "context_type": "graph_node",
        "context_id": node.get("id"),
        "context_summary": f"{node.get('name')} ({node.get('label')})",
        "context_payload": {
            "node": {
                "id": node.get("id"),
                "label": node.get("label"),
                "name": node.get("name"),
            },
            "details": node,
            "connections": detail.get("connections", []),
            "relation_summary": relation_summary,
        },
    }


def normalize_chat_context(
    context: dict | None,
    memory: MemoryManager,
    anchor_node_id: str | None = None,
) -> dict | None:
    if context and context.get("context_type") and context.get("context_id"):
        return {
            "source_section": context.get("source_section") or "chat",
            "context_type": context["context_type"],
            "context_id": context["context_id"],
            "context_summary": context.get("context_summary") or context["context_id"],
            "context_payload": context.get("context_payload") or {},
        }
    if anchor_node_id:
        return build_graph_context(anchor_node_id, memory)
    return None


def build_effective_prompt(text: str, context: dict | None) -> str:
    if not context:
        return text

    payload = context.get("context_payload") or {}
    source_section = context.get("source_section", "unknown")
    context_type = context.get("context_type", "context")
    context_id = context.get("context_id", "unknown")
    context_summary = context.get("context_summary", context_id)

    lines = [
        "Use this platform context as the current conversation anchor.",
        f"Source section: {source_section}",
        f"Context type: {context_type}",
        f"Context id: {context_id}",
        f"Context summary: {context_summary}",
    ]

    if payload:
        lines.append(f"Context payload: {payload}")
        relation_summary = payload.get("relation_summary")
        if relation_summary:
            lines.append(f"Context relationships: {relation_summary}")

    lines.extend(["", f"User request: {text}"])
    return "\n".join(lines)


def build_session_preview(memories: list[dict]) -> str:
    for memory in memories:
        if memory.get("metadata", {}).get("role") == "user" and memory.get("text"):
            return memory["text"][:80]
    if memories:
        return memories[0].get("text", "")[:80]
    return "Empty conversation"


def session_sort_key(item: dict) -> tuple[int, str]:
    ts = item.get("last_timestamp") or ""
    try:
        return (1, datetime.fromisoformat(ts.replace("Z", "+00:00")).isoformat())
    except Exception:
        return (0, ts)


def list_chat_sessions(memory: MemoryManager) -> dict:
    results = memory.list_sessions(limit=500)
    docs = results["documents"]
    metas = results["metadatas"]

    if not docs:
        return {"sessions": []}

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
            "preview": build_session_preview(memories),
        })

    sessions.sort(key=session_sort_key, reverse=True)
    return {"sessions": sessions}


def get_chat_session(session_id: str, memory: MemoryManager) -> dict:
    history = memory.get_history(session_id, limit=100)
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
        ],
    }


def create_chat_session(label: str = "browser") -> dict:
    session_id = f"{label}_{uuid.uuid4().hex[:10]}"
    return {"session_id": session_id}


def delete_chat_session(session_id: str, memory: MemoryManager) -> dict:
    ok = memory.delete_session(session_id)
    if ok:
        return {"ok": True, "session_id": session_id}
    return {"ok": False, "session_id": session_id, "error": "Failed to delete session"}


async def send_chat_message(
    *,
    app_id: str,
    user_id: str,
    session_id: str,
    text: str,
    memory: MemoryManager,
    service: AgentService,
    message_timestamp: str | None = None,
    context: dict | None = None,
    anchor_node_id: str | None = None,
    client_msg_id: str | None = None,
) -> dict:
    # Dedupe retries from the frontend offline queue. If we've already
    # processed this client_msg_id for the session, replay the original
    # reply instead of re-running the agent.
    cached = _dedupe_lookup(session_id, client_msg_id)
    if cached is not None:
        return {**cached, "deduped": True}

    normalized_context = normalize_chat_context(context, memory, anchor_node_id)
    effective_text = build_effective_prompt(text, normalized_context)

    result = await service.arun(
        AgentRunRequest(
            app_id=app_id,
            user_id=user_id,
            session_id=session_id,
            message=text,
            message_timestamp=message_timestamp,
            prompt_text=effective_text,
            store_text=text,
            store_metadata={
                "app_id": app_id,
                "user_id": user_id,
                "source_section": normalized_context.get("source_section", "chat") if normalized_context else "chat",
                "chat_context": normalized_context or {},
            },
            context={"chat_context": normalized_context} if normalized_context else {},
        )
    )
    response = {
        "ok": True,
        "session_id": session_id,
        "reply": result.reply,
        "context": normalized_context,
        "timestamp": result.reply_timestamp or datetime.now(timezone.utc).isoformat(),
        "message_timestamp": message_timestamp,
        "memory_degraded": result.memory_degraded,
        "memory_health": result.memory_health,
    }
    _dedupe_record(session_id, client_msg_id, response)
    return response
