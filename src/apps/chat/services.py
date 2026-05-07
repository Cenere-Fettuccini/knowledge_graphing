from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timezone

from src.agent_platform.public.agent_service import agent_service
from src.agent_platform.public.contracts import AgentRunRequest
from src.memory.manager import memory_manager


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


def list_chat_sessions() -> dict:
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
            "preview": build_session_preview(memories),
        })

    sessions.sort(key=session_sort_key, reverse=True)
    return {"sessions": sessions}


def get_chat_session(session_id: str) -> dict:
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
        ],
    }


def create_chat_session(label: str = "browser") -> dict:
    session_id = f"{label}_{uuid.uuid4().hex[:10]}"
    return {"session_id": session_id}


def delete_chat_session(session_id: str) -> dict:
    ok = memory_manager.delete_session(session_id)
    if ok:
        return {"ok": True, "session_id": session_id}
    return {"ok": False, "session_id": session_id, "error": "Failed to delete session"}


async def send_chat_message(
    *,
    app_id: str,
    user_id: str,
    session_id: str,
    text: str,
    anchor_node_id: str | None = None,
) -> dict:
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

    result = await agent_service.arun(
        AgentRunRequest(
            app_id=app_id,
            user_id=user_id,
            session_id=session_id,
            message=text,
            prompt_text=effective_text,
            store_text=text,
            context={"anchor": anchor} if anchor else {},
        )
    )
    return {
        "ok": True,
        "session_id": session_id,
        "reply": result.reply,
        "anchor": anchor,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
