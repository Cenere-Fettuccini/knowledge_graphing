"""Local-LLM extraction: raw conversation turns -> graph_write Intent dicts.

Drives the count-triggered ingestion path (S0.6b). LM Studio + Gemma 4 is
the production target; any OpenAI-compatible local server will work as
long as it honours ``response_format={"type":"json_schema"}``.

Design notes:

- The prompt is intentionally short and includes one worked example.
  Small local models (3-4B) lose precision with long instructions.
- We pass a schema snapshot (existing labels + named entities) so the
  model reuses what's already in the graph instead of inventing parallel
  labels or duplicating nodes that will then need canonicalization.
- We do NOT ask the model to invent stable ids — node identity is by
  ``name`` and the resolver downstream handles dedup against the graph.
- Bad / empty extractions return ``[]`` so the caller can still mark
  the rows analyzed (otherwise the trigger would spin forever on the
  same untargeted backlog).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from src.agent_platform.analyzers.local_llm import (
    LMStudioClient,
    LocalLLMUnavailable,
)

logger = logging.getLogger(__name__)


# S3.4: belief intents are NOT extracted here. The local 4B model is a
# quality bottleneck on subjective content; beliefs are routed to a
# separate cloud pass (cloud_belief_extraction.py). This pass focuses on
# structural facts the small model handles reliably.
_SYSTEM_PROMPT = """\
You extract durable graph facts from conversation transcripts and return them as JSON.

Output schema (return EXACTLY this shape, JSON only, no prose):
{"intents": [<intent>, <intent>, ...]}

Each <intent> is one of:
  {"kind":"entity","name":"<str>","label":"<PascalCase>","description":"<str>"}
  {"kind":"task","title":"<str>","due_date":"<YYYY-MM-DD?>","priority":"low|normal|high","for_person":"<str?>","about_entity":"<str?>"}
  {"kind":"edge","source":"<entity name>","target":"<entity name>","rel_type":"<UPPER_SNAKE>"}

Rules:
- Do NOT emit "belief" intents. Beliefs are handled by a separate pass.
- Every new entity MUST appear as the source or target of at least one edge in the same batch; otherwise it will be rejected.
- A new Person MUST be connected to at least one other Person through an interpersonal edge (FAMILY_OF, FRIEND_OF, COLLEAGUE_OF, PARTNER_OF, KNOWS, …). Use the most specific edge you can justify from the conversation.
- A new Task MUST connect to the entity it relates to via "for_person" (the person it's for) and/or "about_entity" (the thing it's about). Tasks are NOT owned by the user — they hang off the entity they concern.
- Reuse names from the "Existing entities" list when the same concept appears.
- Skip chitchat. Extract only durable structural facts (people, places, projects, items, tasks, relationships).
- Empty output is fine when nothing durable was said: {"intents": []}.

Example
Conversation:
  user: I want to bake my mom a birthday cake next Saturday.
Schema:
  Existing entities: Kevin (User)
Output:
{"intents":[
  {"kind":"entity","name":"Mom","label":"Person","description":"Kevin's mother"},
  {"kind":"entity","name":"Birthday Cake","label":"Item","description":"For Mom's birthday"},
  {"kind":"edge","source":"Kevin","target":"Mom","rel_type":"FAMILY_OF"},
  {"kind":"edge","source":"Mom","target":"Birthday Cake","rel_type":"WANTS"},
  {"kind":"task","title":"Bake Mom's birthday cake","priority":"normal","for_person":"Mom","about_entity":"Birthday Cake"}
]}
"""


def _build_user_prompt(rows: list[dict], schema: dict) -> str:
    convo_lines: list[str] = []
    for row in rows:
        meta = row.get("metadata") or {}
        role = meta.get("role") or "?"
        text = (row.get("text") or "").strip()
        if not text:
            continue
        convo_lines.append(f"{role}: {text}")
    convo_block = "\n".join(convo_lines) or "(empty)"

    entity_samples = schema.get("entities") or []
    entity_lines = []
    for ent in entity_samples[:25]:
        name = ent.get("name")
        labels = ent.get("labels") or []
        if not name:
            continue
        entity_lines.append(f"  - {name} ({', '.join(labels) or 'Entity'})")
    entity_block = "\n".join(entity_lines) or "  (none yet)"

    rels = schema.get("relationship_types") or []
    rel_block = ", ".join(rels[:20]) if rels else "(none yet)"

    return (
        "Conversation:\n"
        f"{convo_block}\n\n"
        "Schema:\n"
        f"  Existing entities:\n{entity_block}\n"
        f"  Existing relationship types: {rel_block}\n"
    )


def _parse_response(raw: str) -> list[dict]:
    if not raw or not raw.strip():
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning("graph_extraction: LLM returned non-JSON (%s): %r", e, raw[:200])
        return []
    if not isinstance(parsed, dict):
        return []
    intents = parsed.get("intents")
    if not isinstance(intents, list):
        return []
    # Filter out anything that isn't a dict with a string kind, and drop
    # any "belief" the model emitted despite the instruction — those go
    # through cloud_belief_extraction instead.
    cleaned: list[dict] = []
    for i in intents:
        if not isinstance(i, dict):
            continue
        kind = i.get("kind")
        if not isinstance(kind, str):
            continue
        if kind == "belief":
            logger.debug("graph_extraction: dropping local-pass belief intent")
            continue
        cleaned.append(i)
    return cleaned


def _extract_intents_sync(
    rows: list[dict], schema: dict, client: LMStudioClient | None = None
) -> list[dict]:
    if not rows:
        return []
    client = client or LMStudioClient()
    user_prompt = _build_user_prompt(rows, schema)
    try:
        raw = client.chat_completion(
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            json_mode=True,
        )
    except LocalLLMUnavailable as e:
        logger.warning("graph_extraction: LLM unavailable, skipping: %s", e)
        return []
    return _parse_response(raw)


async def extract_intents(
    rows: list[dict], schema: dict, client: LMStudioClient | None = None
) -> list[dict]:
    """Run the extraction prompt off the event loop.

    Returns a list of Intent dicts ready for ``graph_write``. Empty list
    on any failure path (parse error, LLM unreachable, nothing durable
    in the rows) so the caller can still mark the rows analyzed and
    move on.
    """
    return await asyncio.to_thread(_extract_intents_sync, rows, schema, client)


# ── Edge repair pass ────────────────────────────────────────────────────────
#
# When the main extraction creates an entity but forgets to connect it, we
# don't fall back to a semantic-RAG guess against the whole conversation
# history. Instead we hand the SAME conversation rows back to the model with
# a focused prompt: "you missed these edges, here are the candidates from
# the same batch, propose only edges the conversation actually supports."
#
# This trades one extra small LM Studio call per affected batch for much
# higher precision: the model is reasoning over the exact turns that
# created the node, not similar-looking turns from elsewhere.

_REPAIR_SYSTEM_PROMPT = """\
You are fixing a knowledge-graph extraction that missed some edges.

