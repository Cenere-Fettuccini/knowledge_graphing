# Memory — Internal Module

Owns all persistence: ChromaDB (semantic/episodic memory) and Neo4j (knowledge graph).
**Apps interact only through `MemoryManager`'s public methods, injected via `get_memory_manager()`.**
Never access `memory.neo4j.*` or `memory.chroma.*` from app code.

## Storage roles
- **ChromaDB** is the source of truth for raw conversation history. Every `store()`
  call lands here with `analyzed: False` so the analyzer pipeline (under
  `src/agent_platform/analyzers/`) can pick it up later.
- **Neo4j** holds *only* inferred, durable knowledge — entities, relationships, and
  beliefs produced by the analyzer. Conversation turns themselves are **not**
  written to the graph.

## Files
| File | Role |
|------|------|
| `manager.py` | `MemoryManager` class + `get_memory_manager()` lazy factory — the only public surface |
| `protocol.py` | `MemoryProtocol` — structural interface for type hints and test mocks |
| `stores/chroma_store.py` | ChromaDB client wrapper (internal) |
| `stores/neo4j_store.py` | Neo4j driver wrapper (internal) |
| `embeddings/google.py` | Google embedding model client (internal) |

## Public Interface — `MemoryManager`

### Health
```python
memory.status() -> dict
# {"status": "online"|"degraded"|"offline", "neo4j": str, "chroma": str}
# Cached for 60s — call invalidate_health_cache() first if you need a fresh probe.

memory.invalidate_health_cache() -> None
# Forces the next status() call to re-probe backends.
```

### Conversation Memory (ChromaDB)
```python
memory.store(text, role: str, session_id: str, is_ephemeral: bool = False, **extra) -> str | None
# Stores a turn in Chroma only, with metadata `analyzed: False`. Returns the chroma memory_id.
# The graph is populated separately by the analyzer pipeline.

memory.search(query: str, k: int = 5, session_id: str | None = None, include_ephemeral: bool = True) -> list
# Semantic search. Each result: {"id": str, "text": str, "metadata": dict, "distance": float}

memory.get_history(session_id: str, limit: int = 20) -> list[dict]
# Recent turns for a session, newest-first. Each: {"id", "text", "metadata": {role, timestamp, ...}}

memory.list_sessions(limit: int = 500) -> dict
# {"documents": list[str], "metadatas": list[dict]} — all stored turns up to limit.

memory.clear_ephemeral(session_id: str | None = None) -> None
memory.delete_session(session_id: str) -> bool
```

### Knowledge Graph (Neo4j)
```python
memory.graph_overview(limit: int = 100) -> dict
# Node/relationship counts and top labels.

memory.graph_node_detail(node_id: str) -> dict
# {"node": {id, label, name, ...}, "connections": [{type, target}, ...]}

memory.graph_node_provenance(node_id: str) -> dict
# Provenance/source chain for a node.

memory.graph_active_tasks() -> list[dict]
# Active task nodes.

memory.graph_belief_trail(belief_id: str) -> dict
# {"chain": list[dict], "evidence": list[dict]}
```

### Canonicalization (entity dedup, S2.4)
```python
memory.list_distinct_graph_labels(*, exclude: set[str] | None = None) -> list[str]
memory.list_named_nodes_by_label(label: str, *, exclude_roots: bool = True) -> list[dict]
memory.count_node_connections(node_ids: list[str]) -> dict[str, int]
memory.list_active_beliefs(limit: int = 1000) -> list[dict]
# Used by EntityCanonicalizer / BeliefCanonicalizer to gather candidates and
# rank merge primaries. list_active_beliefs returns {id, content, confidence,
# created_at} for :Belief nodes with status='active'.

memory.create_merge_proposal(*, proposal_id, label, primary_id,
                             duplicate_ids, scores, canonical_name) -> str
memory.list_merge_proposals(*, status: str = "pending", limit: int = 200) -> list[dict]
memory.get_merge_proposal(proposal_id: str) -> dict | None
memory.apply_merge_proposal(proposal_id: str) -> dict
# Re-points every relationship from each duplicate to the primary (preserving
# rel-type and props), records duplicate names as primary.alternate_names,
# deletes the duplicates, and flips status to "applied". Single transaction.

memory.dismiss_merge_proposal(proposal_id: str) -> bool
# Status flip only; no graph mutation. Stays in the graph so re-runs don't
# re-propose the same cluster.
```

### Analyzer queue (Chroma)
```python
memory.list_unanalyzed(limit: int = 50) -> list[dict]
# Returns the next batch of conversation turns awaiting analysis.
# Filters to `analyzed: false` and excludes ephemeral rows.
# Live conversation turns (`bulk_imported: False`) are served first, FIFO by
# stored timestamp. Bulk-imported rows only surface once the live pool is
# empty, and are returned oldest-first by their source `timestamp` so a
# historical backfill is processed in the order the user lived it.

memory.count_unanalyzed() -> int
# Cheap-ish count for queue-status displays.

memory.mark_analyzed(memory_ids: list[str], run_id: str | None = None) -> int
# Stamps each Chroma row with `analyzed: true` (and `analysis_run_id`).
```

### Analyzer graph writes (Neo4j)
```python
memory.graph_schema_snapshot() -> dict
# {"labels": [...], "relationship_types": [...], "entities": [...]}
# Fed into the analyzer prompt so the LLM reuses existing labels and edge types.

memory.upsert_node(*, node_id: str, labels: list[str], name: str, properties: dict | None = None) -> str
# Multi-label MERGE on stable id. Layered labels are accepted on first sighting.

memory.upsert_relationship(*, source_id: str, target_id: str, rel_type: str, properties: dict | None = None) -> bool
# MERGE a typed relationship between two existing nodes.
```

### Bootstrap (Neo4j)
```python
memory.user_root_exists() -> bool
# True once a `:Person:User {is_root: true}` node has been seeded.

memory.get_user_root() -> dict | None
# Returns the seeded root node, or None if not yet bootstrapped.

memory.bootstrap_user_root(name: str) -> dict
# Hard-wipes Neo4j and seeds a single `:Person:User` root with the given name.
# Chroma is left intact — historical conversations remain queued for the
# analyzer to re-process against the fresh graph.
```

## Adding New Graph Queries
Add the method to `MemoryManager` in `manager.py` — it wraps the appropriate
`self.neo4j.*` call. Never expose `self.neo4j` or `self.chroma` to callers.
Also add the method signature to `MemoryProtocol` in `protocol.py`.
