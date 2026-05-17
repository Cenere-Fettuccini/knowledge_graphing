"""Semantic orphan reattachment (post-commit sweep).

After every successful Neo4j batch commit, ``reattach_orphans()`` is called
with the list of nodes that ``detect_orphans()`` found unreachable from the
user root. Orphans that cannot be placed stay orphaned and are retried on the
next pass — no fallback ``ORPHANED_LINK`` edge is ever written.  For each orphan it:

  1. **RAG** — searches ChromaDB for conversation turns that mention the node,
     providing the LLM with the original context in which the node was created.
  2. **Schema context** — fetches the current graph's entity names + rel-types
     (same snapshot the extraction analyzers use) so the LLM can reuse
     existing vocabulary and target an existing entity.
  3. **Gemini Flash reasoning** — asks the LLM to propose a specific target
     entity and relationship type that semantically connects the orphan back
     into the graph.
  4. **Write** — if the LLM returns a high-confidence proposal that resolves to
     a known node ID, ``memory.upsert_relationship()`` is called.
  5. **Retry** — any orphan the LLM cannot place stays orphaned and will be
     picked up again on the next post-commit sweep.

The whole pass runs synchronously (blocking Gemini calls); it is a post-commit
step and latency here does not affect the write that just completed.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from src.core.config import settings

if TYPE_CHECKING:
    from src.memory.manager import MemoryManager

logger = logging.getLogger(__name__)

_CLOUD_MODEL = "gemini-2.5-flash"
_CONFIDENCE_FLOOR = 0.55
_MAX_ORPHANS_PER_SWEEP = 10  # cap to bound Gemini spend per commit

_SYSTEM_PROMPT = """\
You reconnect an orphaned knowledge-graph node to the most semantically \
appropriate parent node in the graph.

You are given:
- The orphaned node's properties (id, labels, name, description/content)
- Conversation excerpts where this node was mentioned (RAG context)
- Existing graph entities with their names and IDs
- Existing relationship types already used in the graph

Return JSON only:
{
  "target_name": "<exact name from Existing entities, or null if uncertain>",
  "rel_type": "<UPPER_SNAKE_CASE>",
  "direction": "from_orphan",
  "confidence": <0.5–0.9>,
  "reasoning": "<one sentence explaining the connection>"
}

Rules:
- "target_name" MUST be a name from "Existing entities" — never invent a new one.
  Return null if no good match exists.
- "direction" is always "from_orphan" (ORPHAN -[rel]-> TARGET) unless the \
  relationship is clearly one where the target acts on the orphan, in which \
  case use "to_orphan" (TARGET -[rel]-> ORPHAN).
- Reuse a rel_type from "Existing rel-types" when one fits; otherwise invent \
  an UPPER_SNAKE_CASE type that precisely names the relationship.
