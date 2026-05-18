# App: Chat

Manages browser-based conversation sessions. Handles session CRUD, routes user
messages through the agent platform, and optionally anchors conversations to a
graph node from the Explorer app.

## Files
| File | Role |
|------|------|
| `api.py` | FastAPI router — injects deps via `Depends()`, delegates to `services.py` |
| `services.py` | All business logic: session management, context building, message dispatch |
| `app.py` | `AppDefinition` registration (metadata only) |

---

## Called By
| Caller | What it uses |
|--------|-------------|
| `src.platform.app_factory` | `get_chat_app()` — imports factory to register the app |
| HTTP clients (browser UI) | `POST /apps/chat/message`, `GET /apps/chat/sessions`, etc. |

---

## Calls Into
| Dependency | What is called |
|------------|---------------|
| `src.agent_platform.public.agent_service` | `get_agent_service()`, `AgentService`, `AgentRunRequest` |
| `src.memory.manager` | `get_memory_manager()`, `MemoryManager` |
| `src.platform.registry` | `AppDefinition` (in `app.py`) |

---

## Data Flow & Lifecycle

**Phases**: `request`

**State**: `stateless` (per-request)
- Routes inject `MemoryManager` and `AgentService` via `Depends()`; services accept them as parameters. No module-level state.

**Inbound**

| From | Trigger | Payload | Mode |
|------|---------|---------|------|
| Browser | POST `/apps/chat/message` | `{session_id, text, ...}` | `async` |
| Browser | GET `/apps/chat/sessions` | session list | `async` |
| Browser | GET `/apps/chat/history/{session_id}` | history fetch | `async` |
| Browser | DELETE `/apps/chat/sessions/{session_id}` | delete session | `async` |

**Outbound**

| To | Trigger | Payload | Mode |
|----|---------|---------|------|
| `src.agent_platform.public.agent_service.arun` | each message | `AgentRunRequest` | `async` |
| `src.memory.manager.store` | each user / assistant turn | text + metadata | `sync` |
| `src.memory.manager.get_history` | history endpoint | session-scoped read | `sync` |
| `src.memory.manager.list_sessions` | sessions endpoint | scan Chroma metadata | `sync` |
| `src.memory.manager.graph_node_detail` | when message is pinned to a node | node + connections | `sync` |

**Diagnostic notes**
- Chat is **purely synchronous from the user's perspective** — the reply only returns after `service.arun` completes. The lazy `maybe_trigger` after `store()` does NOT block.
- No app-level concurrency control. Two browsers in the same session can interleave turns; ordering is whoever's `store()` lands first in Chroma.

---

## Allowed Imports
```python
from fastapi import Depends
from src.agent_platform.public.agent_service import get_agent_service, AgentService
from src.agent_platform.public.contracts import AgentRunRequest
from src.memory.manager import get_memory_manager, MemoryManager
```

---

## Route → Service Flow

**`api.py` routes inject dependencies and call `services.py`:**
```python
@router.post("/message")
async def post_message(
    body: dict = Body(...),
    memory: MemoryManager = Depends(get_memory_manager),
    service: AgentService = Depends(get_agent_service),
):
    return await services.send_chat_message(..., memory=memory, service=service)
```

**`services.py` functions accept dependencies as parameters:**
```python
def list_chat_sessions(memory: MemoryManager) -> dict: ...
async def send_chat_message(..., memory: MemoryManager, service: AgentService) -> dict: ...
```

---

## Public Methods Used from Each Dependency

### `AgentService`
```python
await service.arun(request: AgentRunRequest) -> AgentRunResult
# .reply: str   .session_id: str   .reply_timestamp: str | None
# .memory_degraded: bool   .memory_health: dict | None
```

### `MemoryManager`
```python
memory.get_history(session_id: str, limit: int = 20) -> list[dict]
# each: {"id": str, "text": str, "metadata": {"role": str, "timestamp": str, ...}}

memory.list_sessions(limit: int = 500) -> dict
# {"documents": list[str], "metadatas": list[dict]}

memory.graph_node_detail(node_id: str) -> dict
# {"node": {id, label, name, ...}, "connections": [{type, target}, ...]}

memory.delete_session(session_id: str) -> bool
```

---

## What NOT to Do
- Do not import `src.core.router` or any other `src.core.*` internals
- Do not access `memory.neo4j.*` or `memory.chroma.*` directly
- Do not import from other apps (`src.apps.explorer`, etc.)
- Do not use module-level singleton imports — always go through `Depends()` in routes
