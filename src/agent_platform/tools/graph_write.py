"""Unified graph write tool.

Single entry point for all graph mutations. Replaces the per-type
intent-queue tools (``store_knowledge``, ``save_belief``, ``create_task``).

Two callers are expected:
  1. Agent tool call from chat — runs synchronously in-process.
  2. ``POST /graph/ingest`` (with shared secret) — runs the same path
     synchronously, used by the count-triggered ingestion job.

This module ships the skeleton: intent types, validation, and the tool
shape. The topological resolver, isolation guard, and reachability sweep
land in subsequent commits (S0.3 / S0.4 / S0.7).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated, Literal, Union

import json

from pydantic import BaseModel, Field, ValidationError

from src.agent_platform.tools.common import ensure_graph_online, logger
from src.core.config import settings
from src.memory.manager import GraphWriteBatch, MemoryManager, get_memory_manager

_ANCHOR_CLOUD_MODEL = "gemini-2.5-flash"

_ANCHOR_SYSTEM_PROMPT = """\
You classify a named entity so it can be added to a personal knowledge graph.

An entity name appears in a relationship but has no matching node yet. Given
the name and the surrounding batch context (what other nodes and edges are
being written at the same time), infer what kind of entity it is and write
a one-sentence description.

Return JSON only:
{
  "label": "<PascalCase label — reuse from Existing labels when one fits>",
  "description": "<one sentence describing what this entity likely is>"
}

