"""FastAPI entry point.

Serves:
  - The Knowledge Graph Explorer at  GET /
  - Graph API routes at              /api/graph/*

Usage:
    uvicorn src.main:app --host 127.0.0.1 --port 8000 --reload
"""

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from src.api.routes import router

logger = logging.getLogger(__name__)

app = FastAPI(title="AIManager", docs_url="/docs")

# ── API routes ────────────────────────────────────────────────────────────────
app.include_router(router, prefix="/api/graph")

# ── Static files (Explorer frontend) ─────────────────────────────────────────
EXPLORER_DIR = Path(__file__).parent / "explorer"

app.mount("/static", StaticFiles(directory=str(EXPLORER_DIR)), name="static")


@app.get("/", include_in_schema=False)
async def serve_explorer():
    return FileResponse(str(EXPLORER_DIR / "index.html"))