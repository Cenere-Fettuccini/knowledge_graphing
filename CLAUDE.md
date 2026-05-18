# AIManager — Project Overview

Python monolith: FastAPI platform (`src/main.py`) + Telegram bot (`run_bot.py`).
Five pluggable apps share a common agent + memory infrastructure.

## Entry Points
- `src/main.py` — FastAPI server (port 8000), mounts all five apps
- `run_bot.py` — Telegram bot (uses the same agent/memory infrastructure)

## App Layer (`src/apps/`)
Five independent apps. **Apps must never import from each other.**

| App | Route prefix | Purpose |
|-----|-------------|---------|
| chat | `/apps/chat` | Conversational interface + session management |
| explorer | `/apps/explorer` | Knowledge graph visualization & system status |
| credits | `/apps/credits` | LLM quota management |
| financial_manager | `/apps/financial-manager` | Finance workflows (stub) |
| routine_scheduler | `/apps/routine-scheduler` | Scheduling/automation (stub) |

## Shared Infrastructure

Everything flows through these — nothing else should be imported from core internals.

| Factory / Import | Module | What it does |
|-----------------|--------|--------------|
| `get_memory_manager()` | `src.memory.manager` | Returns shared ChromaDB + Neo4j facade (lazy, created on first call) |
| `get_agent_service()` | `src.agent_platform.public.agent_service` | Returns shared agent gateway (lazy, created on first call) |
| `settings` | `src.core.config` | All config (env vars, API keys, DB URIs) |

## The Golden Rule for Apps

**FastAPI routes** inject dependencies via `Depends()`:
```python
from fastapi import Depends
from src.memory.manager import get_memory_manager, MemoryManager
from src.agent_platform.public.agent_service import get_agent_service, AgentService

@router.get("/endpoint")
async def my_endpoint(
    memory: MemoryManager = Depends(get_memory_manager),
    service: AgentService = Depends(get_agent_service),
):
    return services.my_func(memory, service)
```

**Service functions** accept dependencies as parameters:
```python
from src.memory.manager import MemoryManager
from src.agent_platform.public.agent_service import AgentService

def my_func(memory: MemoryManager, service: AgentService) -> dict:
    ...
```

**Non-FastAPI code** (tools, workers, bot) calls the factory directly:
```python
from src.memory.manager import get_memory_manager

def my_tool(param: str) -> str:
    memory = get_memory_manager()
    ...
```

**Apps do NOT import from:**
- `src.core.router`, `src.core.agent`, `src.core.context`, `src.core.limiter`
- Other apps (`src.apps.*`)
- `memory.neo4j.*` or `memory.chroma.*` — always use the public methods on `MemoryManager`

## Data Flow & Lifecycle

Every in-repo `CLAUDE.md` file has a `## Data Flow & Lifecycle` section with
the same shape:

- **Phases** — one or more of `boot`, `request`, `background`, `shutdown`, `ad-hoc`.
- **State** — one of `stateless`, `lazy singleton`, `lifespan-scoped`, `module-level`, `per-call`.
- **Inbound** / **Outbound** tables — each row is `From/To · Trigger · Payload · Mode`,
  where `Mode` ∈ `sync · async · lazy · scheduled · event`.
- **Diagnostic notes** — known chokepoints, where state crosses async boundaries,
  fan-in / fan-out hazards.

The **`/flows` page** in the web UI renders these connections as per-action
sequence diagrams (chat turn, nuke & reanalyse, run analyzer, etc.) annotated
with sync / async / fire-and-forget / lock-held / chokepoint / external I/O.
Use it to trace a single data path end-to-end.

Process-wide invariants worth remembering when reading the per-module sections:
- **Lazy singletons**: `MemoryManager` and `AgentService` are created on first
  call and live for process lifetime. Connection pools are not explicitly
  closed on shutdown — they rely on process exit.
- **Lazy back-edge**: `MemoryManager.store()` fires
  `graph_ingest_trigger.maybe_trigger` as a fire-and-forget event. This is the
  only place `memory` calls into `analyzers`.
- **LM Studio is a process-wide chokepoint**. Six entry points
  (`run_extraction_pass` × 4 + `refinement_extraction` + `deep_pass`) can each
  drive concurrent `chat_completion` calls. No global semaphore guards it
  today.
- **Locks are module-scoped**: `graph_ingest_trigger._lock` and
  `services._drain_lock` each guard one caller pattern — neither serialises
  against the others.

## Project Structure
```
src/
  apps/              # Five pluggable feature apps (see src/apps/*/CLAUDE.md)
  agent_platform/
    public/          # Public gateway — contracts + agent_service (see CLAUDE.md inside)
    tools/           # Agent tools: beliefs, graph, memory, tasks (see CLAUDE.md inside)
  core/              # LLM routing, config, rate limiting — INTERNAL, see src/core/CLAUDE.md
  memory/            # ChromaDB + Neo4j stores — INTERNAL, see src/memory/CLAUDE.md
  platform/          # FastAPI factory + app registry
  bot/               # Telegram bot
  frontend/          # Static UI assets
```

# Setup
If .env is missing, symlink from the main repo root:
ln -s /c/Users/Kevin/Desktop/AIManager/.env .env

## Running
```bash
python src/main.py    # Web platform
python run_bot.py     # Telegram bot
pytest tests/         # Test suite
```
