# App: Explorer

Serves the knowledge graph UI and system status dashboard. Provides read-only
graph queries (nodes, relationships, provenance, tasks, belief trails), analyzer
controls, canonicalization, era management, and a system health endpoint that
aggregates memory, agent, and LLM quota status.

## Files
| File | Role |
|------|------|
| `api.py` | FastAPI router — injects deps via `Depends()`, delegates to `services.py` |
| `services.py` | Graph queries, system status, analyzer coordination, bulk import |
| `app.py` | `AppDefinition` registration (metadata only) |

---

## Called By
| Caller | What it uses |
|--------|-------------|
| `src.platform.app_factory` | `get_explorer_app()` — imports factory to register the app |
| HTTP clients (browser UI) | 50+ endpoints: graph, analyze, canonicalize, eras, beliefs, schema |

---

## Calls Into
| Dependency | What is called |
|------------|---------------|
| `src.agent_platform.public.agent_service` | `get_agent_service()`, `AgentService` |
| `src.memory.manager` | `get_memory_manager()`, `MemoryManager` |
| `src.agent_platform.analyzers.graph_ingest_trigger` | `run_extraction_pass()` — manual analyze endpoint + post-bulk-ingest |
| `src.agent_platform.analyzers.cloud_belief_extraction` | `run_belief_extraction_once()` — belief extraction endpoint |
| `src.agent_platform.analyzers.contradiction_detection` | `run_contradiction_detection()` — contradiction endpoint |
| `src.agent_platform.analyzers.schema_drift` | `check_drift()`, `take_snapshot()` |
| `src.agent_platform.analyzers.canonicalize` | `EntityCanonicalizer`, `BeliefCanonicalizer` |
| `src.agent_platform.analyzers.local_llm` | `LMStudioClient` — for analyzer status/model list |
| `src.ingestion.bulk_importer` | `BulkImporter` — bulk import endpoint |
| `src.platform.registry` | `AppDefinition` (in `app.py`) |

---

## Allowed Imports
```python
from fastapi import Depends
from src.agent_platform.public.agent_service import get_agent_service, AgentService
from src.memory.manager import get_memory_manager, MemoryManager
# Analyzer imports are allowed — explorer is the admin surface for analyzers
from src.agent_platform.analyzers.graph_ingest_trigger import run_extraction_pass
from src.agent_platform.analyzers.canonicalize import EntityCanonicalizer, BeliefCanonicalizer
from src.agent_platform.analyzers.local_llm import LMStudioClient
from src.ingestion.bulk_importer import BulkImporter
```

---

## Route → Service Flow

**`api.py` routes inject dependencies and call `services.py`:**
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

**`services.py` functions:**
```python
def get_graph_overview(memory: MemoryManager, limit: int = 100) -> dict
def get_bootstrap_status(memory: MemoryManager) -> dict
def bootstrap_user(name: str, memory: MemoryManager) -> dict
def get_analyzer_status(memory: MemoryManager) -> dict
def list_analyzer_models(memory: MemoryManager) -> list[dict]
async def run_analyzer(memory: MemoryManager, *, batch_size: int = 20, model: str | None = None) -> dict
async def get_system_status(memory: MemoryManager, service: AgentService) -> dict
async def run_bulk_import(path: str, memory: MemoryManager) -> dict
def run_canonicalization(target: str, memory: MemoryManager) -> dict
```

---

## Public Methods Used from Each Dependency

### `AgentService`
```python
await service.astatus(force: bool = False) -> AgentStatus
await service.aquota_status() -> list[dict]
# [{"model": str, "project_scope": str, "headroom": float, "rpm_limit": int, "rpd_limit": int}]
```

### `MemoryManager` (key methods — see `src/memory/CLAUDE.md` for full list)
```python
memory.status() -> dict                       # health check
memory.invalidate_health_cache() -> None
memory.graph_overview(limit, era_id, active_self_only) -> dict
memory.graph_node_detail(node_id) -> dict
memory.graph_node_provenance(node_id) -> dict
memory.graph_active_tasks(include_completed, since) -> list[dict]
memory.graph_belief_trail(belief_id) -> dict
memory.user_root_exists() -> bool
memory.get_user_root() -> dict | None
memory.bootstrap_user_root(name) -> dict
memory.count_unanalyzed() -> int
memory.list_unanalyzed(limit) -> list[dict]
memory.mark_analyzed(ids, run_id=None) -> int
memory.count_failed() -> int
memory.list_failed(limit) -> list[dict]
memory.mark_failed(ids, reason, run_id=None) -> int
memory.retry_failed(memory_ids=None) -> int
memory.list_distinct_graph_labels(exclude=None) -> list[str]
memory.list_named_nodes_by_label(label, exclude_roots=True) -> list[dict]
memory.count_node_connections(node_ids) -> dict[str, int]
memory.list_active_beliefs(limit=1000) -> list[dict]
memory.create_merge_proposal(...) -> str
memory.list_merge_proposals(status, limit) -> list[dict]
memory.apply_merge_proposal(proposal_id) -> dict
memory.dismiss_merge_proposal(proposal_id) -> bool
memory.graph_schema_snapshot() -> dict
memory.list_eras(active_only) -> list[dict]
memory.upsert_era(...) -> dict
memory.delete_era(era_id) -> bool
memory.bind_node_to_era(node_id, era_id) -> bool
memory.count_belief_candidates() -> int
memory.list_pending_beliefs(limit) -> list[dict]
memory.approve_pending_belief(belief_id) -> dict
memory.reject_pending_belief(belief_id, reason) -> dict
memory.list_contradictions(limit) -> list[dict]
memory.belief_calibration() -> dict
memory.graph_neighborhood(node_id, depth, limit) -> dict
memory.eras_active_at(date) -> dict
```

---

## What NOT to Do
- Do not import `src.core.router` — use `service.aquota_status()` instead
- Do not access `memory.neo4j.*` directly — use `memory.graph_*()` methods
- Do not import from other apps (`src.apps.chat`, etc.)
- Do not use module-level singleton imports — always go through `Depends()` in routes
