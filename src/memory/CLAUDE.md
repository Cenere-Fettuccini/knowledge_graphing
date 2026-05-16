# Memory — Internal Persistence Layer

Owns all persistence: ChromaDB (semantic/episodic memory) and Neo4j (knowledge
graph). **Apps interact only through `MemoryManager`'s public methods, injected
via `get_memory_manager()`.** Never access `memory.neo4j.*` or `memory.chroma.*`
from app or tool code.

## Files
| File | Role |
|------|------|
| `manager.py` | `MemoryManager` class + `get_memory_manager()` lazy factory — the only public surface |
| `protocol.py` | `MemoryProtocol` — structural interface for type hints and test mocks |
| `spillover.py` | `SpilloverWriter` — records failed writes for retry (internal) |
| `stores/chroma_store.py` | ChromaDB client wrapper (internal) |
| `stores/neo4j_store.py` | Neo4j driver wrapper (internal) |
| `embeddings/google.py` | Google embedding model client (internal) |

---

## Called By
| Caller | What it uses |
|--------|-------------|
| `src.apps.chat.api` / `.services` | `MemoryManager` via `Depends(get_memory_manager)` |
| `src.apps.explorer.api` / `.services` | `MemoryManager` via `Depends(get_memory_manager)` |
| `src.agent_platform.public.agent_service` | `get_memory_manager()` — passes to `Agent` |
| `src.core.agent` | `MemoryManager`, `get_memory_manager()` — context assembly + store |
| `src.core.context` | `MemoryManager` — history retrieval for context window |
| `src.agent_platform.tools.*` | `get_memory_manager()` — all tools call this directly |
| `src.agent_platform.analyzers.*` | `MemoryManager` accepted as parameter |
| `src.platform.app_factory` | `get_memory_manager()` — lifespan warm-up |
| `src.platform.graph_ingest` | `get_memory_manager()` — batch ingest endpoint |
| `src.rumination.engine` | `MemoryManager`, `get_memory_manager()` |
| `src.bot.proactive` | `get_memory_manager()` |
| `src.ingestion.bulk_importer` | `MemoryManager` — `memory.store()` for each chunk |

---

## Calls Into
| Dependency | What is called |
|------------|---------------|
| `src.core.config` | `settings` — DB URIs, collection names, thresholds |
| `src.memory.stores.chroma_store` | `ChromaStore` — all Chroma operations |
| `src.memory.stores.neo4j_store` | `Neo4jStore` — all Neo4j operations |
| `src.memory.spillover` | `SpilloverWriter` — records write failures |
| `src.agent_platform.analyzers.graph_ingest_trigger` | `maybe_trigger()` — called lazily from `store()` |

---

## Storage Architecture
- **ChromaDB** is the source of truth for raw conversation history. Every
  `store()` call lands here with `analyzed: False`. The analyzer pipeline
  drains rows with `analyzed: False` to populate Neo4j.
- **Neo4j** holds *only* inferred, durable knowledge: entities, relationships,
  beliefs, tasks. Conversation turns themselves are **not** written to the graph.
- `get_memory_manager()` is a lazy singleton — the first call initializes both
  backends. Subsequent calls return the same instance.

---

## Public Interface — `MemoryManager`

### Health
```python
memory.status() -> dict
# {"status": "online"|"degraded"|"offline", "neo4j": str, "chroma": str}
# Cached 60s — call invalidate_health_cache() first for a fresh probe.

memory.invalidate_health_cache() -> None
memory.snapshot_health() -> dict
```

### Conversation Memory (ChromaDB)
```python
memory.store(text, role: str, session_id: str, is_ephemeral: bool = False, **extra) -> str | None
# Stores a turn; returns memory_id. Triggers maybe_trigger() after store.

memory.search(query: str, k: int = 5, session_id: str | None = None, include_ephemeral: bool = True) -> list
# Each result: {"id": str, "text": str, "metadata": dict, "distance": float}

memory.get_history(session_id: str, limit: int = 20) -> list[dict]
# Newest-first. Each: {"id", "text", "metadata": {role, timestamp, ...}}

memory.list_sessions(limit: int = 500) -> dict
memory.clear_ephemeral(session_id: str | None = None) -> None
memory.delete_session(session_id: str) -> bool
```

