"""Contradiction detection between active :Belief nodes (S4.3).

For each "new" belief (created since the last run), find the closest
existing active beliefs by embedding cosine similarity, then ask Gemini
Flash whether each pair actually contradicts each other (similarity alone
fires on paraphrases of the same idea, which we DON'T want labelled as
contradictions).

Confirmed contradictions get a ``CONTRADICTS`` edge written in both
directions (Cypher MERGE keeps it idempotent). Operators see them via
the explorer panel and reconcile through the existing belief tools
(evolve, supersede, or accept the contradiction).

Triggered manually via ``POST /api/explorer/analyze/contradictions``.
Auto-scheduling (nightly via the rumination scheduler) is a follow-up.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import uuid
from typing import TYPE_CHECKING

from src.core.config import settings

if TYPE_CHECKING:
    from src.memory.manager import MemoryManager

logger = logging.getLogger(__name__)

_SIMILARITY_FLOOR = 0.6   # below this, don't even ask the LLM
_TOP_K_NEIGHBOURS = 5     # how many candidates to verify per new belief
_CLOUD_MODEL = "gemini-2.5-flash"

_SYSTEM_PROMPT = """\
You are checking whether two beliefs CONTRADICT each other.

Definition: two beliefs contradict if accepting both as simultaneously true
would be incoherent for the same person. Paraphrases of the same idea do
NOT contradict. Beliefs that differ in scope, intensity, or context do not
contradict unless they are mutually exclusive.

Return JSON only: {"contradicts": true|false, "reason": "<one sentence>"}
"""


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _ask_contradiction(text_a: str, text_b: str) -> dict | None:
    """Single Gemini call. Returns the parsed JSON or None on failure."""
    try:
        from google import genai
    except ImportError:
        return None
    api_key = (settings.google_api_keys or "").split(",")[0].strip()
    if not api_key:
        return None
    try:
        client = genai.Client(api_key=api_key)
        prompt = (
            f"Belief A: {text_a}\nBelief B: {text_b}\n\n"
            "Do these contradict?"
        )
        response = client.models.generate_content(
            model=_CLOUD_MODEL,
            contents=prompt,
            config={
                "system_instruction": _SYSTEM_PROMPT,
                "response_mime_type": "application/json",
                "temperature": 0.0,
            },
        )
        raw = (getattr(response, "text", "") or "").strip()
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            return None
        return parsed
    except Exception as e:
        logger.debug("contradiction check failed: %s", e)
        return None


def _detect_sync(memory: "MemoryManager", *, since: str | None = None) -> dict:
    """Sync core. ``since`` is an ISO timestamp; new beliefs are those whose
    ``created_at >= since``. If None, runs over all active beliefs."""
    run_id = f"contradiction_{uuid.uuid4().hex[:12]}"
    all_beliefs = memory.list_active_beliefs(limit=2000)
    if len(all_beliefs) < 2:
        return {"ok": True, "run_id": run_id, "pairs_checked": 0, "links_written": 0}

    new_beliefs = (
        [b for b in all_beliefs if (b.get("created_at") or "") >= since]
        if since else all_beliefs
    )
    if not new_beliefs:
        return {"ok": True, "run_id": run_id, "pairs_checked": 0, "links_written": 0}

    # Embed every active belief; pairwise similarity is cheap on a few hundred.
    try:
        from src.memory.embeddings.google import get_embedding_model
        embedder = get_embedding_model()
        contents = [b.get("content", "") for b in all_beliefs]
        vectors = embedder.embed_documents(contents)
    except Exception as e:
        logger.warning("contradiction: embedding failed: %s", e)
        return {"ok": False, "error": "embedding_failed", "run_id": run_id}

    by_id = {b["id"]: (b, vectors[i]) for i, b in enumerate(all_beliefs)}
    pairs_checked = 0
    links_written = 0
    already_examined: set[tuple[str, str]] = set()

    for new_belief in new_beliefs:
        new_id = new_belief["id"]
        new_vec = by_id[new_id][1]
        scored: list[tuple[float, dict]] = []
        for other in all_beliefs:
            if other["id"] == new_id:
                continue
            sim = _cosine(new_vec, by_id[other["id"]][1])
            if sim >= _SIMILARITY_FLOOR:
                scored.append((sim, other))
        scored.sort(key=lambda t: t[0], reverse=True)

        for sim, other in scored[:_TOP_K_NEIGHBOURS]:
            pair_key = tuple(sorted([new_id, other["id"]]))
            if pair_key in already_examined:
                continue
            already_examined.add(pair_key)
            pairs_checked += 1
            verdict = _ask_contradiction(
                new_belief.get("content", ""),
                other.get("content", ""),
            )
            if not verdict or not verdict.get("contradicts"):
                continue
            reason = (verdict.get("reason") or "").strip()[:200]
            if memory.link_contradiction(
                pair_key[0], pair_key[1], reason=reason, similarity=sim, run_id=run_id
            ):
                links_written += 1

    logger.info(
        "%s: examined %d pair(s), wrote %d CONTRADICTS edge(s)",
        run_id, pairs_checked, links_written,
    )
    return {
        "ok": True, "run_id": run_id,
        "pairs_checked": pairs_checked,
        "links_written": links_written,
        "new_beliefs_count": len(new_beliefs),
    }


async def run_contradiction_detection(
    memory: "MemoryManager", *, since: str | None = None
) -> dict:
    """Run a contradiction sweep over active beliefs, off the event loop."""
    return await asyncio.to_thread(_detect_sync, memory, since=since)
