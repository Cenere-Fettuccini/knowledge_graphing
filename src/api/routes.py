"""Graph API routes.

All endpoints are currently backed by in-memory mock data so the Explorer UI
is fully functional right now. Each handler is clearly marked where the real
store call will be dropped in during Step 6.
"""

import time
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter(tags=["graph"])

# ── Mock data ─────────────────────────────────────────────────────────────────
# Realistic enough to exercise every UI component.

_MOCK_NODES: list[dict] = [
    {"id": "p1",  "label": "Person",       "name": "Alice",              "properties": {"relation_to_user": "colleague", "notes": "Senior engineer on the infra team"}},
    {"id": "p2",  "label": "Person",       "name": "Bob",                "properties": {"relation_to_user": "friend",    "notes": "Met at PyCon 2023"}},
    {"id": "p3",  "label": "Person",       "name": "Carol",              "properties": {"relation_to_user": "manager",   "notes": "Joined Acme in Q1"}},
    {"id": "o1",  "label": "Organization", "name": "Acme Corp",          "properties": {"type": "employer"}},
    {"id": "o2",  "label": "Organization", "name": "PyCon",              "properties": {"type": "conference"}},
    {"id": "pr1", "label": "Project",      "name": "Dashboard Redesign", "properties": {"status": "active",   "description": "Revamp the internal analytics dashboard"}},
    {"id": "pr2", "label": "Project",      "name": "API Migration",      "properties": {"status": "planning", "description": "Move legacy REST endpoints to GraphQL"}},
    {"id": "t1",  "label": "Topic",        "name": "Python",             "properties": {"domain": "programming"}},
    {"id": "t2",  "label": "Topic",        "name": "Machine Learning",   "properties": {"domain": "AI"}},
    {"id": "t3",  "label": "Topic",        "name": "System Design",      "properties": {"domain": "engineering"}},
    {"id": "e1",  "label": "Event",        "name": "Q3 Planning",        "properties": {"date": "2025-07-14", "location": "Conference Room B"}},
    {"id": "f1",  "label": "Fact",         "name": "Alice prefers morning standups", "properties": {"confidence": 0.9, "source_date": "2025-04-21"}},
    {"id": "f2",  "label": "Fact",         "name": "Bob is learning Rust",          "properties": {"confidence": 0.75, "source_date": "2025-04-18"}},
]

_MOCK_EDGES: list[dict] = [
    {"source": "p1",  "target": "o1",  "type": "WORKS_AT"},
    {"source": "p2",  "target": "o1",  "type": "WORKS_AT"},
    {"source": "p3",  "target": "o1",  "type": "WORKS_AT"},
    {"source": "p1",  "target": "pr1", "type": "WORKS_ON"},
    {"source": "p2",  "target": "pr1", "type": "WORKS_ON"},
    {"source": "p3",  "target": "pr2", "type": "WORKS_ON"},
    {"source": "p1",  "target": "p2",  "type": "KNOWS"},
    {"source": "p1",  "target": "p3",  "type": "KNOWS"},
    {"source": "pr1", "target": "o1",  "type": "BELONGS_TO"},
    {"source": "pr2", "target": "o1",  "type": "BELONGS_TO"},
    {"source": "t1",  "target": "t3",  "type": "SUBTOPIC_OF"},
    {"source": "t2",  "target": "t3",  "type": "SUBTOPIC_OF"},
    {"source": "f1",  "target": "p1",  "type": "ABOUT"},
    {"source": "f2",  "target": "p2",  "type": "ABOUT"},
    {"source": "p1",  "target": "e1",  "type": "ATTENDS"},
    {"source": "p3",  "target": "e1",  "type": "ATTENDS"},
]

_MOCK_CONVERSATIONS: dict[str, list[dict]] = {
    "f1": [
        {"role": "user",      "text": "Alice mentioned she really prefers doing standups in the morning, before 10 AM.", "timestamp": "2025-04-21T09:14:00Z"},
        {"role": "assistant", "text": "Got it! I'll remember that Alice prefers morning standups.",                      "timestamp": "2025-04-21T09:14:03Z"},
    ],
    "f2": [
        {"role": "user",      "text": "Ran into Bob today — he's been learning Rust in his spare time.",  "timestamp": "2025-04-18T17:42:00Z"},
        {"role": "assistant", "text": "Interesting! I'll note that Bob is learning Rust.",                 "timestamp": "2025-04-18T17:42:05Z"},
    ],
}

_node_index: dict[str, dict] = {n["id"]: n for n in _MOCK_NODES}

