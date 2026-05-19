# aimanager.apps

Vertical product surfaces. Each app is a self-contained slice: app
registration, HTTP routes, business logic, and static UI assets in one
folder. Apps are discovered and mounted by the platform layer at server
startup.

**Status:** chat — planned implementation. Flows page — planned. Others — future.

## Folder shape (per app)

```
apps/
  <name>/
    __init__.py        Public export — only the factory
    app.py             AppDefinition + get_<name>_app() factory
    api.py             FastAPI router (private to the app)
    services.py        Business logic (private to the app)
    static/            Per-app HTML / CSS / JS — served by the shell
```

## Public API per app

Each app's `__init__.py` exports exactly one symbol:

```python
__all__ = ["get_<name>_app"]
```

The factory returns an `AppDefinition` (defined in
`aimanager.backend.platform`) describing the app's id, route prefix,
FastAPI router, and static directory.

```python
from src.apps.chat import get_chat_app   # called by backend.platform.app_factory

app_def = get_chat_app()
# AppDefinition(
#     id="chat",
#     name="Chat",
#     route_prefix="/apps/chat",
#     api_router=<APIRouter>,
#     api_prefix="/apps/chat",
#     static_dir=Path(".../apps/chat/static"),
# )
```

Everything else inside an app — `api.py`, `services.py`, `static/` —
is internal to that app and not part of any public contract.

## Allowed imports inside an app

Apps depend only on the published platform contracts:

```python
from fastapi import Depends
from src.memory import MemoryManager, get_memory_manager
from src.agent import (
    AgentService, AgentRunRequest, AgentRunResult, get_agent_service,
)
from src.backend.platform import AppDefinition
```

Apps must not import from other apps, from agent internals, or from
memory internals.

## Implemented apps

### chat (planned)

User-facing conversational interface.

**Public exports:** `get_chat_app`

**HTTP surface** (mounted under `/apps/chat`):

| Method | Path | Description |
|---|---|---|
| `POST` | `/message` | Send a user message; returns the agent reply. |
| `GET` | `/sessions` | List active sessions for the current user. |
| `GET` | `/history/{session_id}` | Return conversation history. |
| `DELETE` | `/sessions/{session_id}` | Delete a session. |

**Request/response shapes:**

```jsonc
// POST /apps/chat/message
{ "session_id": "...", "text": "..." }
// → { "session_id": "...", "reply": "...", "timestamp": "..." }
```

**Static assets:** `static/chat-page.js`, `static/chat.css`.

**Per-request flow:**

```
1. Browser fetch → POST /apps/chat/message
2. api.py route handler validates body, injects Conversation via Depends
3. result = await conversation.handle_turn(session_id, text, parent_turn_id=...)
     (internally: memory.append user → memory.recent_turns → agent.arun → memory.append assistant)
4. api.py returns {"reply": result.reply, "user_turn_id": ..., "assistant_turn_id": ...}
5. Response serialised by FastAPI
6. Browser updates DOM in static/chat-page.js
```

For edit / regenerate, the request body carries `parent_turn_id`;
`Conversation.handle_turn` passes it through to memory, producing a
sibling instead of a continuation.

Session-management endpoints (`GET /sessions`, `DELETE /sessions/{id}`)
inject `MemoryManager` directly and call `memory.list_sessions()` /
`memory.delete_session()` — they do not go through `Conversation`
because they do not run a turn.

### flows (planned)

Single-screen visualization of the platform's data flow and component
graph. The page renders nodes (subsystems: apps, agent, memory, platform)
and edges (HTTP calls, async LLM calls, JSONL writes, events) using
D3.js force layout. Two modes:

- **Scenario mode** — predefined paths are highlighted while others
  dim. Example scenarios: "chat message," "tool call," "memory read."
- **Node-focus mode** — clicking a node dims the graph except for that
  node and its immediate neighbors (incoming + outgoing edges).

**Public exports:** `get_flows_app`

**HTTP surface** (mounted under `/apps/flows`):

| Method | Path | Description |
|---|---|---|
| `GET` | `/graph` | Return the full flow graph: `{nodes, edges, scenarios}`. |
| `GET` | `/scenarios` | List available scenarios. |
| `GET` | `/scenarios/{name}` | Return the highlighted edge IDs for a scenario. |

**Graph data shape:**

```jsonc
{
  "nodes": [
    {
      "id": "apps_chat",
      "label": "apps/chat",
      "layer": "app",          // "app" | "agent" | "memory" | "platform" | "external"
      "kind": "feature",       // "feature" | "service" | "store" | "client"
      "description": "Chat user-facing app",
      "claudeMd": "src/apps/CLAUDE.md"
    }
  ],
  "edges": [
    {
      "id": "chat_to_agent",
      "source": "apps_chat",
      "target": "agent_service",
      "kind": "async_call",     // "async_call" | "sync_call" | "http" | "jsonl_write" | "event"
      "label": "service.arun()",
      "scenarios": ["chat_message"]
    }
  ],
  "scenarios": [
    { "name": "chat_message", "label": "User chat turn", "edges": ["chat_to_agent", "agent_to_memory", ...] }
  ]
}
```

**Static assets:** `static/flows-page.js`, `static/flows.css`.

**Rendering reference (for the implementation):**

- Single SVG, full viewport.
- D3 `forceSimulation` with `forceLink`, `forceManyBody`, `forceCenter`.
- Node colour by `layer`; node shape by `kind`.
- Edge colour by `kind`; edge style: solid for sync, dashed for async, dotted for event.
- Hover a node: show its description in a side panel; surface `claudeMd` link.
- Click a node: enter node-focus mode. Click background to exit.
- Toolbar at top selects scenario (radio buttons) or "all flows."
- Keyboard: `Esc` exits any focus mode; arrow keys cycle scenarios.

**Data source:** `services.build_flow_graph()` reads CLAUDE.md frontmatter
or a hard-coded structure to produce the graph payload. (Implementation
detail — not part of the public API.)

## Adding a new app

1. Create `apps/<name>/__init__.py`, `app.py`, `api.py`, `services.py`, and (optional) `static/`.
2. Implement `get_<name>_app() -> AppDefinition` in `app.py`.
3. Export it from `__init__.py` with `__all__ = ["get_<name>_app"]`.
4. Register the factory in `backend.platform.app_factory.build_registry()`.
5. If the app has a UI, add a `<script>` for its page JS in the frontend shell (or register it via the shell's manifest).

The shell picks up the new app on next boot.

## Stability and versioning

The per-app public surface (`get_<name>_app`) and the HTTP endpoints
declared above are the contract.

- **Non-breaking:** new endpoints, new optional request fields, new response fields.
- **Breaking (major version):** removing endpoints, changing path or method, removing response fields, narrowing types.

## Internals

`api.py`, `services.py`, request/response Pydantic models, and helper
functions in an app are not part of the public API and may change
without notice.

## Anti-patterns

- Importing across apps (`from src.apps.chat import ...` inside `apps/flows`).
- Importing app internals from outside the app (`from src.apps.chat.services import ...`).
- Module-level singletons; use `Depends` in routes and parameter passing in services.
- Mixing UI assets across apps; each app owns its own `static/`.
