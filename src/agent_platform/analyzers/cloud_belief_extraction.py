"""Cloud-LLM belief extraction (S3.4).

The local pass (``graph_extraction``) handles structural facts — entities,
tasks, edges — which the 4B model is reliable on. Beliefs need richer
subjective reasoning, so they're routed here, where Gemini Flash does
the extraction.

Triggered manually via ``POST /api/explorer/analyze/beliefs/extract``.
A future ticket will auto-trigger it once a configurable number of
``belief_candidate`` rows have accumulated, but doing it on demand for
now keeps cloud spend predictable.

Pipeline contract:
  1. Pull rows from Chroma where ``belief_candidate: true``.
  2. Run Gemini Flash with a belief-only prompt.
  3. Pass the produced intents to ``graph_write``. The standard
     isolation guard + reachability sweep apply, same as every other
     write path.
  4. Mark the consumed rows ``belief_processed: true`` and clear the
     candidate flag iff the write succeeded.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import TYPE_CHECKING

from src.agent_platform.tools.graph_write import graph_write
from src.core.config import settings

if TYPE_CHECKING:
    from src.memory.manager import MemoryManager

logger = logging.getLogger(__name__)

_CLOUD_MODEL = "gemini-2.5-flash"

_SYSTEM_PROMPT = """\
You extract durable BELIEFS from conversation transcripts and return JSON.

A belief is a stable opinion, preference, value, or generalization the user
holds. Not facts about the world ("Paris is in France") and not transient
moods ("I'm tired today"). Things like:
  - "I prefer mornings to evenings"
  - "Mom is the most patient person I know"
  - "Vinyl sounds warmer than digital"

Output schema (return EXACTLY this shape, JSON only):
{"intents": [
  {"kind":"belief",
   "content":"<the belief as a clean first-person statement>",
   "about_entity":"<entity name if the belief is about a specific person/thing, else empty>",
   "confidence":<0.5 speculative, 0.7 implied, 0.9 stated directly>,
   "source_text":"<the verbatim sentence from the transcript>"}
]}

Rules:
- One intent per distinct belief. Merge near-duplicates into the strongest phrasing.
- Skip chitchat, transient moods, and pure facts.
- If about_entity is set, prefer names from "Existing entities" so the belief
  links to the right node. Use empty string if the belief is general / about self.
- Empty output is fine: {"intents":[]}.
"""


def _build_user_prompt(rows: list[dict], schema: dict) -> str:
    convo_lines: list[str] = []
    for row in rows:
        meta = row.get("metadata") or {}
        role = meta.get("role") or "?"
        text = (row.get("text") or "").strip()
        if text:
            convo_lines.append(f"{role}: {text}")
    convo_block = "\n".join(convo_lines) or "(empty)"

    entity_samples = (schema.get("entities") or [])[:25]
    entity_lines = []
    for ent in entity_samples:
        name = ent.get("name")
        labels = ent.get("labels") or []
        if name:
            entity_lines.append(f"  - {name} ({', '.join(labels) or 'Entity'})")
    entity_block = "\n".join(entity_lines) or "  (none yet)"

    return (
        "Conversation:\n"
        f"{convo_block}\n\n"
        f"Existing entities:\n{entity_block}\n"
    )


def _parse_response(raw: str) -> list[dict]:
    if not raw or not raw.strip():
        return []
    cleaned = raw.strip()
    # Gemini sometimes wraps JSON in a ```json fence even with JSON mode.
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```", 2)[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.warning("cloud_belief_extraction: non-JSON response (%s): %r", e, raw[:200])
        return []
    if not isinstance(parsed, dict):
        return []
    intents = parsed.get("intents")
    if not isinstance(intents, list):
        return []
    return [i for i in intents
            if isinstance(i, dict) and i.get("kind") == "belief"]


def _call_gemini_sync(system_prompt: str, user_prompt: str) -> str:
    """Issue the Gemini Flash call. Sync; wrap in to_thread when awaiting."""
    try:
        from google import genai
    except ImportError as e:
        logger.error("google.genai not installed; can't run belief extraction: %s", e)
        return ""

    api_key = (settings.google_api_keys or "").split(",")[0].strip()
    if not api_key:
        logger.error("cloud_belief_extraction: no GOOGLE_API_KEY configured")
        return ""

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=_CLOUD_MODEL,
            contents=user_prompt,
            config={
                "system_instruction": system_prompt,
                "response_mime_type": "application/json",
                "temperature": 0.2,
            },
        )
        return getattr(response, "text", "") or ""
    except Exception as e:
        logger.warning("cloud_belief_extraction: Gemini call failed: %s", e)
        return ""


async def extract_beliefs(rows: list[dict], schema: dict) -> list[dict]:
    """Run belief extraction off the event loop. Returns list of belief intents."""
    if not rows:
        return []
    user_prompt = _build_user_prompt(rows, schema)
    raw = await asyncio.to_thread(_call_gemini_sync, _SYSTEM_PROMPT, user_prompt)
    return _parse_response(raw)


async def run_belief_extraction_once(
    memory: "MemoryManager", *, batch_size: int = 25
) -> dict:
    """Drain a batch of belief_candidate rows through Gemini Flash.

    Returns a stats dict for the explorer endpoint to surface.
    """
    run_id = f"belief_extract_{uuid.uuid4().hex[:12]}"
    try:
        rows = memory.list_belief_candidates(limit=batch_size)
    except Exception:
        logger.exception("%s: list_belief_candidates failed", run_id)
        return {"ok": False, "error": "list_belief_candidates failed", "run_id": run_id}

    if not rows:
        return {"ok": True, "run_id": run_id, "rows": 0, "intents": 0, "written": 0}

    schema = _safe_schema(memory)
    row_ids = [r["id"] for r in rows if r.get("id")]

    try:
        intents = await extract_beliefs(rows, schema)
    except Exception:
        logger.exception("%s: extraction crashed", run_id)
        return {"ok": False, "error": "extraction crashed", "run_id": run_id}

    if not intents:
        logger.info("%s: 0 belief intents from %d rows; clearing candidate flag", run_id, len(row_ids))
        _mark_processed(memory, row_ids, run_id)
        return {"ok": True, "run_id": run_id, "rows": len(row_ids), "intents": 0, "written": 0}

    result = graph_write(intents)
    if result.get("ok"):
        logger.info(
            "%s: wrote %d belief node(s); clearing candidate flag on %d rows",
            run_id, len(result.get("nodes_written", [])), len(row_ids),
        )
        _mark_processed(memory, row_ids, run_id)
        return {
            "ok": True, "run_id": run_id, "rows": len(row_ids),
            "intents": len(intents),
            "written": len(result.get("nodes_written", [])),
        }
    logger.warning(
        "%s: graph_write rejected (error=%s); leaving candidate flag",
        run_id, result.get("error"),
    )
    return {
        "ok": False, "run_id": run_id, "rows": len(row_ids),
        "intents": len(intents), "written": 0,
        "error": result.get("error"),
    }


def _safe_schema(memory: "MemoryManager") -> dict:
    try:
        return memory.graph_schema_snapshot()
    except Exception:
        return {"labels": [], "relationship_types": [], "entities": []}


def _mark_processed(memory: "MemoryManager", ids: list[str], run_id: str) -> None:
    if not ids:
        return
    try:
        memory.mark_belief_candidates_processed(ids, run_id=run_id)
    except Exception:
        logger.exception("%s: mark_belief_candidates_processed failed", run_id)
