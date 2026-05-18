from __future__ import annotations

from pathlib import Path

from src.apps.explorer.api import router as explorer_api_router
from src.platform.registry import AppDefinition


def get_explorer_app() -> AppDefinition:
    return AppDefinition(
        id="explorer",
        name="Explorer",
        description="Knowledge graph, credits, and conversational graph exploration.",
        route_prefix="/apps/explorer",
        section_role="cross_cutting",
        static_dir=Path(__file__).resolve().parents[2] / "frontend" / "shell",
        api_prefix="/api/explorer",
        api_router=explorer_api_router,
        icon="Graph",
        status="active",
        legacy_route_prefixes=("/explorer", "/credits", "/chat", "/financial", "/routine", "/arch", "/architecture", "/flows"),
    )
