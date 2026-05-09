# Memory — Internal Module

Owns all persistence: ChromaDB (semantic/episodic memory) and Neo4j (knowledge graph).
**Apps interact only through the `memory_manager` singleton's public methods.**
Never access `memory_manager.neo4j.*` or `memory_manager.chroma.*` from app code.

## Files
| File | Role |
|------|------|
| `manager.py` | `MemoryManager` class + `memory_manager` singleton — the only public surface |
| `stores/chroma_store.py` | ChromaDB client wrapper (internal) |
| `stores/neo4j_store.py` | Neo4j driver wrapper (internal) |
| `knowledge_extractor.py` | Extracts belief signals from conversation text (internal) |
| `embeddings/google.py` | Google embedding model client (internal) |

## Public Interface — `memory_manager`

### Health
```python
memory_manager.status() -> dict
# {"status": "online"|"degraded"|"offline", "neo4j": str, "chroma": str}
# Cached for 60s — call invalidate_health_cache() first if you need a fresh probe.

memory_manager.invalidate_health_cache() -> None
# Forces the next status() call to re-probe backends.
```

### Conversation Memory (ChromaDB)
```python
memory_manager.store(text, role: str, session_id: str, is_ephemeral: bool = False, **extra) -> str | None
# Stores a turn in Chroma + Neo4j. Returns the chroma memory_id.

memory_manager.search(query: str, k: int = 5, session_id: str | None = None, include_ephemeral: bool = True) -> list
# Semantic search. Each result: {"id": str, "text": str, "metadata": dict, "distance": float}

memory_manager.get_history(session_id: str, limit: int = 20) -> list[dict]
# Recent turns for a session, newest-first. Each: {"id", "text", "metadata": {role, timestamp, ...}}

memory_manager.list_sessions(limit: int = 500) -> dict
# {"documents": list[str], "metadatas": list[dict]} — all stored turns up to limit.

memory_manager.clear_ephemeral(session_id: str | None = None) -> None
memory_manager.delete_session(session_id: str) -> bool
```

### Knowledge Graph (Neo4j)
```python
memory_manager.graph_overview(limit: int = 100) -> dict
# Node/relationship counts and top labels.

memory_manager.graph_node_detail(node_id: str) -> dict
# {"node": {id, label, name, ...}, "connections": [{type, target}, ...]}

memory_manager.graph_node_provenance(node_id: str) -> dict
# Provenance/source chain for a node.

memory_manager.graph_active_tasks() -> list[dict]
# Active task nodes.

memory_manager.graph_belief_trail(belief_id: str) -> dict
# {"chain": list[dict], "evidence": list[dict]}
```

## Adding New Graph Queries
Add the method to `MemoryManager` in `manager.py` — it wraps the appropriate
`self.neo4j.*` call. Never expose `self.neo4j` or `self.chroma` to callers.
