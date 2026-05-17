from __future__ import annotations

import asyncio
import logging

from src.agent_platform.analyzers import graph_ingest_trigger
from src.agent_platform.analyzers.canonicalize import (
    DEFAULT_BELIEF_THRESHOLD,
    DEFAULT_THRESHOLD,
    BeliefCanonicalizer,
    EntityCanonicalizer,
)
from src.agent_platform.analyzers.local_llm import (
    LMStudioClient,
    LocalLLMUnavailable,
)
from src.agent_platform.public.agent_service import AgentService
from src.ingestion.bulk_importer import BulkImporter
from src.memory.manager import MemoryManager


def _build_canonicalizer(memory: MemoryManager) -> EntityCanonicalizer:
    return EntityCanonicalizer(memory=memory)


def _build_belief_canonicalizer(memory: MemoryManager) -> BeliefCanonicalizer:
    return BeliefCanonicalizer(memory=memory)


def get_graph_overview(
    memory: MemoryManager,
    limit: int = 100,
    *,
    era_id: str | None = None,
    active_self_only: bool = False,
) -> dict:
    return memory.graph_overview(
        limit=limit, era_id=era_id, active_self_only=active_self_only
    )


def get_node_detail(node_id: str, memory: MemoryManager) -> dict:
    return memory.graph_node_detail(node_id)


def get_node_provenance(node_id: str, memory: MemoryManager) -> dict:
    return memory.graph_node_provenance(node_id)


def get_active_tasks(
    memory: MemoryManager,
    *,
    include_completed: bool = False,
    since: str | None = None,
) -> list[dict]:
    return memory.graph_active_tasks(include_completed=include_completed, since=since)


def get_belief_trail(belief_id: str, memory: MemoryManager) -> dict:
    return memory.graph_belief_trail(belief_id)


def get_bootstrap_status(memory: MemoryManager) -> dict:
    if not memory.is_graph_online():
        return {"initialized": None, "user": None, "neo4j_offline": True}
    user = memory.get_user_root()
    return {"initialized": user is not None, "user": user, "neo4j_offline": False}


def bootstrap_user(name: str, memory: MemoryManager) -> dict:
    if not name or not name.strip():
        raise ValueError("name must be a non-empty string")
    user = memory.bootstrap_user_root(name.strip())
    return {"user": user}


def reset_graph(memory: MemoryManager) -> dict:
    """Wipe all Neo4j nodes, reseed the Kevin root, and re-queue all Chroma rows for analysis."""
    root = memory.bootstrap_user_root("Kevin")
    requeued = memory.mark_all_unanalyzed(include_ephemeral=False)
    return {"user": root, "requeued": requeued}


_DRAIN_ROW_CAP = 200            # max rows processed per reset click
_DRAIN_BATCH_SIZE = 5          # rows per LM Studio call
_DRAIN_INTERBATCH_SLEEP = 30.0   # seconds between batches — lets LM Studio breathe


async def drain_after_reset(memory: MemoryManager) -> None:
    """Process a bounded slice of the queue after a reset.

    Capped at ``_DRAIN_ROW_CAP`` rows total (not batches) with a small sleep
    between batches so the local LLM and host don't get pinned by a 1000-call
    burst. Anything beyond the cap drains gradually via the count-based
    trigger on subsequent chat turns.
    """
    from src.agent_platform.analyzers.graph_ingest_trigger import run_extraction_pass

    log = logging.getLogger(__name__)
    processed_total = 0
    while processed_total < _DRAIN_ROW_CAP:
        if memory.count_unanalyzed() <= 0:
            break
        remaining_cap = _DRAIN_ROW_CAP - processed_total
        batch_size = min(_DRAIN_BATCH_SIZE, remaining_cap)
        result = await run_extraction_pass(memory, batch_size=batch_size)
        if result.get("skipped"):
            break
        processed = result.get("processed_messages") or 0
        if not processed:
            break
        processed_total += processed
        if processed_total < _DRAIN_ROW_CAP and memory.count_unanalyzed() > 0:
            await asyncio.sleep(_DRAIN_INTERBATCH_SLEEP)

    log.info(
        "drain_after_reset: processed %d row(s); remaining=%d",
        processed_total,
        memory.count_unanalyzed(),
    )


def get_analyzer_status(memory: MemoryManager) -> dict:
    """Lightweight status for the explorer panel.

    Shape preserved from the legacy ``KnowledgeAnalyzer.queue_status``
    so the frontend doesn't need to change. The values come straight
    from MemoryManager + LMStudioClient — the old analyzer wrapper
    was only ever a thin pass-through here.
    """
    client = LMStudioClient()
    try:
        local_available = client.is_available()
    except Exception:
        local_available = False
    return {
        "unanalyzed_count": memory.count_unanalyzed(),
        "failed_count": memory.count_failed(),
        "local_llm_available": local_available,
        "default_model": client.default_model,
    }


def list_analyzer_models(memory: MemoryManager) -> list[dict]:
    """LM Studio's ``/v1/models`` pass-through for the UI's picker."""
    try:
        return LMStudioClient().list_models()
    except LocalLLMUnavailable:
        return []