You are given:
- The original conversation transcript.
- NEEDS_EDGES: entities that were created from this conversation but have no edge yet.
- CANDIDATES: other entities available to connect to (from this batch + the existing graph).
- Existing relationship types already in use.

For each entity in NEEDS_EDGES, propose an edge connecting it to ANOTHER entity (from CANDIDATES or other NEEDS_EDGES — never to itself) using a relationship the conversation literally supports.

Output schema (JSON only):
{"intents": [
  {"kind":"edge","source":"<name>","target":"<name>","rel_type":"<UPPER_SNAKE>"}
]}

Rules:
- Only emit an edge the conversation directly justifies. If the conversation
  does not support a clear connection for an entity, OMIT that entity. Do not
  invent associations from co-occurrence alone (a cake mentioned near a person
  does NOT mean the person LIKES the cake).
- Names must match exactly (case-insensitive) something in NEEDS_EDGES or CANDIDATES.
- Pick the most specific rel_type the conversation supports (FOR, ABOUT,
  WANTS, BAKES_FOR, FAMILY_OF, FRIEND_OF, …). Reuse from "Existing rel-types"
  when one fits.
- Empty output is fine: {"intents":[]}.
"""


def _build_repair_prompt(
    rows: list[dict],
    isolated: list[dict],
    schema: dict,
    nodes_written: list[dict] | None = None,
) -> str:
    convo_lines: list[str] = []
    for row in rows:
        meta = row.get("metadata") or {}
        role = meta.get("role") or "?"
        text = (row.get("text") or "").strip()
        if text:
            convo_lines.append(f"{role}: {text}")
    convo_block = "\n".join(convo_lines) or "(empty)"

    needs_lines = []
    isolated_names = {(i.get("name") or "").strip().lower() for i in isolated}
    for i in isolated:
        n = i.get("name")
        if n:
            needs_lines.append(f"  - {n}")
    needs_block = "\n".join(needs_lines) or "  (none)"

    # Candidates = everything else this batch created + a sample from the graph.
    cand_lines = []
    if nodes_written:
        for n in nodes_written:
            name = n.get("name") or n.get("title")
            if not name:
                continue
            if name.strip().lower() in isolated_names:
                continue
            cand_lines.append(f"  - {name} (this batch)")
    for ent in (schema.get("entities") or [])[:25]:
        name = ent.get("name")
        if not name or name.strip().lower() in isolated_names:
            continue
        labels = ", ".join(ent.get("labels") or []) or "Entity"
        cand_lines.append(f"  - {name} ({labels})")
    cand_block = "\n".join(cand_lines) or "  (none)"

    rels = schema.get("relationship_types") or []
    rel_block = ", ".join(rels[:20]) if rels else "(none yet)"

    return (
        "Conversation:\n"
        f"{convo_block}\n\n"
        "NEEDS_EDGES (entities created from this conversation, missing an edge):\n"
        f"{needs_block}\n\n"
        "CANDIDATES (other entities you may connect to):\n"
        f"{cand_block}\n\n"
        f"Existing relationship types: {rel_block}\n"
    )


def _repair_isolated_sync(
    rows: list[dict],
    isolated: list[dict],
    schema: dict,
    nodes_written: list[dict] | None,
    client: LMStudioClient | None,
) -> list[dict]:
    if not rows or not isolated:
        return []
    client = client or LMStudioClient()
    user_prompt = _build_repair_prompt(rows, isolated, schema, nodes_written)
    try:
        raw = client.chat_completion(
            messages=[
                {"role": "system", "content": _REPAIR_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            json_mode=True,
        )
    except LocalLLMUnavailable as e:
        logger.warning("repair_isolated_nodes: LM Studio unavailable: %s", e)
        return []
    parsed = _parse_response(raw)
    # Keep only edge intents — the repair pass shouldn't be inventing entities.
    return [p for p in parsed if p.get("kind") == "edge"]


async def repair_isolated_nodes(
    rows: list[dict],
    isolated: list[dict],
    schema: dict,
    *,
    nodes_written: list[dict] | None = None,
    client: LMStudioClient | None = None,
) -> list[dict]:
    """Focused re-prompt using the original conversation rows.

    Asks the model to propose edges only for nodes that ended up isolated
    in the just-committed batch. Returns a list of EdgeIntent dicts ready
    for ``graph_write``. Empty list on failure, with the same "skip and
    leave the orphan for the next pass" semantics as the main extractor.
    """
    return await asyncio.to_thread(
        _repair_isolated_sync, rows, isolated, schema, nodes_written, client
    )
