# Platform — FastAPI App Factory & Registry

Assembles the FastAPI application: registers all five apps, mounts routes,
configures lifespan hooks (memory warm-up, rumination scheduler), and provides
the shell/graph-ingest routers.

## Files
| File | Role |
|------|------|
| `app_factory.py` | `create_platform_app()` — builds and returns the `FastAPI` instance |
| `registry.py` | `AppDefinition` dataclass + `AppRegistry` — app metadata and mounting |
| `shell.py` | `build_shell_router()` — `/api/apps` metadata endpoint used by the UI |
| `graph_ingest.py` | `build_graph_ingest_router()` — `POST /graph/ingest` shared-secret HTTP entry point |

---

## Called By
| Caller | What it uses |
|--------|-------------|
| `src/main.py` | `create_platform_app()` — the single entry point to build the server |

---

## Calls Into
| Dependency | What is imported |
|------------|-----------------|
| `src.apps.chat.app` | `get_chat_app()` |
| `src.apps.explorer.app` | `get_explorer_app()` |
| `src.apps.credits.app` | `get_credits_app()` |
| `src.apps.financial_manager.app` | `get_financial_manager_app()` |
| `src.apps.routine_scheduler.app` | `get_routine_scheduler_app()` |
| `src.memory.manager` | `get_memory_manager()` — warm-up in lifespan |
| `src.rumination.engine` | `RuminationScheduler` — started/stopped in lifespan |
| `src.core.config` | `settings` |
| `src.core.logging_config` | `setup_logging()` |

---

## Data Flow & Lifecycle

**Phases**: `boot` · `shutdown` · `request`

**State**: `lifespan-scoped`
- `AppRegistry` instance built inside `create_platform_app()`. Holds the five `AppDefinition`s for the lifetime of the FastAPI app.
- `RuminationScheduler` started in the lifespan startup hook, stopped in shutdown.
- No state in `graph_ingest.py` — it's just a router factory.

**Inbound**

| From | Trigger | Payload | Mode |
|------|---------|---------|------|
| `src/main.py` | process start | `create_platform_app()` | `sync` |
| uvicorn | FastAPI lifespan enter | startup hook fires | `async` |
| uvicorn | FastAPI lifespan exit | shutdown hook fires | `async` |
| external HTTP client | POST `/graph/ingest` with `X-Ingest-Secret` | batch of intents | `async` |

**Outbound**

| To | Trigger | Payload | Mode |
|----|---------|---------|------|
| `src.apps.*` | startup | `get_<app>_app()` × 5 → mount routers | `sync` |
| `src.memory.manager` | startup | `get_memory_manager()` warm-up | `lazy` |
| `src.rumination.engine` | startup / shutdown | `RuminationScheduler(...).start()` / `.stop()` | `async` |
| `src.agent_platform.analyzers.graph_ingest_trigger` | POST `/graph/ingest` | `run_extraction_pass(memory, batch_size)` | `async` (no lock) |
| `src.core.logging_config` | startup | `setup_logging()` | `sync` |

**Diagnostic notes**
- `app_factory.py` is the *only* place that imports all five `get_<app>_app()` factories. Adding an app means editing this file.
- `graph_ingest.py` is one of three lock-free entry points into `run_extraction_pass` (along with manual `/analyze/run` and `drain_after_reset`).
- The lifespan does not explicitly close memory pools — relies on process exit.

---

## Public API

### `app_factory.py`
```python
def create_platform_app() -> FastAPI:
    """Build the configured FastAPI app. Called once from src/main.py."""
```

### `registry.py`
```python
@dataclass(frozen=True)
class AppDefinition:
    id: str
    name: str
    description: str
    route_prefix: str          # e.g. "/apps/chat"
    section_role: str
    static_dir: Path | None = None
    api_prefix: str | None = None
    api_router: object | None = None
    icon: str = "App"
    status: str = "active"
    legacy_api_prefixes: tuple[str, ...] = ()
    legacy_route_prefixes: tuple[str, ...] = ()

@dataclass
class AppRegistry:
    def register(app_def: AppDefinition) -> None
    def list_apps() -> list[AppDefinition]
    def iter_active_apps() -> Iterable[AppDefinition]
```

Every app's `app.py` imports `AppDefinition` from here and returns an instance
via its `get_<app>_app()` factory. `app_factory.py` calls all five factories,
registers them, and mounts their routers.

### `graph_ingest.py`
```python
def build_graph_ingest_router() -> APIRouter:
    """POST /graph/ingest — accepts batched graph writes with a shared secret.
    Calls get_memory_manager() and run_extraction_pass() from analyzers."""
```

The ingest endpoint is a back-channel for external pipelines. It verifies
`X-Ingest-Secret` against `settings.graph_ingest_secret` before writing.

---

## Coupling Notes
- `app_factory.py` is the **only place** that imports all five app factories.
  Adding a new app means importing its factory here and calling `registry.register()`.
- `graph_ingest.py` directly imports `graph_ingest_trigger.run_extraction_pass` —
  this is the only place outside `apps/explorer` that calls the analyzer trigger.
- The lifespan in `app_factory.py` calls `get_memory_manager()` to warm the
  connection pool before the first request, and starts/stops `RuminationScheduler`.
