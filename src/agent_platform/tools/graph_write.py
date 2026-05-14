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

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, ValidationError

from src.agent_platform.tools.common import ensure_graph_online, logger


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

    # S0.3 / S0.4 / S0.7 land the resolver, isolation guard, and reachability
    # sweep. For now the skeleton returns success for an empty batch and
    # NotImplemented for anything substantive — gives us a registered tool
    # the agent can target while the write path is being built out.
    if not parsed:
        return {"ok": True, "nodes_written": [], "edges_written": [], "quarantined": 0}

    return {
        "ok": False,
        "error": "graph_write resolver not yet implemented (S0.3)",
        "received": [i.kind for i in parsed],
        "nodes_written": [],
        "edges_written": [],
        "quarantined": 0,
    }


_INTENT_MODELS: dict[str, type[BaseModel]] = {
    "entity": EntityIntent,
    "belief": BeliefIntent,
    "task": TaskIntent,
    "edge": EdgeIntent,
}


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