Rules:
- label must be singular PascalCase (Person, Project, Place, Event, Tool, …).
- Prefer a label from "Existing labels" over inventing a new one.
- description is inferred from the name and batch context; keep it concise.
- If the name is clearly a person, use label "Person".
"""


def _llm_propose_entity(
    missing_name: str,
    existing_labels: list[str],
    batch_context: str,
) -> dict | None:
    """Call Gemini Flash to infer label + description for an unknown entity name.

    Returns ``{"label": str, "description": str}`` or ``None`` on failure.
    Runs synchronously — called from the resolver which is already sync.
    """
    try:
        from google import genai
    except ImportError:
        logger.warning("_propose_anchor: google.genai not installed")
        return None

    api_key = (settings.google_api_keys or "").split(",")[0].strip()
    if not api_key:
        logger.warning("_propose_anchor: no GOOGLE_API_KEY configured")
        return None

    labels_str = ", ".join(existing_labels) if existing_labels else "(none yet)"
    user_prompt = (
        f'Entity name: "{missing_name}"\n\n'
        f"Existing labels: {labels_str}\n\n"
        f"Batch context (other nodes/edges being written now):\n{batch_context or '(none)'}"
    )

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=_ANCHOR_CLOUD_MODEL,
            contents=user_prompt,
            config={
                "system_instruction": _ANCHOR_SYSTEM_PROMPT,
                "response_mime_type": "application/json",
                "temperature": 0.1,
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
        if not parsed.get("label"):
            return None
        return parsed
    except Exception as e:
        logger.warning("_propose_anchor: Gemini call failed: %s", e)
        return None


class EntityIntent(BaseModel):
    """Create or update a knowledge-graph entity (e.g. a person, project, place)."""

    kind: Literal["entity"] = "entity"
    name: str
    label: str = "Entity"
    description: str = ""
    properties: dict = Field(default_factory=dict)


class BeliefIntent(BaseModel):
    """Record a belief the user holds. Optionally anchored to an entity by name."""

    kind: Literal["belief"] = "belief"
    content: str
    about_entity: str = ""
    confidence: float = 0.8
    source_text: str = ""


class TaskIntent(BaseModel):
    """Create a task node. Tasks soft-archive on completion (S0.8)."""

    kind: Literal["task"] = "task"
    title: str
    due_date: str = ""
    priority: str = "normal"
    for_person: str = ""
    about_entity: str = ""


class EdgeIntent(BaseModel):
    """Explicitly create a relationship between two existing or pending nodes.

    ``source`` and ``target`` are entity names; the resolver matches them to
    existing nodes or to other intents in the same batch.
    """

    kind: Literal["edge"] = "edge"
    source: str
    target: str
    rel_type: str
    properties: dict = Field(default_factory=dict)


Intent = Annotated[
    Union[EntityIntent, BeliefIntent, TaskIntent, EdgeIntent],
    Field(discriminator="kind"),
]


class IsolatedNodeError(Exception):
    """Raised when a batch would create one or more nodes with zero edges."""

    def __init__(self, isolated: list[dict]) -> None:
        super().__init__(f"{len(isolated)} isolated node(s) rejected")
        self.isolated = isolated


def graph_write(intents: list[dict]) -> dict:
    """Write a batch of graph intents to the knowledge graph.

    Each intent has a ``kind`` field: ``"entity"``, ``"belief"``, ``"task"``,
    or ``"edge"``. Use ``edge`` to connect nodes explicitly; otherwise the
    resolver attaches new nodes to the user root when no anchor is supplied.

    Example::

        graph_write([
            {"kind": "entity", "name": "Mom", "label": "Person"},
            {"kind": "entity", "name": "Birthday Cake", "label": "Item"},
            {"kind": "edge", "source": "Mom", "target": "Birthday Cake",
             "rel_type": "WANTS"},
        ])

    Returns ``{ok, nodes_written, edges_written, quarantined}``.
    """
    logger.info("Tool Call: graph_write -> %d intents", len(intents or []))

    offline = ensure_graph_online()
    if offline:
        return {"ok": False, "error": offline, "nodes_written": [], "edges_written": [], "quarantined": 0}

    parsed, errors = _parse_intents(intents or [])
    if errors:
        return {
            "ok": False,
            "error": "intent validation failed",
            "details": errors,
            "nodes_written": [],
            "edges_written": [],
            "quarantined": 0,
        }

    if not parsed:
        return {"ok": True, "nodes_written": [], "edges_written": [], "quarantined": 0}

    memory = get_memory_manager()
    resolver = _Resolver(memory)

    sorted_intents = _topo_sort(parsed)

    nodes_written: list[dict] = []
    edges_written: list[dict] = []
    isolated: list[dict] = []

    try:
        with memory.batch_graph_writes() as batch:
            for intent in sorted_intents:
                if isinstance(intent, EntityIntent):
                    node_id = resolver.upsert_entity(intent, batch)
                    nodes_written.append({"id": node_id, "name": intent.name, "kind": "entity"})
                elif isinstance(intent, BeliefIntent):
                    belief_id = resolver.upsert_belief(intent, batch)
                    nodes_written.append({"id": belief_id, "content": intent.content[:60], "kind": "belief"})
                elif isinstance(intent, TaskIntent):
                    task_id = resolver.upsert_task(intent, batch)
                    nodes_written.append({"id": task_id, "title": intent.title, "kind": "task"})
                elif isinstance(intent, EdgeIntent):
                    edge_meta = resolver.create_edge(intent, batch)
                    edges_written.append(edge_meta)

            # Isolation guard (S0.4): reject any batch that would leave a
            # newly-created node with zero edges. Cleared ops will skip
            # _flush_batch entirely so Neo4j is left unchanged.
            isolated = _find_isolated_nodes(batch.ops, nodes_written)
            if isolated:
                logger.warning(
                    "graph_write rejecting batch — %d isolated node(s): %s",
                    len(isolated), [i["name"] for i in isolated],
                )
                batch.ops.clear()
    except Exception as e:
        logger.exception("graph_write batch failed")
        return {
            "ok": False,
            "error": f"batch commit failed: {e}",
            "nodes_written": [],
            "edges_written": [],
            "quarantined": 0,
        }

    if isolated:
        return {
            "ok": False,
            "error": "isolated nodes rejected",
            "isolated": isolated,
            "nodes_written": [],
            "edges_written": [],
            "fallbacks": resolver.fallbacks,
            "quarantined": 0,
        }

    quarantined = memory.quarantine_unreachable_nodes()
    return {
        "ok": True,
        "nodes_written": nodes_written,
        "edges_written": edges_written,
        "fallbacks": resolver.fallbacks,
        "quarantined": quarantined,
    }


_INTENT_MODELS: dict[str, type[BaseModel]] = {
    "entity": EntityIntent,
    "belief": BeliefIntent,
    "task": TaskIntent,
    "edge": EdgeIntent,
}


def _find_isolated_nodes(
    ops: list[tuple[str, dict]], nodes_written: list[dict]
) -> list[dict]:
    """Return any nodes upserted in this batch that have zero edges in it.

    A node is considered newly created if it appears as a ``"node"`` op —
    the resolver only emits node ops for genuinely new uuids (existing
    nodes are reused by id without re-inserting). So every node op here is
    a fresh entity/belief/task that must carry at least one edge or be
    rejected.
    """
    new_ids: set[str] = set()
    for op_type, kwargs in ops:
        if op_type == "node":
            new_ids.add(kwargs["node_id"])

    endpoint_ids: set[str] = set()
    for op_type, kwargs in ops:
        if op_type == "edge":
            endpoint_ids.add(kwargs["source_id"])
            endpoint_ids.add(kwargs["target_id"])

    orphan_ids = new_ids - endpoint_ids
    if not orphan_ids:
        return []

    by_id = {n["id"]: n for n in nodes_written}
    return [by_id[nid] for nid in orphan_ids if nid in by_id]


_TOPO_ORDER = {"entity": 0, "task": 1, "belief": 2, "edge": 3}


def _topo_sort(intents: list[BaseModel]) -> list[BaseModel]:
    """Order intents so referenced nodes are created before referencing edges.

    Entities → tasks → beliefs → edges. Within a group, original order is
    preserved (stable sort). This is sufficient because the intent schema
    only carries forward references (edges/tasks/beliefs → entities), never
    backward.
    """
    return sorted(intents, key=lambda i: _TOPO_ORDER.get(i.kind, 99))


class _Resolver:
    """Stateful name → node_id resolution across a single graph_write batch.

    Resolution order for any missing name:
      1. ``name_to_id`` cache — populated by same-batch entity upserts.
      2. ``memory.find_entity()`` — existing Neo4j node exact-name lookup.
      3. ``_propose_anchor()`` — Gemini Flash infers label + description for
         the unknown name and stages a new node; depth-capped at 3.
      4. Fall back to root with ``RELATED_TO`` / ``ABOUT`` if all else fails.

    Every fallback is recorded in ``self.fallbacks`` for observability.
    """

    MAX_PROPOSAL_DEPTH = 3

    def __init__(self, memory: MemoryManager) -> None:
        self.memory = memory
        self.name_to_id: dict[str, str] = {}
        self.fallbacks: list[dict] = []
        self._root_id: str | None = None
        self._proposal_depth: int = 0
        self._schema: dict | None = None  # fetched once, cached for the batch

    def root(self) -> str | None:
        if self._root_id is not None:
            return self._root_id
        r = self.memory.get_user_root()
        self._root_id = r["id"] if r else None
        return self._root_id

    def _get_schema(self) -> dict:
        """Fetch the graph schema once and cache it for the lifetime of this batch."""
        if self._schema is None:
            try:
                self._schema = self.memory.graph_schema_snapshot()
            except Exception as e:
                logger.warning("_Resolver: schema fetch failed: %s", e)
                self._schema = {"labels": [], "relationship_types": [], "entities": []}
        return self._schema

    def resolve_entity_name(self, name: str) -> str | None:
        """Resolve a name to a node ID using cache then Neo4j. No proposals."""
        if not name:
            return None
        if name in self.name_to_id:
            return self.name_to_id[name]
        existing = self.memory.find_entity(name)
        if existing:
            self.name_to_id[name] = existing
            return existing
        return None

    def resolve_or_propose(
        self, name: str, batch: GraphWriteBatch, batch_context: str = ""
    ) -> str | None:
        """Resolve name → ID, proposing a new node via LLM if not found.

        Falls through to ``_propose_anchor`` when the deterministic lookup
        fails, staging a fresh node into ``batch`` and registering its ID in
        ``name_to_id`` so downstream edges can reference it immediately.
        Returns ``None`` only when both the lookup and the LLM proposal fail.
        """
        existing = self.resolve_entity_name(name)
        if existing:
            return existing
        proposed = self._propose_anchor(name, batch_context)
        if proposed:
            node_id = self.upsert_entity(proposed, batch)
            logger.info(
                "_Resolver: proposed new entity %r as %s (%s)",
                name, proposed.label, node_id,
            )
            return node_id
        return None

    def upsert_entity(self, intent: EntityIntent, batch: GraphWriteBatch) -> str:
        existing = self.resolve_entity_name(intent.name)
        if existing:
            return existing
        node_id = str(uuid.uuid4())
        props = {"description": intent.description, **(intent.properties or {})}
        batch.upsert_node(
            node_id=node_id,
            labels=[intent.label or "Entity"],
            name=intent.name,
            properties=props,
        )
        self.name_to_id[intent.name] = node_id
        return node_id

    def upsert_belief(self, intent: BeliefIntent, batch: GraphWriteBatch) -> str:
        belief_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        batch.upsert_node(
            node_id=belief_id,
            labels=["Belief"],
            name=intent.content,
            properties={
                "content": intent.content,
                "confidence": intent.confidence,
                "status": "active",
                "created_at": now,
                "updated_at": now,
                "source_text": intent.source_text or None,
            },
        )
        if intent.about_entity:
            anchor = self.resolve_or_propose(
                intent.about_entity, batch,
                batch_context=f'belief: "{intent.content}"',
            )
        else:
            anchor = None
        if anchor is None:
            # Belief without a resolvable subject is "a belief about myself" —
            # anchor to root so it can't float.
            anchor = self.root()
            if intent.about_entity:
                self._record_fallback("belief", intent.about_entity, "anchor_to_root")
            else:
                self._record_fallback("belief", "<unspecified>", "anchor_to_root")
        if anchor:
            batch.upsert_relationship(
                source_id=belief_id, target_id=anchor, rel_type="ABOUT"
            )
        return belief_id

    def upsert_task(self, intent: TaskIntent, batch: GraphWriteBatch) -> str:
        node_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        batch.upsert_node(
            node_id=node_id,
            labels=["Task"],
            name=intent.title,
            properties={
                "status": "TODO",
                "due_date": intent.due_date or None,
                "priority": intent.priority or "normal",
                "created_at": now,
            },
        )
        root = self.root()
        if root:
            batch.upsert_relationship(source_id=root, target_id=node_id, rel_type="OWNS_TASK")
        else:
            self._record_fallback("task", "<user_root>", "root_missing")
        if intent.for_person:
            person_id = self.resolve_or_propose(
                intent.for_person, batch,
                batch_context=f'task: "{intent.title}"',
            )
            if person_id:
                batch.upsert_relationship(
                    source_id=node_id, target_id=person_id, rel_type="FOR_PERSON"
                )
            else:
                self._record_fallback("task.for_person", intent.for_person, "no_anchor")
        if intent.about_entity:
            about_id = self.resolve_or_propose(
                intent.about_entity, batch,
                batch_context=f'task: "{intent.title}"',
            )
            if about_id:
                batch.upsert_relationship(
                    source_id=node_id, target_id=about_id, rel_type="ABOUT_ITEM"
                )
            else:
                self._record_fallback("task.about_entity", intent.about_entity, "no_anchor")
        return node_id

    def create_edge(self, intent: EdgeIntent, batch: GraphWriteBatch) -> dict:
        rel_type = (intent.rel_type or "RELATED_TO").upper().replace(" ", "_")
        batch_context = f'edge: "{intent.source}" -{rel_type}-> "{intent.target}"'

        src = self.resolve_or_propose(intent.source, batch, batch_context)
        tgt = self.resolve_or_propose(intent.target, batch, batch_context)

        if src and tgt:
            batch.upsert_relationship(
                source_id=src, target_id=tgt, rel_type=rel_type, properties=intent.properties
            )
            return {"source": intent.source, "target": intent.target, "rel_type": rel_type}

        # One or both endpoints couldn't be resolved or proposed — last resort: root.
        root = self.root()
        if src and root:
            batch.upsert_relationship(source_id=src, target_id=root, rel_type="RELATED_TO")
            self._record_fallback("edge.target", intent.target, "fallback_to_root")
            return {
                "source": intent.source, "target": "<root>",
                "rel_type": "RELATED_TO", "fallback": True,
            }
        if tgt and root:
            batch.upsert_relationship(source_id=root, target_id=tgt, rel_type="RELATED_TO")
            self._record_fallback("edge.source", intent.source, "fallback_to_root")
            return {
                "source": "<root>", "target": intent.target,
                "rel_type": "RELATED_TO", "fallback": True,
            }

        self._record_fallback(
            "edge", f"{intent.source}->{intent.target}", "both_endpoints_missing"
        )
        return {
            "source": intent.source, "target": intent.target,
            "rel_type": rel_type, "skipped": True,
        }

    def _record_fallback(self, where: str, missing: str, action: str) -> None:
        entry = {"where": where, "missing": missing, "action": action}
        self.fallbacks.append(entry)
        logger.warning("graph_write fallback: %s", entry)

    # ── LLM anchor proposal ──────────────────────────────────────────────────

    def _propose_anchor(
        self, missing_name: str, batch_context: str = ""
    ) -> EntityIntent | None:
        """Ask Gemini Flash to propose an EntityIntent for an unknown name.

        Returns an ``EntityIntent`` whose ``name`` equals ``missing_name``
        exactly, or ``None`` when the LLM can't determine anything useful.
        Depth-capped at ``MAX_PROPOSAL_DEPTH`` to prevent runaway recursion.

        The returned intent is NOT staged here — callers pass it to
        ``upsert_entity()`` so the normal node-op + name_to_id wiring fires.
        The isolation guard is satisfied because the caller's edge intent will
        reference the same node.
        """
        if self._proposal_depth >= self.MAX_PROPOSAL_DEPTH:
            logger.warning(
                "_propose_anchor: depth cap reached for %r — falling back to root",
                missing_name,
            )
            return None

        self._proposal_depth += 1
        try:
            schema = self._get_schema()
            existing_labels = schema.get("labels") or []
            result = _llm_propose_entity(missing_name, existing_labels, batch_context)
            if not result:
                return None
            label = (result.get("label") or "Entity").strip()
            description = (result.get("description") or "").strip()
            return EntityIntent(
                name=missing_name,
                label=label,
                description=description,
            )
        except Exception as e:
            logger.warning("_propose_anchor(%r) failed: %s", missing_name, e)
            return None
        finally:
            self._proposal_depth -= 1


def _parse_intents(raw: list[dict]) -> tuple[list[BaseModel], list[dict]]:
    """Validate raw intent dicts. Returns (parsed, errors)."""
    parsed: list[BaseModel] = []
    errors: list[dict] = []
    for idx, item in enumerate(raw):
        if not isinstance(item, dict):
            errors.append({"index": idx, "error": "intent must be a dict"})
            continue
        kind = item.get("kind")
        model = _INTENT_MODELS.get(kind)
        if model is None:
            errors.append({"index": idx, "error": f"unknown kind: {kind!r}"})
            continue
        try:
            parsed.append(model.model_validate(item))
        except ValidationError as e:
            errors.append({"index": idx, "error": e.errors()})
    return parsed, errors
