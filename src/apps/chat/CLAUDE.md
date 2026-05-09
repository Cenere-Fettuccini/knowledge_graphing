# App: Chat

Manages browser-based conversation sessions. Handles session CRUD, routes user messages
through the agent platform, and optionally anchors conversations to a graph node from
the Explorer app.

## Files
| File | Role |
|------|------|
| `api.py` | FastAPI router — thin HTTP layer, delegates everything to `services.py` |
| `services.py` | All business logic: session management, context building, message dispatch |
| `app.py` | `AppDefinition` registration (metadata only) |

## Allowed Imports (what this app may use)
```python
from src.agent_platform.public.agent_service import agent_service
from src.agent_platform.public.contracts import AgentRunRequest
from src.memory.manager import memory_manager
```

## Public Methods Used from Each Import

### `agent_service`
```python
await agent_service.arun(request: AgentRunRequest) -> AgentRunResult
# .reply: str   .session_id: str   .reply_timestamp: str | None
```

### `memory_manager` (public methods only)
```python
memory_manager.get_history(session_id: str, limit: int = 20) -> list[dict]
# each item: {"id": str, "text": str, "metadata": {"role": str, "timestamp": str, ...}}

memory_manager.list_sessions(limit: int = 500) -> dict
# {"documents": list[str], "metadatas": list[dict]}

memory_manager.graph_node_detail(node_id: str) -> dict
# {"node": {id, label, name, ...}, "connections": [{type, target}, ...]}

memory_manager.delete_session(session_id: str) -> bool
```

### `AgentRunRequest` fields
```python
AgentRunRequest(
    app_id="chat",
    user_id="web_user",
    session_id=str,
    message=str,               # raw user text (stored as-is)
    message_timestamp=str,     # ISO timestamp, optional
    prompt_text=str,           # assembled prompt (may include context)
    store_text=str,            # what goes into memory
    store_metadata=dict,
    context=dict,
)
```

## What NOT to Do
- Do not import `src.core.router` or any other `src.core.*` internals
- Do not access `memory_manager.neo4j.*` or `memory_manager.chroma.*` directly
- Do not import from other apps (`src.apps.explorer`, etc.)
