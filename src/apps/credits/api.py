from __future__ import annotations

import logging

from fastapi import APIRouter, Body

from src.apps.credits import services

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("")
@router.get("/")
async def get_credits():
    return services.get_credits()


@router.post("/limits/import")
async def import_limits(body: dict = Body(...)):
    try:
        return services.import_limits_text(body.get("text", ""))
    except Exception as e:
        logger.exception("Failed to import AI Studio limits")
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "matched": []}


@router.get("/mismatches")
async def get_mismatches():
    return services.get_mismatches()
