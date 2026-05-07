"""Compatibility API router that forwards legacy endpoints to app-owned routers."""

from fastapi import APIRouter

from src.apps.chat.api import router as chat_router
from src.apps.credits.api import router as credits_router
from src.apps.explorer.api import router as explorer_router

router = APIRouter()
router.include_router(explorer_router)
router.include_router(chat_router, prefix="/chat")
router.include_router(credits_router, prefix="/credits")
