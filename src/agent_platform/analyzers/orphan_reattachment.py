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

if TYPE_CHECKING:
    from src.memory.manager import MemoryManager

logger = logging.getLogger(__name__)

_CONFIDENCE_FLOOR = 0.55
_MAX_ORPHANS_PER_SWEEP = 10  # cap to bound Gemini spend per commit

_SYSTEM_PROMPT = """\
You connect a SUBJECT node in a knowledge graph to another entity that is \
semantically related to it.

You are given:
- The SUBJECT node's properties (id, labels, name, description/content)
- Conversation excerpts where the subject was mentioned (RAG context)
- A CANDIDATES list of other entities currently in the graph (subject excluded)
- Existing relationship types already used in the graph

Return JSON only:
{
  "target_name": "<exact name from CANDIDATES, or null if no good match>",
  "rel_type": "<UPPER_SNAKE_CASE>",
  "direction": "from_subject",
  "confidence": <0.5–0.9>,
  "reasoning": "<one sentence explaining the connection>"
}

Rules:
- "target_name" MUST be a name that appears in CANDIDATES. Never invent a new
  name. Never echo the subject's own name. Return null if nothing in CANDIDATES
  fits the conversation context.
- "direction" is "from_subject" (SUBJECT -[rel]-> TARGET) unless the \
  relationship is clearly one where the target acts on the subject, in which \
  case use "to_subject" (TARGET -[rel]-> SUBJECT).
- Reuse a rel_type from "Existing rel-types" when one fits; otherwise invent \
  an UPPER_SNAKE_CASE type that precisely names the relationship.
- confidence: 0.5 = plausible guess, 0.7 = implied by context, 0.9 = explicit.
- Prefer the most semantically specific entity over the generic user root.
- If the subject IS the user root (is_root property true), return target_name null.
"""


def _build_prompt(orphan: dict, context_turns: list[dict], schema: dict) -> str:
    labels = ", ".join(orphan.get("labels") or []) or "unknown"
    name = orphan.get("name") or orphan.get("content") or "(unnamed)"
    description = orphan.get("description") or orphan.get("content") or ""

    orphan_block = (
        f"SUBJECT node:\n"
        f"  id: {orphan.get('id', '?')}\n"
        f"  labels: {labels}\n"
        f"  name: {name}\n"
        f"  description: {description or '(none)'}\n"
    )

    if context_turns:
        convo_lines = []
        for t in context_turns[:15]:
            meta = t.get("metadata") or {}
            role = meta.get("role") or "?"
            text = (t.get("text") or "").strip()
            if text:
                convo_lines.append(f"  {role}: {text}")
        convo_block = "Conversation context (RAG):\n" + "\n".join(convo_lines)
    else:
        convo_block = "Conversation context (RAG): (none found)"

    # Filter the orphan itself out of the candidate list so the model can't
    # propose a self-loop. Match on id first (authoritative); fall back to a
    # case-insensitive name match for safety.
    orphan_id = orphan.get("id")
    orphan_name_lc = (orphan.get("name") or "").strip().lower()
    entities = schema.get("entities") or []
    entity_lines = []
    for e in entities:
        e_name = e.get("name")
        if not e_name:
            continue
        if orphan_id and e.get("id") == orphan_id:
            continue
        if orphan_name_lc and e_name.strip().lower() == orphan_name_lc:
            continue
        entity_lines.append(f"  - {e_name} [{', '.join(e.get('labels') or [])}]")
    entity_block = "CANDIDATES (the subject is excluded):\n" + ("\n".join(entity_lines) or "  (none)")

    rel_types = schema.get("relationship_types") or []
    rel_block = "Existing rel-types: " + (", ".join(rel_types) or "(none)")

    return "\n\n".join([orphan_block, convo_block, entity_block, rel_block])


def _call_lm_studio(system_prompt: str, user_prompt: str) -> dict | None:
    from src.agent_platform.analyzers.local_llm import (
        LMStudioClient,
        LocalLLMUnavailable,
    )

    try:
        client = LMStudioClient()
        raw = client.chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            json_mode=True,
        )
    except LocalLLMUnavailable as e:
        logger.warning("orphan_reattachment: LM Studio unavailable: %s", e)
        return None

    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning("orphan_reattachment: non-JSON response (%s): %r", e, raw[:200])
        return None
    return parsed if isinstance(parsed, dict) else None


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
            context_turns = memory.search(search_query, k=15)
        except Exception as e:
            logger.debug("orphan_reattachment: search failed for %s: %s", orphan_id, e)
            context_turns = []

        # Build prompt and call the LLM.
        user_prompt = _build_prompt(orphan, context_turns, schema)
        proposal = _call_lm_studio(_SYSTEM_PROMPT, user_prompt)

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
        # Accept both new ("from_subject"/"to_subject") and legacy
        # ("from_orphan"/"to_orphan") direction values for back-compat.
        direction_raw = (proposal.get("direction") or "from_subject").lower()
        direction = "to_orphan" if direction_raw in ("to_subject", "to_orphan") else "from_orphan"
        reasoning = (proposal.get("reasoning") or "").strip()

        if not target_name or confidence < _CONFIDENCE_FLOOR or not rel_type:
            logger.info(
                "orphan_reattachment: low-confidence or null proposal for %s (%s) "
                "[confidence=%.2f, target=%r] — will retry next sweep",
                orphan_id, orphan_name, confidence, target_name,
            )
            unresolved.append({"id": orphan_id, "name": orphan_name})
            continue

        # Reject self-loops: the orphan cannot reattach to itself even if the
        # model returns its own name as the target.
        if target_name.strip().lower() == (orphan_name or "").strip().lower():
            logger.info(
                "orphan_reattachment: rejecting self-loop proposal for %s (%s) — "
                "target_name == orphan name; will retry next sweep",
                orphan_id, orphan_name,
            )
            unresolved.append({"id": orphan_id, "name": orphan_name})
            continue

        target_id = _resolve_target_id(target_name, schema_entities)
        if target_id == orphan_id:
            logger.info(
                "orphan_reattachment: resolved target == orphan for %s (%s) — "
                "rejecting self-loop; will retry next sweep",
                orphan_id, orphan_name,
            )
            unresolved.append({"id": orphan_id, "name": orphan_name})
            continue
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
