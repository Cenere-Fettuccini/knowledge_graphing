# Agent Platform — Public Gateway

The **only** entry point apps use to run the agent. Hides all internals:
prompt assembly, memory retrieval, model routing, tool execution.

## Files
| File | Role |
|------|------|
| `contracts.py` | Frozen dataclasses: `AgentRunRequest`, `AgentRunResult`, `AgentStatus`, `MemorySearchRequest` |
| `agent_service.py` | `AgentService` class + `get_agent_service()` lazy factory |

---

## Called By
| Caller | What it uses |
|--------|-------------|
| `src.apps.chat.api` / `.services` | `AgentService` via `Depends(get_agent_service)`, `AgentRunRequest` |
| `src.apps.explorer.api` / `.services` | `AgentService` via `Depends(get_agent_service)` |
| `src.bot.proactive` | `get_agent_service()`, `AgentService` |
| `src.rumination.engine` | `get_agent_service()`, `AgentService` — passed to `DeepPass` |

---

## Calls Into
| Dependency | What is called |
|------------|---------------|
| `src.core.agent` | `Agent`, `BaseAgent` — the gateway wraps the agent |
| `src.memory.manager` | `get_memory_manager()` — passed to `Agent` constructor |
| `src.core.router` | `llm_router` — for `aquota_status()` headroom data |
| `src.agent_platform.public.contracts` | `AgentRunRequest`, `AgentRunResult`, `AgentStatus` |

---

## Contracts (`contracts.py`)

```python
@dataclass(frozen=True)
class AgentRunRequest:
    app_id: str              # identifies the calling app ("chat", "explorer", ...)
    user_id: str
    session_id: str
    message: str             # raw user text — stored in memory as-is
    message_timestamp: str | None = None   # ISO 8601
    prompt_text: str | None = None         # assembled prompt (overrides default if set)
    store_text: str | None = None          # what goes into memory (defaults to message)
    store_metadata: dict = {}
    context: dict = {}

@dataclass(frozen=True)
class AgentRunResult:
    app_id: str
    session_id: str
    reply: str
    reply_timestamp: str | None = None
    memory_degraded: bool = False
    memory_health: dict | None = None

@dataclass(frozen=True)
class AgentStatus:
    status: str       # "online" | "degraded" | "offline"
    llm: str          # description of the active model
    memory: dict      # same shape as memory_manager.status()

@dataclass(frozen=True)
class MemorySearchRequest:
    query: str
    session_id: str | None = None
    k: int = 5
    include_ephemeral: bool = True
```

---

## Agent Service API (`agent_service.py`)

```python
# Synchronous
service.run(request: AgentRunRequest) -> AgentRunResult
service.status(force: bool = False) -> AgentStatus
service.get_history(session_id: str, limit: int = 20) -> list[dict]
service.clear_session(session_id: str) -> None

# Async (prefer these in FastAPI endpoints)
await service.arun(request: AgentRunRequest) -> AgentRunResult
await service.astatus(force: bool = False) -> AgentStatus
await service.aquota_status() -> list[dict]
# aquota_status returns: [{"model": str, "project_scope": str, "headroom": float,
#                          "rpm_limit": int, "rpd_limit": int}, ...]

def get_agent_service() -> AgentService   # Lazy singleton factory
```

---

## Typical App Usage Pattern

**In `api.py` (routes):**
```python
from fastapi import Depends
from src.agent_platform.public.agent_service import get_agent_service, AgentService
from src.agent_platform.public.contracts import AgentRunRequest
from src.apps.my_app import services

@router.post("/message")
async def post_message(
    body: dict,
    service: AgentService = Depends(get_agent_service),
):
    return await services.handle_message(body, service)
```

**In `services.py` (business logic):**
```python
from src.agent_platform.public.agent_service import AgentService
from src.agent_platform.public.contracts import AgentRunRequest

async def handle_message(body: dict, service: AgentService) -> dict:
    result = await service.arun(AgentRunRequest(
        app_id="my_app",
        user_id="web_user",
        session_id=body["session_id"],
        message=body["text"],
        store_metadata={"app_id": "my_app"},
    ))
    return {"reply": result.reply}
```

---

## Coupling Notes
- `AgentService` is a thin facade — it delegates to `src.core.agent.Agent`.
  The reason for the wrapper is to decouple app code from agent internals and
  to allow `Agent` to be swapped or mocked without changing app code.
- `get_agent_service()` is a lazy singleton. It creates `Agent` on first call,
  which itself calls `get_memory_manager()`. Both singletons are shared across
  the entire process.
- `aquota_status()` reads `llm_router` directly — this is the one place the
  gateway touches router internals, so apps do not need to.
- For non-FastAPI callers (`ProactiveBot`, `RuminationScheduler`), call
  `get_agent_service()` directly instead of using `Depends()`.