async def run_analyzer(
    memory: MemoryManager,
    *,
    batch_size: int = 20,
    model: str | None = None,
) -> dict:
    """Manual one-shot drain — routes through the same pipeline as the
    count-trigger so the manual path can't drift from the auto one.

    ``model`` is accepted for backwards compatibility with the legacy
    KnowledgeAnalyzer signature but currently unused — the extraction
    pass uses ``settings.lm_studio_model``. Wire model-override here
    if the explorer's model-picker needs to work again.
    """
    return await graph_ingest_trigger.run_extraction_pass(
        memory, batch_size=batch_size
    )


def list_analyzer_failures(memory: MemoryManager, limit: int = 50) -> dict:
    """Return the analyzer's dead-letter queue for the explorer panel."""
    items = memory.list_failed(limit=limit)
    return {
        "count": memory.count_failed(),
        "items": [
            {
                "id": row.get("id"),
                "text": row.get("text"),
                "reason": (row.get("metadata") or {}).get("analyzer_failure_reason"),
                "failed_at": (row.get("metadata") or {}).get("analyzer_failed_at"),
                "run_id": (row.get("metadata") or {}).get("analysis_run_id"),
                "session_id": (row.get("metadata") or {}).get("session_id"),
            }
            for row in items
        ],
    }


def retry_analyzer_failures(
    memory: MemoryManager,
    memory_ids: list[str] | None = None,
) -> dict:
    """Reset failed rows so the next analyzer tick picks them up."""
    reset = memory.retry_failed(memory_ids)
    return {"reset": reset, "remaining": memory.count_failed()}


def run_bulk_import(
    memory: MemoryManager,
    *,
    path: str,
    format: str = "jsonl",
    source: str | None = None,
    chunk_size: int = 1000,
    chunk_overlap: int = 100,
) -> dict:
    """Drop a historical archive into Chroma so the analyzer can backfill the graph.

    ``format`` is either ``"jsonl"`` (one row per line, ``text`` key required)
    or ``"directory"`` (recursive walk over ``.txt`` / ``.md`` files, chunked).
    The function never raises on bad input — bad rows / unreadable files are
    counted as skipped and the user sees the totals in the response.
    """
    importer = BulkImporter(memory=memory)
    if format == "jsonl":
        result = importer.import_jsonl(path, source=source)
    elif format == "directory":
        result = importer.import_directory(
            path, chunk_size=chunk_size, chunk_overlap=chunk_overlap,
        )
    else:
        return {
            "imported": 0,
            "skipped": 0,
            "errors": [f"unknown format: {format!r} (expected 'jsonl' or 'directory')"],
            "source_path": path,
        }
    return result.as_dict()


def run_canonicalization(
    memory: MemoryManager,
    *,
    target: str = "entities",
    threshold: float | None = None,
) -> dict:
    """Scan the graph for near-duplicates and write merge proposals.

    ``target`` is ``"entities"`` (default — every label except internal types,
    threshold defaults to 0.92) or ``"beliefs"`` (active :Belief nodes only,
    threshold defaults to 0.88). Both targets write into the same
    :MergeProposal store, so /canonicalize/proposals and /canonicalize/apply
    work uniformly regardless of how the proposal was generated.
    """
    if target == "beliefs":
        canon = _build_belief_canonicalizer(memory)
        return canon.propose_merges(
            threshold=threshold if threshold is not None else DEFAULT_BELIEF_THRESHOLD,
        ).as_dict()
    canon = _build_canonicalizer(memory)
    return canon.propose_merges(
        threshold=threshold if threshold is not None else DEFAULT_THRESHOLD,
    ).as_dict()


def list_merge_proposals(
    memory: MemoryManager,
    *,
    status: str = "pending",
    limit: int = 200,
) -> dict:
    """Return :MergeProposal nodes for the explorer panel."""
    proposals = memory.list_merge_proposals(status=status, limit=limit)
    return {"count": len(proposals), "items": proposals}


def apply_merge_proposal(memory: MemoryManager, proposal_id: str) -> dict:
    """Apply a pending proposal and return the merge stats."""
    stats = memory.apply_merge_proposal(proposal_id)
    return {"proposal_id": proposal_id, **stats}


def dismiss_merge_proposal(memory: MemoryManager, proposal_id: str) -> dict:
    """Mark a pending proposal as dismissed; no graph mutation."""
    ok = memory.dismiss_merge_proposal(proposal_id)
    return {"proposal_id": proposal_id, "dismissed": bool(ok)}


async def get_system_status(memory: MemoryManager, service: AgentService) -> dict:
    memory.invalidate_health_cache()
    health = memory.status()

    quota = await service.aquota_status()
    agent_status = await service.astatus(force=True)
    return {
        "status": health["status"],
        "neo4j": "online" if "online" in health["neo4j"] else "offline",
        "chroma": "online" if "online" in health["chroma"] else "offline",
        "agent": "online" if agent_status.status == "online" else agent_status.status,
        "quota": quota,
        "details": {
            "neo4j": health["neo4j"],
            "chroma": health["chroma"],
            "llm": agent_status.llm,
        },
    }