# ── Helpers ───────────────────────────────────────────────────────────────────

def _connections_for(node_id: str) -> list[dict]:
    conns = []
    for edge in _MOCK_EDGES:
        if edge["source"] == node_id:
            target = _node_index.get(edge["target"])
            if target:
                conns.append({"direction": "out", "rel": edge["type"], "node": target})
        elif edge["target"] == node_id:
            source = _node_index.get(edge["source"])
            if source:
                conns.append({"direction": "in", "rel": edge["type"], "node": source})
    return conns


def _facts_for(node_id: str) -> list[dict]:
    return [
        n for n in _MOCK_NODES
        if n["label"] == "Fact"
        and any(
            e["source"] == n["id"] and e["target"] == node_id
            for e in _MOCK_EDGES
        )
    ]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/overview")
async def overview() -> dict[str, Any]:
    """All nodes + edges (max 500). Step 6: replace body with Neo4jStore.get_overview()."""
    counts: dict[str, int] = {}
    for n in _MOCK_NODES:
        counts[n["label"]] = counts.get(n["label"], 0) + 1

    return {
        "nodes": _MOCK_NODES,
        "edges": _MOCK_EDGES,
        "stats": {
            "total_nodes": len(_MOCK_NODES),
            "total_edges": len(_MOCK_EDGES),
            "nodes_by_label": counts,
            "last_rumination": "Never (engine not yet running)",
        },
    }


@router.get("/node/{node_id}")
async def node_detail(node_id: str) -> dict[str, Any]:
    """Full node detail + 1-hop connections + linked facts. Step 6: replace with Neo4jStore.query_context()."""
    node = _node_index.get(node_id)
    if not node:
        raise HTTPException(status_code=404, detail=f"Node '{node_id}' not found")

    return {
        "node": node,
        "connections": _connections_for(node_id),
        "facts": _facts_for(node_id),
    }


@router.get("/expand/{node_id}")
async def expand_node(node_id: str) -> dict[str, Any]:
    """2-hop neighbourhood. Step 6: replace with Neo4jStore.get_2hop_neighbourhood()."""
    if node_id not in _node_index:
        raise HTTPException(status_code=404, detail=f"Node '{node_id}' not found")

    hop1_ids = {
        e["target"] if e["source"] == node_id else e["source"]
        for e in _MOCK_EDGES
        if e["source"] == node_id or e["target"] == node_id
    }
    hop2_ids: set[str] = set()
    for nid in hop1_ids:
        for e in _MOCK_EDGES:
            if e["source"] == nid:
                hop2_ids.add(e["target"])
            elif e["target"] == nid:
                hop2_ids.add(e["source"])

    all_ids = {node_id} | hop1_ids | hop2_ids
    nodes = [_node_index[i] for i in all_ids if i in _node_index]
    edges = [
        e for e in _MOCK_EDGES
        if e["source"] in all_ids and e["target"] in all_ids
    ]
    return {"nodes": nodes, "edges": edges}


@router.get("/search")
async def search(q: str = "") -> dict[str, Any]:
    """Full-text search across node names + fact content. Step 6: add semantic search via ChromaStore."""
    if not q:
        return {"results": []}

    q_lower = q.lower()
    results = []
    for node in _MOCK_NODES:
        score = 0
        if q_lower in node["name"].lower():
            score = 1.0
        elif any(q_lower in str(v).lower() for v in node.get("properties", {}).values()):
            score = 0.6
        if score:
            results.append({"id": node["id"], "label": node["label"], "name": node["name"], "score": score})

    results.sort(key=lambda x: x["score"], reverse=True)
    return {"results": results}


@router.get("/source/{fact_id}")
async def fact_source(fact_id: str) -> dict[str, Any]:
    """Fetch original conversation chunks for a fact. Step 6: replace with ChromaStore.get(session_id=...)."""
    convos = _MOCK_CONVERSATIONS.get(fact_id)
    if convos is None:
        raise HTTPException(status_code=404, detail=f"No source conversation for fact '{fact_id}'")
    return {"conversations": convos}


@router.get("/stats")
async def stats() -> dict[str, Any]:
    """Graph statistics. Step 6: replace with live Neo4j + APScheduler state."""
    counts: dict[str, int] = {}
    for n in _MOCK_NODES:
        counts[n["label"]] = counts.get(n["label"], 0) + 1

    return {
        "nodes_by_label": counts,
        "total_nodes": len(_MOCK_NODES),
        "total_edges": len(_MOCK_EDGES),
        "last_rumination_ts": None,
        "last_rumination_human": "Never",
    }