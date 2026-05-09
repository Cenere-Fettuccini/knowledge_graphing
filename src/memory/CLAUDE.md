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

## Adding New Graph Queries
Add the method to `MemoryManager` in `manager.py` — it wraps the appropriate
`self.neo4j.*` call. Never expose `self.neo4j` or `self.chroma` to callers.
Also add the method signature to `MemoryProtocol` in `protocol.py`.
