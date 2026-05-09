# App: Routine Scheduler

Stub app for scheduling routines, recurring structures, and calendar-driven automation.
Currently only registers its `AppDefinition` — no services or API layer yet.

## Files
| File | Role |
|------|------|
| `app.py` | `AppDefinition` registration — id, name, route_prefix, icon, status |
| `static/index.html` | Placeholder UI |

## Adding Features to This App
When building out this app, follow the same pattern as `chat` or `explorer`:

1. Create `services.py` with pure business logic functions
2. Create `api.py` with a FastAPI `APIRouter` that delegates to `services.py`
3. Update `app.py` to wire in the router

**Allowed imports for services.py:**
```python
from src.agent_platform.public.agent_service import agent_service
from src.agent_platform.public.contracts import AgentRunRequest
from src.memory.manager import memory_manager
from src.core.config import settings
```

## What NOT to Do
- Do not import from other apps
- Do not import `src.core.router` or other `src.core.*` internals
- Do not access `memory_manager.neo4j.*` or `memory_manager.chroma.*` directly
