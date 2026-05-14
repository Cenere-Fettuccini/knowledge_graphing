"""Local-LLM extraction: raw conversation turns -> graph_write Intent dicts.

Drives the count-triggered ingestion path (S0.6b). LM Studio + Gemma 4 is
the production target; any OpenAI-compatible local server will work as
long as it honours ``response_format={"type":"json_object"}``.

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


_SYSTEM_PROMPT = """\
You extract durable graph facts from conversation transcripts and return them as JSON.

Output schema (return EXACTLY this shape, JSON only, no prose):
{"intents": [<intent>, <intent>, ...]}

Each <intent> is one of:
  {"kind":"entity","name":"<str>","label":"<PascalCase>","description":"<str>"}
  {"kind":"belief","content":"<str>","about_entity":"<str?>","confidence":<0-1>}
  {"kind":"task","title":"<str>","due_date":"<YYYY-MM-DD?>","priority":"low|normal|high","for_person":"<str?>","about_entity":"<str?>"}
  {"kind":"edge","source":"<entity name>","target":"<entity name>","rel_type":"<UPPER_SNAKE>"}

Rules:
- Every new entity MUST appear as the source or target of at least one edge in the same batch; otherwise it will be rejected.
- Reuse names from the "Existing entities" list when the same concept appears.
- Skip chitchat and ephemeral state. Extract only durable facts (people, places, projects, preferences, tasks, beliefs).
- Confidence: 0.9 if the user states it directly, 0.7 if implied, 0.5 if speculative.
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
    # Filter out anything that isn't a dict with a string kind — the
    # downstream Pydantic validation will catch the rest.
    return [i for i in intents if isinstance(i, dict) and isinstance(i.get("kind"), str)]


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
