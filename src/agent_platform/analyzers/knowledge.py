"""LLM-driven extraction of durable knowledge from queued conversation turns.

Reads ``analyzed: false`` rows from Chroma, asks an LLM to distil entities and
relationships about the user's world, and writes the result into Neo4j anchored
to the ``:Person:User`` root. Designed to run on triggers (manual, scheduled,
post-bulk-ingest) — not synchronously on every message.

The analyzer never deletes graph data. New labels and relationship types
proposed by the LLM are accepted on first sighting; pruning happens
elsewhere (manual delete in the explorer panel, or a future consolidation
pass).
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from src.agent_platform.analyzers.local_llm import (
    LMStudioClient,
    LocalLLMUnavailable,
)
from src.memory.protocol import MemoryProtocol

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are a knowledge graph analyst.

Read the supplied batch of conversation turns between a user and an assistant.
Your job is to extract durable facts about the user, the people they know,
their preferences, opinions, plans, jobs, and anything else worth remembering
long-term. Skip greetings, debugging chatter, and transient task discussion.

Anchor everything to the user's root node when possible — for example
``(user)-[:KNOWS]->(:Person {name: "Alice"})``. Implicit signals count: e.g.
"get me the calendar for xyz" implies the user works at xyz.

Reuse existing labels and relationship types when one fits; only invent a new
one when nothing existing applies. Labels are PascalCase singular nouns.
Relationship types are SCREAMING_SNAKE_CASE verbs.

Return STRICT JSON ONLY, with this shape:

{
  "entities": [
    {"id": "<stable slug>", "labels": ["Label1", "Label2"], "name": "...", "props": {...}}
  ],
  "relationships": [
    {"from": "<entity id>", "to": "<entity id>", "type": "TYPE_NAME", "props": {...}}
  ],
  "evidence_chroma_ids": ["<chroma id from input>", ...]
}

If nothing is worth extracting from this batch, return
``{"entities": [], "relationships": [], "evidence_chroma_ids": []}``.
"""


@dataclass
class AnalysisResult:
    run_id: str
    processed_messages: int
    entities_written: int
    relationships_written: int
    skipped: bool = False
    reason: str = ""
    raw_output: str = ""
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "processed_messages": self.processed_messages,
            "entities_written": self.entities_written,
            "relationships_written": self.relationships_written,
            "skipped": self.skipped,
            "reason": self.reason,
            "errors": self.errors,
        }


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return cleaned or "entity"


