# App: Explorer

Serves the knowledge graph UI and system status dashboard. Provides read-only graph
queries (nodes, relationships, provenance, tasks, belief trails) and a system health
endpoint that aggregates memory, agent, and LLM quota status.

## Files
| File | Role |
|------|------|
| `api.py` | FastAPI router — injects deps via `Depends()`, delegates to `services.py` |
| `services.py` | Graph queries and system status aggregation |
| `app.py` | `AppDefinition` registration (metadata only) |

## Allowed Imports (what this app may use)
```python
from fastapi import Depends
from src.agent_platform.public.agent_service import get_agent_service, AgentService
from src.memory.manager import get_memory_manager, MemoryManager
```

## Usage Pattern

**In `api.py` (routes):**
```python
@router.get("/graph/overview")
async def get_overview(
    limit: int = Query(100, ge=1, le=1000),
    memory: MemoryManager = Depends(get_memory_manager),
):
    return services.get_graph_overview(memory, limit=limit)

@router.get("/system/status")
async def get_system_status(
    memory: MemoryManager = Depends(get_memory_manager),
    service: AgentService = Depends(get_agent_service),
):
    return await services.get_system_status(memory, service)
```

**In `services.py` (business logic):**
```python
def get_graph_overview(memory: MemoryManager, limit: int = 100) -> dict: ...
def get_bootstrap_status(memory: MemoryManager) -> dict: ...
def bootstrap_user(name: str, memory: MemoryManager) -> dict: ...
def get_analyzer_status(memory: MemoryManager) -> dict: ...
def list_analyzer_models(memory: MemoryManager) -> list[dict]: ...
def run_analyzer(memory: MemoryManager, *, batch_size: int = 20, model: str | None = None) -> dict: ...
async def get_system_status(memory: MemoryManager, service: AgentService) -> dict: ...
```

## Public Methods Used from Each Dependency

### `MemoryManager` (public methods only)
```python
memory.status() -> dict
# {"status": "online"|"degraded"|"offline", "neo4j": str, "chroma": str}

memory.invalidate_health_cache() -> None
# forces the next status() call to re-probe backends (use before status() in /system/status)

memory.graph_overview(limit: int = 100) -> dict
memory.graph_node_detail(node_id: str) -> dict
memory.graph_node_provenance(node_id: str) -> dict
memory.graph_active_tasks() -> list[dict]
memory.graph_belief_trail(belief_id: str) -> dict

memory.user_root_exists() -> bool
memory.get_user_root() -> dict | None
memory.bootstrap_user_root(name: str) -> dict
# Hard-wipes the graph and seeds a `:Person:User` root. Used by the
# first-run bootstrap modal in the Explorer page.

memory.count_unanalyzed() -> int
memory.list_unanalyzed(limit: int = 50) -> list[dict]
memory.mark_analyzed(ids: list[str], run_id: str | None = None) -> int
# Used by the KnowledgeAnalyzer (under src/agent_platform/analyzers/) to drain
# the ChromaDB analysis queue.

memory.list_failed(limit: int = 50) -> list[dict]
memory.count_failed() -> int
memory.mark_failed(ids: list[str], reason: str, run_id: str | None = None) -> int
memory.retry_failed(memory_ids: list[str] | None = None) -> int
# Dead-letter queue for items the analyzer couldn't process (e.g. malformed
# LLM JSON). Used by /analyze/failed and /analyze/retry-failed.

memory.graph_schema_snapshot() -> dict
memory.upsert_node(*, node_id, labels, name, properties=None) -> str
memory.upsert_relationship(*, source_id, target_id, rel_type, properties=None) -> bool
# Used by the analyzer to write extracted facts into Neo4j.
```

### `AgentService`
```python
await service.astatus(force: bool = False) -> AgentStatus
# .status: str   .llm: str   .memory: dict

await service.aquota_status() -> list[dict]
# [{"model": str, "project_scope": str, "headroom": float, "rpm_limit": int, "rpd_limit": int}, ...]
```

## What NOT to Do
- Do not import `src.core.router` — use `service.aquota_status()` instead
- Do not access `memory.neo4j.*` directly — use `memory.graph_*()` methods
- Do not access `memory._health_cache_time` — use `memory.invalidate_health_cache()`
- Do not import from other apps (`src.apps.chat`, etc.)
- Do not use module-level singleton imports — always go through `Depends()` in routes
