# App: Financial Manager

Stub app for money workflows, financial analysis, and finance-safe tools.
Currently only registers its `AppDefinition` — no services or API layer yet.

## Files
| File | Role |
|------|------|
| `app.py` | `AppDefinition` registration — id, name, route_prefix, icon, status |

---

## Called By
| Caller | What it uses |
|--------|-------------|
| `src.platform.app_factory` | `get_financial_manager_app()` — imports factory to register the app |

---

## Calls Into
| Dependency | What is called |
|------------|---------------|
| `src.platform.registry` | `AppDefinition` (in `app.py`) |

---

## Data Flow & Lifecycle

**Phases**: *(none yet — stub)*

**State**: `stateless`

**Inbound**: none beyond the registry hand-off in `src.platform.app_factory`.

**Outbound**: none beyond `AppDefinition` registration.

**Diagnostic notes**
- Stub app. When real endpoints land, follow the chat / explorer pattern: routes inject `MemoryManager` and `AgentService` via `Depends()`, services accept them as parameters.

---

## Adding Features to This App
Follow the same pattern as `chat` or `explorer`:

1. Create `services.py` with pure business logic functions
2. Create `api.py` with a FastAPI `APIRouter` that delegates to `services.py`
3. Update `app.py` to wire in the router and `api_prefix`

**Allowed imports:**
```python
# In api.py (routes) — inject via Depends():
from fastapi import Depends
from src.agent_platform.public.agent_service import get_agent_service, AgentService
from src.memory.manager import get_memory_manager, MemoryManager

# In services.py — accept as parameters:
from src.agent_platform.public.agent_service import AgentService
from src.agent_platform.public.contracts import AgentRunRequest
from src.memory.manager import MemoryManager
from src.core.config import settings
```

---

## What NOT to Do
- Do not import from other apps
- Do not import `src.core.router` or other `src.core.*` internals
- Do not access `memory.neo4j.*` or `memory.chroma.*` directly
- Do not use module-level singleton imports — always go through `Depends()` in routes
