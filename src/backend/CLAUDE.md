# aimanager.backend

Platform machinery. Hosts subsystems that are shared across all apps
and entry points: the FastAPI factory and registry, the conversation
orchestrator, and (planned) cross-cutting HTTP endpoints and the
background extraction worker.

Adding or removing an app does not change anything in this directory.

## Submodules

Each subpackage is documented in its own `CLAUDE.md`:

| Submodule | Purpose | Status |
|---|---|---|
| [`backend.platform`](platform/CLAUDE.md) | FastAPI app factory + app registry | Planned implementation |
| [`backend.conversation`](conversation/CLAUDE.md) | Conversation orchestrator — runs a turn end-to-end, called by both HTTP chat and Telegram bot | Planned implementation |
| `backend.api` (planned) | Cross-cutting HTTP endpoints (health, ingest, etc.) | Not in MVP |
| `backend.analysis_queue` (planned) | Background worker for graph extraction | Not in MVP |

## Public surface

The backend exposes its submodules through their own `__init__.py`
files. Consumers import directly from the submodule:

```python
from src.backend.platform     import create_platform_app, AppDefinition, AppRegistry
from src.backend.conversation import Conversation, TurnResult, ConversationError, get_conversation
```

There is no `from src.backend import …`. The `backend/__init__.py` is
intentionally empty.

## Dependency direction within backend

```
backend.platform   ← imports apps (only for factory discovery)
backend.conversation ← imports memory, agent
backend.api        ← imports memory (when implemented)
backend.analysis_queue ← imports agent, memory (when implemented)
```

Submodules under `backend/` are siblings — they do not import each
other. The composition root is `src/main.py`, which imports
`create_platform_app` only.

## Dependency direction with the rest of the system

| Caller | Allowed imports |
|---|---|
| `src.main` | `src.backend.platform.create_platform_app` only |
| `apps/<name>/api.py` | `src.backend.conversation`, `src.backend.platform.AppDefinition`, `src.memory`, `src.agent`, `src.log` |
| `apps/<name>/app.py` | `src.backend.platform.AppDefinition` |
| `bot/` | `src.backend.conversation`, `src.memory` (for session ops), `src.log` |

`backend.*` modules never import `apps/`, `bot/`, or `frontend/`.

## Anti-patterns

- Adding cross-submodule imports inside `backend/` (e.g. `backend.platform` importing `backend.conversation`). They should remain peers wired by `src/main.py`.
- Putting app-specific logic in any `backend/` submodule.
- Bypassing `backend.conversation` from `apps/chat/api.py` or `bot/_handlers.py` to call agent + memory directly — that defeats the purpose of the orchestrator.
