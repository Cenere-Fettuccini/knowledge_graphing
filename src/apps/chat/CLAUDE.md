# App: Chat

Manages browser-based conversation sessions. Handles session CRUD, routes user messages
through the agent platform, and optionally anchors conversations to a graph node from
the Explorer app.

## Files
| File | Role |
|------|------|
| `api.py` | FastAPI router — injects deps via `Depends()`, delegates to `services.py` |
| `services.py` | All business logic: session management, context building, message dispatch |
| `app.py` | `AppDefinition` registration (metadata only) |

## Allowed Imports (what this app may use)
```python
from fastapi import Depends
from src.agent_platform.public.agent_service import get_agent_service, AgentService
from src.agent_platform.public.contracts import AgentRunRequest
from src.memory.manager import get_memory_manager, MemoryManager
```

## Usage Pattern

**In `api.py` (routes):**
```python
@router.post("/message")
async def post_message(
    body: dict = Body(...),
    memory: MemoryManager = Depends(get_memory_manager),
    service: AgentService = Depends(get_agent_service),
):
    return await services.send_chat_message(..., memory=memory, service=service)
```

**In `services.py` (business logic):**
```python
def list_chat_sessions(memory: MemoryManager) -> dict: ...
async def send_chat_message(..., memory: MemoryManager, service: AgentService) -> dict: ...
```

## Public Methods Used from Each Dependency

### `AgentService`
```python
await service.arun(request: AgentRunRequest) -> AgentRunResult
# .reply: str   .session_id: str   .reply_timestamp: str | None
```

### `MemoryManager` (public methods only)
```python
memory.get_history(session_id: str, limit: int = 20) -> list[dict]
# each item: {"id": str, "text": str, "metadata": {"role": str, "timestamp": str, ...}}

memory.list_sessions(limit: int = 500) -> dict
# {"documents": list[str], "metadatas": list[dict]}

memory.graph_node_detail(node_id: str) -> dict
# {"node": {id, label, name, ...}, "connections": [{type, target}, ...]}

memory.delete_session(session_id: str) -> bool
```

## What NOT to Do
- Do not import `src.core.router` or any other `src.core.*` internals
- Do not access `memory.neo4j.*` or `memory.chroma.*` directly
- Do not import from other apps (`src.apps.explorer`, etc.)
- Do not use module-level singleton imports — always go through `Depends()` in routes
