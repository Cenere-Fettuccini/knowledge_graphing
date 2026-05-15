"""Shared-secret HTTP entry point for batch graph writes.

Chat-API callers reach the graph via the in-process ``graph_write`` agent
tool. Bulk / programmatic ingestion (the count-triggered job, future
backfill scripts, anything outside the agent loop) uses this route
instead. The shared secret is the only auth — this is a single-user
local app, not a multi-tenant service.

If ``settings.graph_ingest_secret`` is empty the endpoint is registered
but every request returns 503; that's the "feature flag off" state so
forgetting to set the env var doesn't silently expose an unauthenticated
write path.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, Field

from src.agent_platform.tools.graph_write import graph_write
from src.core.config import settings

logger = logging.getLogger(__name__)


class IngestRequest(BaseModel):
    intents: list[dict] = Field(default_factory=list)


def build_graph_ingest_router() -> APIRouter:
    router = APIRouter(prefix="/graph", tags=["graph-ingest"])

    @router.post("/ingest")
    def ingest(
        body: IngestRequest,
        x_graph_ingest_secret: str | None = Header(default=None),
    ) -> dict:
        expected = settings.graph_ingest_secret
        if not expected:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="graph_ingest_secret is not configured",
            )
        if not x_graph_ingest_secret or x_graph_ingest_secret != expected:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid or missing X-Graph-Ingest-Secret",
            )

        result = graph_write(body.intents)
        logger.info(
            "graph_ingest: %d intents -> ok=%s nodes=%d edges=%d quarantined=%d",
            len(body.intents),
            result.get("ok"),
            len(result.get("nodes_written", [])),
            len(result.get("edges_written", [])),
            result.get("quarantined", 0),
        )
        return result

    return router
