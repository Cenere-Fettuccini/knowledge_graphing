from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.api.routes import router as legacy_api_router
from src.apps.chat.app import get_chat_app
from src.apps.credits.app import get_credits_app
from src.apps.explorer.app import get_explorer_app
from src.apps.financial_manager.app import get_financial_manager_app
from src.apps.routine_scheduler.app import get_routine_scheduler_app
from src.core.logging_config import setup_logging
from src.platform.registry import AppRegistry
from src.platform.shell import build_shell_router


def build_registry() -> AppRegistry:
    registry = AppRegistry()
    for app_factory in (
        get_explorer_app,
        get_chat_app,
        get_credits_app,
        get_financial_manager_app,
        get_routine_scheduler_app,
    ):
        registry.register(app_factory())
    return registry


def create_platform_app() -> FastAPI:
    setup_logging()

    registry = build_registry()
    app = FastAPI(title="AIManager App Platform")
    app.state.app_registry = registry

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(build_shell_router(registry))
    app.include_router(legacy_api_router, prefix="/api")
    app.mount(
        "/shell-assets",
        StaticFiles(directory=str(Path(__file__).resolve().parents[1] / "explorer")),
        name="shell-assets",
    )

    for app_def in registry.list_apps():
        if app_def.api_router and app_def.api_prefix:
            app.include_router(app_def.api_router, prefix=app_def.api_prefix)

        if app_def.static_dir:
            app.mount(
                app_def.route_prefix,
                StaticFiles(directory=str(app_def.static_dir), html=True),
                name=f"{app_def.id}-ui",
            )
            for legacy_route_prefix in app_def.legacy_route_prefixes:
                app.mount(
                    legacy_route_prefix,
                    StaticFiles(directory=str(app_def.static_dir), html=True),
                    name=f"{app_def.id}-legacy-{legacy_route_prefix.strip('/').replace('/', '-') or 'root'}",
                )

    return app
