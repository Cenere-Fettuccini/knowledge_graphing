# App: Explorer

Serves the knowledge graph UI and system status dashboard. Provides read-only graph
queries (nodes, relationships, provenance, tasks, belief trails) and a system health
endpoint that aggregates memory, agent, and LLM quota status.

## Files
| File | Role |
|------|------|
| `api.py` | FastAPI router — thin HTTP layer, delegates everything to `services.py` |
| `services.py` | Graph queries and system status aggregation |
| `app.py` | `AppDefinition` registration (metadata only) |

## Allowed Imports (what this app may use)
```python
from src.agent_platform.public.agent_service import agent_service
from src.memory.manager import memory_manager
```

## Public Methods Used from Each Import

### `memory_manager` (public methods only)
```python
memory_manager.status() -> dict
# {"status": "online"|"degraded"|"offline", "neo4j": str, "chroma": str}

memory_manager.invalidate_health_cache() -> None
# forces the next status() call to re-probe backends (use before status() in /system/status)

memory_manager.graph_overview(limit: int = 100) -> dict
# node/relationship counts and top labels from Neo4j

memory_manager.graph_node_detail(node_id: str) -> dict
# {"node": {id, label, name, ...}, "connections": [{type, target}, ...]}

memory_manager.graph_node_provenance(node_id: str) -> dict
# provenance/source chain for a node

memory_manager.graph_active_tasks() -> list[dict]
# active task nodes from the graph

memory_manager.graph_belief_trail(belief_id: str) -> dict
# {"chain": list, "evidence": list}
```

### `agent_service`
```python
await agent_service.astatus(force: bool = False) -> AgentStatus
# .status: str   .llm: str   .memory: dict

await agent_service.aquota_status() -> list[dict]
# [{"model": str, "project_scope": str, "headroom": float, "rpm_limit": int, "rpd_limit": int}, ...]
```

## What NOT to Do
- Do not import `src.core.router` — use `agent_service.aquota_status()` instead
- Do not access `memory_manager.neo4j.*` directly — use `memory_manager.graph_*()` methods
- Do not access `memory_manager._health_cache_time` — use `memory_manager.invalidate_health_cache()`
- Do not import from other apps (`src.apps.chat`, etc.)
