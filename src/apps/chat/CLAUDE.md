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
