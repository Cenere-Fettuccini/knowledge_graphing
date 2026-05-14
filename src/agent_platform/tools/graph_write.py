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

from pydantic import BaseModel, Field, ValidationError

from src.agent_platform.tools.common import ensure_graph_online, logger
from src.memory.manager import GraphWriteBatch, MemoryManager, get_memory_manager


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

    The resolver is the seam where the LLM-driven anchor proposal will plug
    in (S0.3b — currently a stub). For now it does deterministic resolution
    against the existing graph plus same-batch intents, and falls back to
    ``RELATED_TO`` on the user root for edges that can't be fully resolved.
    Every fallback is recorded so we can see where the resolver gives up.
    """

    MAX_PROPOSAL_DEPTH = 3  # reserved for the LLM proposal step (S0.3b)

    def __init__(self, memory: MemoryManager) -> None:
        self.memory = memory
        self.name_to_id: dict[str, str] = {}
        self.fallbacks: list[dict] = []
        self._root_id: str | None = None
        self._proposal_depth: int = 0

    def root(self) -> str | None:
        if self._root_id is not None:
            return self._root_id
        r = self.memory.get_user_root()
        self._root_id = r["id"] if r else None
        return self._root_id

    def resolve_entity_name(self, name: str) -> str | None:
        if not name:
            return None
        if name in self.name_to_id:
            return self.name_to_id[name]
        existing = self.memory.find_entity(name)
        if existing:
            self.name_to_id[name] = existing
            return existing
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
        anchor = (
            self.resolve_entity_name(intent.about_entity) if intent.about_entity else None
        )
        if anchor is None:
            # Belief without a resolvable subject is "a belief about myself" —
            # anchor to root so it can't float. Tracked as a fallback so we can
            # see how often this happens.
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
            person_id = self.resolve_entity_name(intent.for_person)
            if person_id:
                batch.upsert_relationship(
                    source_id=node_id, target_id=person_id, rel_type="FOR_PERSON"
                )
            else:
                self._record_fallback("task.for_person", intent.for_person, "no_anchor")
        if intent.about_entity:
            about_id = self.resolve_entity_name(intent.about_entity)
            if about_id:
                batch.upsert_relationship(
                    source_id=node_id, target_id=about_id, rel_type="ABOUT_ITEM"
                )
            else:
                self._record_fallback("task.about_entity", intent.about_entity, "no_anchor")
        return node_id

    def create_edge(self, intent: EdgeIntent, batch: GraphWriteBatch) -> dict:
        src = self.resolve_entity_name(intent.source)
        tgt = self.resolve_entity_name(intent.target)
        rel_type = (intent.rel_type or "RELATED_TO").upper().replace(" ", "_")

        if src and tgt:
            batch.upsert_relationship(
                source_id=src, target_id=tgt, rel_type=rel_type, properties=intent.properties
            )
            return {"source": intent.source, "target": intent.target, "rel_type": rel_type}

        # One or both endpoints missing. Fall back to root for the resolved end.
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

    # ── LLM anchor proposal (S0.3b — stub) ──────────────────────────────────
    #
    # When the deterministic resolver can't find an anchor for an edge or
    # qualifier, this hook is the place to ask a small LLM call for an
    # EntityIntent it can splice into the batch. Currently a no-op so the
    # resolver behaves deterministically — flip on once we've watched the
    # fallback log under real traffic.

    def _propose_anchor(self, missing_name: str) -> EntityIntent | None:
        if self._proposal_depth >= self.MAX_PROPOSAL_DEPTH:
            return None
        # self._proposal_depth += 1
        # ... LLM call ...
        return None


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