class KnowledgeAnalyzer:
    """Single-batch LLM analyzer that drains the Chroma queue into Neo4j."""

    def __init__(
        self,
        memory: MemoryProtocol,
        llm: LMStudioClient | None = None,
    ) -> None:
        self._memory = memory
        self._llm = llm or LMStudioClient()

    # ── Public entrypoints ────────────────────────────────────────────────────

    def list_available_models(self) -> list[dict[str, Any]]:
        """Pass-through to LM Studio's ``/v1/models`` for the UI's picker."""
        try:
            return self._llm.list_models()
        except LocalLLMUnavailable as exc:
            logger.warning("Local LLM model listing failed: %s", exc)
            return []

    def queue_status(self) -> dict[str, Any]:
        """Lightweight status — used by the explorer panel to render a badge."""
        return {
            "unanalyzed_count": self._memory.count_unanalyzed(),
            "local_llm_available": self._llm.is_available(),
            "default_model": self._llm.default_model,
        }

    def analyze_pending(
        self,
        *,
        batch_size: int = 20,
        model: str | None = None,
    ) -> AnalysisResult:
        """Process up to ``batch_size`` queued messages in a single LLM call."""
        run_id = uuid.uuid4().hex[:12]

        user_root = self._memory.get_user_root()
        if user_root is None:
            return AnalysisResult(
                run_id=run_id,
                processed_messages=0,
                entities_written=0,
                relationships_written=0,
                skipped=True,
                reason="no_user_root",
            )

        batch = self._memory.list_unanalyzed(limit=batch_size)
        if not batch:
            return AnalysisResult(
                run_id=run_id,
                processed_messages=0,
                entities_written=0,
                relationships_written=0,
                skipped=True,
                reason="queue_empty",
            )

        schema = self._memory.graph_schema_snapshot()
        prompt_messages = self._build_prompt(user_root=user_root, schema=schema, batch=batch)

        try:
            raw = self._llm.chat_completion(prompt_messages, model=model, json_mode=True)
        except LocalLLMUnavailable as exc:
            logger.warning("Analyzer skipped — local LLM unavailable: %s", exc)
            return AnalysisResult(
                run_id=run_id,
                processed_messages=0,
                entities_written=0,
                relationships_written=0,
                skipped=True,
                reason=f"llm_unavailable: {exc}",
            )

        parsed = self._parse_json(raw)
        if parsed is None:
            return AnalysisResult(
                run_id=run_id,
                processed_messages=0,
                entities_written=0,
                relationships_written=0,
                skipped=True,
                reason="invalid_json_response",
                raw_output=raw,
            )

        result = self._apply_extraction(
            run_id=run_id,
            user_root_id=user_root["id"],
            extraction=parsed,
            batch_ids=[m["id"] for m in batch],
        )
        return result

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _build_prompt(
        self,
        *,
        user_root: dict,
        schema: dict,
        batch: list[dict],
    ) -> list[dict[str, str]]:
        context = {
            "user_root": {
                "id": user_root.get("id"),
                "name": user_root.get("name"),
                "labels": user_root.get("labels") or [user_root.get("label")],
            },
            "graph_schema": {
                "labels": schema.get("labels", []),
                "relationship_types": schema.get("relationship_types", []),
                "sample_entities": schema.get("entities", []),
            },
            "batch": [
                {
                    "chroma_id": row["id"],
                    "role": (row.get("metadata") or {}).get("role"),
                    "timestamp": (row.get("metadata") or {}).get("timestamp"),
                    "session_id": (row.get("metadata") or {}).get("session_id"),
                    "text": row["text"],
                }
                for row in batch
            ],
        }
        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Context (graph state and batch to analyse):\n"
                    + json.dumps(context, ensure_ascii=False, indent=2)
                ),
            },
        ]

    @staticmethod
    def _parse_json(raw: str) -> dict | None:
        if not raw:
            return None
        # Some local models wrap JSON in ```json fences; strip them defensively.
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3].strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as exc:
            logger.warning("Analyzer JSON parse failed: %s", exc)
            return None

    def _apply_extraction(
        self,
        *,
        run_id: str,
        user_root_id: str,
        extraction: dict,
        batch_ids: list[str],
    ) -> AnalysisResult:
        errors: list[str] = []
        id_map: dict[str, str] = {user_root_id: user_root_id}
        entities_written = 0
        relationships_written = 0

        for entity in extraction.get("entities") or []:
            try:
                proposed_id = (entity.get("id") or "").strip()
                name = (entity.get("name") or "").strip()
                labels = [str(label).strip() for label in (entity.get("labels") or []) if label]
                if not name or not labels:
                    continue
                stable_id = proposed_id or self._stable_entity_id(labels[0], name)
                if stable_id == user_root_id:
                    id_map[proposed_id or stable_id] = user_root_id
                    continue
                props = dict(entity.get("props") or {})
                props.setdefault("provenance_run_ids", [])
                if run_id not in props["provenance_run_ids"]:
                    props["provenance_run_ids"] = [*props["provenance_run_ids"], run_id]
                self._memory.upsert_node(
                    node_id=stable_id,
                    labels=labels,
                    name=name,
                    properties=props,
                )
                id_map[proposed_id] = stable_id if proposed_id else stable_id
                id_map[stable_id] = stable_id
                entities_written += 1
            except Exception as exc:  # pragma: no cover - defensive
                errors.append(f"entity {entity.get('id')!r}: {exc}")

        for rel in extraction.get("relationships") or []:
            try:
                src = id_map.get((rel.get("from") or "").strip()) or rel.get("from")
                tgt = id_map.get((rel.get("to") or "").strip()) or rel.get("to")
                rel_type = (rel.get("type") or "").strip()
                if not src or not tgt or not rel_type:
                    continue
                props = dict(rel.get("props") or {})
                props.setdefault("provenance_run_id", run_id)
                if self._memory.upsert_relationship(
                    source_id=src,
                    target_id=tgt,
                    rel_type=rel_type,
                    properties=props,
                ):
                    relationships_written += 1
            except Exception as exc:  # pragma: no cover - defensive
                errors.append(f"relationship {rel.get('type')!r}: {exc}")

        # Mark every Chroma row in the batch as analyzed, regardless of whether
        # the LLM extracted anything from it — empty extraction is a valid
        # answer and we don't want to retry the same turns forever.
        marked = self._memory.mark_analyzed(batch_ids, run_id=run_id)

        return AnalysisResult(
            run_id=run_id,
            processed_messages=marked,
            entities_written=entities_written,
            relationships_written=relationships_written,
            errors=errors,
        )

    @staticmethod
    def _stable_entity_id(primary_label: str, name: str) -> str:
        return f"{_slugify(primary_label)}:{_slugify(name)}"