- confidence: 0.5 = plausible guess, 0.7 = implied by context, 0.9 = explicit.
- Prefer the most semantically specific entity over the generic user root.
- If the orphan IS the user root (is_root property true), return target_name null.
"""


def _build_prompt(orphan: dict, context_turns: list[dict], schema: dict) -> str:
    labels = ", ".join(orphan.get("labels") or []) or "unknown"
    name = orphan.get("name") or orphan.get("content") or "(unnamed)"
    description = orphan.get("description") or orphan.get("content") or ""

    orphan_block = (
        f"Orphaned node:\n"
        f"  id: {orphan.get('id', '?')}\n"
        f"  labels: {labels}\n"
        f"  name: {name}\n"
        f"  description: {description or '(none)'}\n"
    )

    if context_turns:
        convo_lines = []
        for t in context_turns[:5]:
            meta = t.get("metadata") or {}
            role = meta.get("role") or "?"
            text = (t.get("text") or "").strip()
            if text:
                convo_lines.append(f"  {role}: {text}")
        convo_block = "Conversation context (RAG):\n" + "\n".join(convo_lines)
    else:
        convo_block = "Conversation context (RAG): (none found)"

    entities = schema.get("entities") or []
    entity_lines = [
        f"  - {e['name']} [{', '.join(e.get('labels') or [])}]"
        for e in entities
        if e.get("name")
    ]
    entity_block = "Existing entities:\n" + ("\n".join(entity_lines) or "  (none)")

    rel_types = schema.get("relationship_types") or []
    rel_block = "Existing rel-types: " + (", ".join(rel_types) or "(none)")

    return "\n\n".join([orphan_block, convo_block, entity_block, rel_block])


def _call_gemini(system_prompt: str, user_prompt: str) -> dict | None:
    try:
        from google import genai
    except ImportError:
        logger.warning("orphan_reattachment: google.genai not installed")
        return None

    api_key = (settings.google_api_keys or "").split(",")[0].strip()
    if not api_key:
        logger.warning("orphan_reattachment: no GOOGLE_API_KEY configured")
        return None

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
        raw = (getattr(response, "text", "") or "").strip()
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except Exception as e:
        logger.warning("orphan_reattachment: Gemini call failed: %s", e)
        return None


def _resolve_target_id(target_name: str, schema_entities: list[dict]) -> str | None:
    """Find the node ID for target_name from the schema entity sample."""
    target_lower = target_name.strip().lower()
    for entity in schema_entities:
        if (entity.get("name") or "").strip().lower() == target_lower:
            return entity.get("id")
    return None


def reattach_orphans(
    memory: "MemoryManager",
    orphans: list[dict],
    now_iso: str,
) -> dict:
    """Attempt to semantically reattach each orphaned node.

    For each orphan: RAG search → schema context → Gemini Flash proposal →
    ``upsert_relationship`` on success. Unresolved orphans are left in place
    and retried on the next post-commit sweep.

    Returns::

        {
            "reattached": [{"id", "name", "target", "rel_type", "reasoning"}, ...],
            "unresolved": [{"id", "name"}, ...],
        }
    """
    if not orphans:
        return {"reattached": [], "fallback": []}

    capped = orphans[:_MAX_ORPHANS_PER_SWEEP]
    if len(orphans) > _MAX_ORPHANS_PER_SWEEP:
        logger.warning(
            "orphan_reattachment: %d orphans detected, processing first %d",
            len(orphans),
            _MAX_ORPHANS_PER_SWEEP,
        )

    # Fetch schema once for the whole batch.
    try:
        schema = memory.graph_schema_snapshot()
    except Exception as e:
        logger.warning("orphan_reattachment: schema fetch failed: %s", e)
        schema = {"labels": [], "relationship_types": [], "entities": []}

    schema_entities = schema.get("entities") or []
    reattached = []
    unresolved = []

    for orphan in capped:
        orphan_id = orphan.get("id")
        orphan_name = orphan.get("name") or orphan.get("content") or "(unnamed)"

        if not orphan_id:
            logger.warning("orphan_reattachment: skipping orphan with no id: %s", orphan)
            continue

        # RAG: search for conversation turns mentioning this node.
        search_query = " ".join(filter(None, [
            orphan.get("name"),
            orphan.get("description"),
            orphan.get("content"),
        ])).strip() or orphan_name
        try:
            context_turns = memory.search(search_query, k=5)
        except Exception as e:
            logger.debug("orphan_reattachment: search failed for %s: %s", orphan_id, e)
            context_turns = []

        # Build prompt and call the LLM.
        user_prompt = _build_prompt(orphan, context_turns, schema)
        proposal = _call_gemini(_SYSTEM_PROMPT, user_prompt)

        if not proposal:
            logger.info(
                "orphan_reattachment: no proposal for %s (%s) — will retry next sweep",
                orphan_id, orphan_name,
            )
            unresolved.append({"id": orphan_id, "name": orphan_name})
            continue

        target_name = proposal.get("target_name")
        confidence = float(proposal.get("confidence") or 0.0)
        rel_type = (proposal.get("rel_type") or "").strip().upper().replace(" ", "_")
        direction = proposal.get("direction") or "from_orphan"
        reasoning = (proposal.get("reasoning") or "").strip()

        if not target_name or confidence < _CONFIDENCE_FLOOR or not rel_type:
            logger.info(
                "orphan_reattachment: low-confidence or null proposal for %s (%s) "
                "[confidence=%.2f, target=%r] — will retry next sweep",
                orphan_id, orphan_name, confidence, target_name,
            )
            unresolved.append({"id": orphan_id, "name": orphan_name})
            continue

        target_id = _resolve_target_id(target_name, schema_entities)
        if not target_id:
            logger.info(
                "orphan_reattachment: proposed target %r not found in schema for %s — "
                "will retry next sweep",
                target_name, orphan_id,
            )
            unresolved.append({"id": orphan_id, "name": orphan_name})
            continue

        # Write the proposed edge.
        try:
            if direction == "to_orphan":
                memory.upsert_relationship(
                    source_id=target_id,
                    target_id=orphan_id,
                    rel_type=rel_type,
                    properties={"inferred_by": "orphan_reattachment", "reasoning": reasoning},
                )
            else:
                memory.upsert_relationship(
                    source_id=orphan_id,
                    target_id=target_id,
                    rel_type=rel_type,
                    properties={"inferred_by": "orphan_reattachment", "reasoning": reasoning},
                )
            logger.info(
                "orphan_reattachment: reattached %s (%s) -[%s]-> %s [confidence=%.2f] — %s",
                orphan_id, orphan_name, rel_type, target_name, confidence, reasoning,
            )
            reattached.append({
                "id": orphan_id,
                "name": orphan_name,
                "target": target_name,
                "rel_type": rel_type,
                "direction": direction,
                "confidence": confidence,
                "reasoning": reasoning,
            })
        except Exception as e:
            logger.error(
                "orphan_reattachment: write failed for %s -> %s: %s",
                orphan_id, target_id, e,
            )
            unresolved.append({"id": orphan_id, "name": orphan_name})

    if unresolved:
        logger.info(
            "orphan_reattachment: %d node(s) unresolved — will retry on next sweep: %s",
            len(unresolved),
            [u["id"] for u in unresolved],
        )

    return {"reattached": reattached, "unresolved": unresolved}
