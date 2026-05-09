# Agent Platform — Public Gateway

This is the **only** entry point apps use to run the agent.
It hides all internals: prompt assembly, memory retrieval, model routing, tool execution.

## Files
| File | Role |
|------|------|
| `contracts.py` | Frozen dataclasses: `AgentRunRequest`, `AgentRunResult`, `AgentStatus`, `MemorySearchRequest` |
| `agent_service.py` | `AgentService` class + `agent_service` singleton |

## Contracts (`contracts.py`)

```python
@dataclass(frozen=True)
class AgentRunRequest:
    app_id: str              # identifies the calling app ("chat", "explorer", ...)
    user_id: str             # identifies the user
    session_id: str          # conversation session identifier
    message: str             # raw user text — stored in memory as-is
    message_timestamp: str | None = None   # ISO 8601 timestamp
    prompt_text: str | None = None         # assembled prompt (overrides default if set)
    store_text: str | None = None          # what goes into memory (defaults to message)
    store_metadata: dict = {}              # extra metadata to store alongside the turn
    context: dict = {}                     # structured context passed to the agent

@dataclass(frozen=True)
class AgentRunResult:
    app_id: str
    session_id: str
    reply: str
    reply_timestamp: str | None = None

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

## Agent Service (`agent_service`)

```python
# Synchronous
agent_service.run(request: AgentRunRequest) -> AgentRunResult
agent_service.status(force: bool = False) -> AgentStatus
agent_service.get_history(session_id: str, limit: int = 20) -> list[dict]
agent_service.clear_session(session_id: str) -> None

# Async (prefer these in FastAPI endpoints)
await agent_service.arun(request: AgentRunRequest) -> AgentRunResult
await agent_service.astatus(force: bool = False) -> AgentStatus
await agent_service.aquota_status() -> list[dict]
# aquota_status returns: [{"model": str, "project_scope": str, "headroom": float,
#                          "rpm_limit": int, "rpd_limit": int}, ...]
```

## Typical App Usage Pattern
```python
from src.agent_platform.public.agent_service import agent_service
from src.agent_platform.public.contracts import AgentRunRequest

result = await agent_service.arun(AgentRunRequest(
    app_id="my_app",
    user_id="web_user",
    session_id=session_id,
    message=user_text,
    prompt_text=assembled_prompt,   # optional override
    store_text=user_text,
    store_metadata={"app_id": "my_app", ...},
))
# result.reply  — the agent's response string
# result.reply_timestamp  — ISO timestamp
```
