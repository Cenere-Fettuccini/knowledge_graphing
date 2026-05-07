from __future__ import annotations

from fastapi import APIRouter

from src.apps.explorer import services

router = APIRouter()


@router.get("/graph/overview")
async def get_overview():
    return services.get_graph_overview()


@router.get("/graph/node/{node_id}")
async def get_node_detail(node_id: str):
    return services.get_node_detail(node_id)


@router.get("/tasks/active")
async def get_active_tasks():
    return services.get_active_tasks()


@router.get("/graph/belief/{belief_id}/trail")
async def get_belief_trail(belief_id: str):
    return services.get_belief_trail(belief_id)


@router.get("/system/status")
async def get_system_status():
    return services.get_system_status()
