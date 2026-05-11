from __future__ import annotations

from src.agent_platform.analyzers.canonicalize import (
    DEFAULT_BELIEF_THRESHOLD,
    DEFAULT_THRESHOLD,
    BeliefCanonicalizer,
    EntityCanonicalizer,
)
from src.agent_platform.analyzers.knowledge import KnowledgeAnalyzer
from src.agent_platform.public.agent_service import AgentService
from src.ingestion.bulk_importer import BulkImporter
from src.memory.manager import MemoryManager


def _build_analyzer(memory: MemoryManager) -> KnowledgeAnalyzer:
    return KnowledgeAnalyzer(memory=memory)


def _build_canonicalizer(memory: MemoryManager) -> EntityCanonicalizer:
    return EntityCanonicalizer(memory=memory)


def _build_belief_canonicalizer(memory: MemoryManager) -> BeliefCanonicalizer:
    return BeliefCanonicalizer(memory=memory)


def get_graph_overview(memory: MemoryManager, limit: int = 100) -> dict:
    return memory.graph_overview(limit=limit)


def get_node_detail(node_id: str, memory: MemoryManager) -> dict:
    return memory.graph_node_detail(node_id)


def get_node_provenance(node_id: str, memory: MemoryManager) -> dict:
    return memory.graph_node_provenance(node_id)


def get_active_tasks(memory: MemoryManager) -> list[dict]:
    return memory.graph_active_tasks()


def get_belief_trail(belief_id: str, memory: MemoryManager) -> dict:
    return memory.graph_belief_trail(belief_id)


def get_bootstrap_status(memory: MemoryManager) -> dict:
    user = memory.get_user_root()
    return {"initialized": user is not None, "user": user}


def bootstrap_user(name: str, memory: MemoryManager) -> dict:
    if not name or not name.strip():
        raise ValueError("name must be a non-empty string")
    user = memory.bootstrap_user_root(name.strip())
    return {"user": user}


def get_analyzer_status(memory: MemoryManager) -> dict:
    analyzer = _build_analyzer(memory)
    return analyzer.queue_status()


def list_analyzer_models(memory: MemoryManager) -> list[dict]:
    analyzer = _build_analyzer(memory)
    return analyzer.list_available_models()


def run_analyzer(
    memory: MemoryManager,
    *,
    batch_size: int = 20,
    model: str | None = None,
) -> dict:
    analyzer = _build_analyzer(memory)
    result = analyzer.analyze_pending(batch_size=batch_size, model=model)
    return result.as_dict()


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