### Knowledge Graph (Neo4j) — reads
```python
memory.graph_overview(limit, era_id, active_self_only) -> dict
memory.graph_node_detail(node_id: str) -> dict
memory.graph_node_provenance(node_id: str) -> dict
memory.graph_active_tasks(include_completed, since) -> list[dict]
memory.graph_belief_trail(belief_id: str, chain_depth=None) -> dict
memory.graph_schema_snapshot() -> dict
memory.graph_neighborhood(node_id, depth, limit) -> dict
```

### Knowledge Graph (Neo4j) — writes
```python
memory.upsert_node(*, node_id, labels, name, properties=None) -> str
memory.upsert_relationship(*, source_id, target_id, rel_type, properties=None) -> bool
memory.batch_graph_writes() -> context manager  # atomic batching
```

### Canonicalization
```python
memory.list_distinct_graph_labels(exclude=None) -> list[str]
memory.list_named_nodes_by_label(label, exclude_roots=True) -> list[dict]
memory.count_node_connections(node_ids) -> dict[str, int]
memory.list_active_beliefs(limit=1000) -> list[dict]
memory.create_merge_proposal(*, proposal_id, label, primary_id, duplicate_ids, scores, canonical_name) -> str
memory.list_merge_proposals(*, status="pending", limit=200) -> list[dict]
memory.get_merge_proposal(proposal_id) -> dict | None
memory.apply_merge_proposal(proposal_id) -> dict
memory.dismiss_merge_proposal(proposal_id) -> bool
```

### Analyzer Queue (ChromaDB)
```python
memory.count_unanalyzed() -> int
memory.list_unanalyzed(limit=50) -> list[dict]
# Live conversation turns first (FIFO), then bulk-imported rows (oldest-first).

memory.mark_analyzed(memory_ids: list[str], run_id=None) -> int
memory.count_failed() -> int
memory.list_failed(limit=50) -> list[dict]
memory.mark_failed(ids, reason, run_id=None) -> int
memory.retry_failed(memory_ids=None) -> int
```

### Eras (Neo4j)
```python
memory.list_eras(active_only) -> list[dict]
memory.get_era(era_id) -> dict | None
memory.upsert_era(*, name, description, start_date, end_date, era_id=None) -> dict
memory.delete_era(era_id) -> bool
memory.bind_node_to_era(node_id, era_id) -> bool
memory.unbind_node_from_era(node_id, era_id) -> bool
memory.eras_active_at(date) -> dict
```

### Pending Beliefs & Contradictions (Neo4j)
```python
memory.count_belief_candidates() -> int
memory.list_pending_beliefs(limit) -> list[dict]
memory.create_pending_belief(...) -> dict
memory.approve_pending_belief(belief_id) -> dict
memory.edit_pending_belief(belief_id, new_content) -> dict
memory.reject_pending_belief(belief_id, reason) -> dict
memory.purge_expired_rejections() -> int
memory.list_active_rejections(limit) -> list[dict]
memory.list_contradictions(limit) -> list[dict]
memory.belief_calibration() -> dict
```

### Bootstrap (Neo4j)
```python
memory.user_root_exists() -> bool
memory.get_user_root() -> dict | None
memory.bootstrap_user_root(name: str) -> dict
# Hard-wipes Neo4j and seeds a single :Person:User root.
# Chroma is left intact — queued turns are re-processed by the analyzer.
```

---

## Adding New Graph Queries
Add the method to `MemoryManager` in `manager.py` (wraps the appropriate
`self.neo4j.*` call). Never expose `self.neo4j` or `self.chroma` to callers.
Also add the signature to `MemoryProtocol` in `protocol.py` for test mocking.
