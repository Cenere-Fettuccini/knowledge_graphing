from __future__ import annotations

from fastapi import APIRouter, Body

from src.apps.chat import services

router = APIRouter()


@router.get("/sessions")
async def get_chat_sessions():
    return services.list_chat_sessions()


@router.get("/session/{session_id}")
async def get_chat_session(session_id: str):
    return services.get_chat_session(session_id)


@router.post("/session")
async def create_chat_session(body: dict = Body(default={})):
    label = body.get("label", "browser")
    return services.create_chat_session(label=label)


@router.delete("/session/{session_id}")
async def delete_chat_session(session_id: str):
    return services.delete_chat_session(session_id)


@router.post("/message")
async def post_chat_message(body: dict = Body(...)):
    session_id = body.get("session_id")
    text = (body.get("message") or "").strip()
    anchor_node_id = body.get("anchor_node_id")

    if not session_id:
        return {"ok": False, "error": "Missing session_id"}
    if not text:
        return {"ok": False, "error": "Empty message"}

    return await services.send_chat_message(
        app_id="chat",
        user_id="web_user",
        session_id=session_id,
        text=text,
        anchor_node_id=anchor_node_id,
    )
