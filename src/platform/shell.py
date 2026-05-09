from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse, RedirectResponse

from src.platform.registry import AppRegistry


def build_shell_router(registry: AppRegistry) -> APIRouter:
    router = APIRouter()

    @router.get("/")
    async def platform_home() -> RedirectResponse:
        return RedirectResponse(url="/explorer")

    @router.get("/platform/apps")
    async def list_platform_apps() -> JSONResponse:
        payload = [
            {
                "id": app_def.id,
                "name": app_def.name,
                "description": app_def.description,
                "route_prefix": app_def.route_prefix,
                "api_prefix": app_def.api_prefix,
                "section_role": app_def.section_role,
                "status": app_def.status,
            }
            for app_def in registry.list_apps()
        ]
        return JSONResponse({"apps": payload})

    return router
