from __future__ import annotations

from fastapi import APIRouter, Body, Depends

from src.agent_platform.public.agent_service import AgentService, get_agent_service
from src.apps.chat import services
from src.memory.manager import MemoryManager, get_memory_manager

router = APIRouter()


@router.get("/sessions")
async def get_chat_sessions(memory: MemoryManager = Depends(get_memory_manager)):
    return services.list_chat_sessions(memory)


@router.get("/session/{session_id}")
async def get_chat_session(
    session_id: str,
    memory: MemoryManager = Depends(get_memory_manager),
):
    return services.get_chat_session(session_id, memory)


@router.post("/session")
async def create_chat_session(body: dict = Body(default={})):
    label = body.get("label", "browser")
    return services.create_chat_session(label=label)


@router.delete("/session/{session_id}")
async def delete_chat_session(
    session_id: str,
    memory: MemoryManager = Depends(get_memory_manager),
):
    return services.delete_chat_session(session_id, memory)


@router.post("/message")
async def post_chat_message(
    body: dict = Body(...),
    memory: MemoryManager = Depends(get_memory_manager),
    service: AgentService = Depends(get_agent_service),
):
    session_id = body.get("session_id")
    text = (body.get("message") or "").strip()
    message_timestamp = body.get("message_timestamp")
    context = body.get("context")
    anchor_node_id = body.get("anchor_node_id")
    client_msg_id = body.get("client_msg_id")

    if not session_id:
        return {"ok": False, "error": "Missing session_id"}
    if not text:
        return {"ok": False, "error": "Empty message"}

    return await services.send_chat_message(
        app_id="chat",
        user_id="web_user",
        session_id=session_id,
        text=text,
        memory=memory,
        service=service,
        message_timestamp=message_timestamp,
        context=context,
        anchor_node_id=anchor_node_id,
        client_msg_id=client_msg_id,
    )
