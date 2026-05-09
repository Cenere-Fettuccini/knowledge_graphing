from __future__ import annotations

from pathlib import Path

from src.apps.credits.api import router as credits_api_router
from src.platform.registry import AppDefinition


def get_credits_app() -> AppDefinition:
    return AppDefinition(
        id="credits",
        name="Credits",
        description="Platform-wide model limit observability and import workflows.",
        route_prefix="/apps/credits",
        section_role="cross_cutting",
        static_dir=Path(__file__).resolve().parents[2] / "frontend" / "shell",
        api_prefix="/api/credits-app",
        api_router=credits_api_router,
        icon="Credits",
        status="active",
    )
