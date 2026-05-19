# aimanager.backend.platform

FastAPI assembly. Builds the application, registers apps, and mounts
their routers and static directories. Does not change when apps are
added or removed.

**Status:** stable.

## Installation

Importable as:

```python
from src.backend.platform import create_platform_app, AppDefinition, AppRegistry
```

## Public API

| Name | Kind | Description |
|---|---|---|
| `create_platform_app` | function | Builds and returns the configured FastAPI app. |
| `AppDefinition` | `@dataclass(frozen=True)` | App metadata returned by each `apps/<name>` factory. |
| `AppRegistry` | `@dataclass` | Mutable collection of registered apps. |

### `create_platform_app`

```python
def create_platform_app() -> FastAPI:
    """Build the configured FastAPI app.

    Iterates `_build_registry()`, mounts each app's router (if any) and
    static directory (if any), and installs lifespan hooks.
    """
```

### `AppDefinition`

```python
@dataclass(frozen=True)
class AppDefinition:
    id: str                                   # e.g. "chat"
    name: str                                 # human-readable
    route_prefix: str                         # e.g. "/apps/chat"
    api_router: APIRouter | None = None
    api_prefix: str | None = None
    static_dir: Path | None = None
    description: str = ""
    icon: str = ""
```

### `AppRegistry`

```python
@dataclass
class AppRegistry:
    def register(self, app_def: AppDefinition) -> None: ...
    def list_apps(self) -> list[AppDefinition]: ...
    def iter_active_apps(self) -> Iterable[AppDefinition]: ...
```

## Boot sequence

```
1. src/main.py imports create_platform_app
2. create_platform_app() calls _build_registry() (private)
3. _build_registry() imports each apps.<name>.get_<name>_app() and registers the AppDefinition
4. The factory mounts each app's APIRouter at its api_prefix
5. The factory mounts each app's static_dir at its route_prefix
6. The factory installs the lifespan hook
7. The FastAPI app is returned; uvicorn serves it
```

## Usage patterns

**Entry point (`src/main.py`):**

```python
from src.backend.platform import create_platform_app

app = create_platform_app()

# uvicorn src.main:app
```

**Apps consuming `AppDefinition`:**

```python
from pathlib import Path
from src.backend.platform import AppDefinition
from src.apps.chat.api import router

def get_chat_app() -> AppDefinition:
    return AppDefinition(
        id="chat",
        name="Chat",
        route_prefix="/apps/chat",
        api_router=router,
        api_prefix="/apps/chat",
        static_dir=Path(__file__).parent / "static",
        description="Conversational interface",
    )
```

## Configuration

| Variable | Default | Description |
|---|---|---|
| `CORS_ORIGINS` | `*` | Comma-separated list of allowed CORS origins. |
| `STATIC_CACHE_SECONDS` | `0` | Cache-Control max-age for static assets. |

## Stability and versioning

`create_platform_app`, `AppDefinition`, and `AppRegistry` are the public
contract.

- **Non-breaking:** adding optional fields to `AppDefinition` with defaults; adding new methods on `AppRegistry`; new optional kwargs on `create_platform_app`.
- **Breaking (major version):** removing fields, making optional fields required, renaming methods, changing return shapes.

## Internals

```
backend/platform/
  __init__.py          Public factory + dataclasses
  _factory.py          create_platform_app implementation
  _registry.py         AppRegistry + AppDefinition (re-exported)
  _lifespan.py         FastAPI lifespan hook
  py.typed
```

`_build_registry()` is private — the only place that imports every
`apps/<name>` factory. Adding a new app means editing this function
once.

## Anti-patterns

- Importing `_build_registry` or `_lifespan` from outside the package.
- Instantiating `AppRegistry` outside `backend.platform`.
- Adding app-specific logic to the factory; app behaviour lives in `apps/<name>`.
- Importing from `apps/<name>.api` or `.services` directly (use `get_<name>_app()`).
