from __future__ import annotations

from pathlib import Path

from src.apps.chat.api import router as chat_api_router
from src.platform.registry import AppDefinition


def get_chat_app() -> AppDefinition:
    return AppDefinition(
        id="chat",
        name="Chat",
        description="A dedicated conversational surface that will consume the shared agent platform.",
        route_prefix="/apps/chat",
        static_dir=Path(__file__).resolve().parent / "static",
        api_prefix="/api/chat-app",
        api_router=chat_api_router,
        icon="Chat",
        status="active",
    )
