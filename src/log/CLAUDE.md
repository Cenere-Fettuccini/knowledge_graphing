# aimanager.log

Central logger for the AIManager platform. All code emits log records
through this module; the user controls verbosity by setting one
environment variable to one of three modes.

**Status:** stable. Public API is the contract.

## Installation

Part of the `aimanager` distribution. Importable as:

```python
from src.log import get_logger, in_development, done, setup_logging
```

## Quick start

```python
from src.log import setup_logging, get_logger, in_development

setup_logging()                   # called once at process start (reads LOG_MODE env var)

logger = get_logger(__name__)

@in_development
async def my_new_function(...):
    logger.info("processing", extra={"session_id": session_id})
```

## Public API quick reference

| Name | Kind | Description |
|---|---|---|
| `setup_logging` | function | Configure the root logger; called once at process start. |
| `get_logger` | function | Return a module-scoped logger. Replaces `logging.getLogger(__name__)`. |
| `in_development` | decorator | Mark a function as actively under development — verbose in `active_dev` mode. |
| `done` | decorator | Mark a function as complete — only errors emit in `active_dev` mode. |
| `LogMode` | enum | The three modes (`dev`, `prod`, `active_dev`). |

That is the entire public surface.

## Modes

| Mode | What emits |
|---|---|
| `dev` | Every log line at every level (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`). |
| `prod` | Only `ERROR` and `CRITICAL`, from anywhere. |
| `active_dev` | All `ERROR`/`CRITICAL` from anywhere, plus all levels from functions marked `@in_development`. Functions marked `@done` emit only errors. |

Mode is set at process start via `LOG_MODE` env var. Default: `dev` in
non-production environments, `prod` otherwise.

## Public API

### `setup_logging`

```python
def setup_logging(mode: LogMode | str | None = None) -> None:
    """Configure the root logger.

    Reads `LOG_MODE` env var if `mode` is None. Idempotent — calling twice
    in the same process re-applies the configuration.

    Must be called once before any `get_logger()` invocation; if not, the
    first `get_logger()` call invokes it with defaults.
    """
```

### `get_logger`

```python
def get_logger(name: str) -> logging.Logger:
    """Return a logger bound to `name` (typically `__name__`).

    The returned logger uses the central formatter and the active mode's
    level filter. Do not call `logging.getLogger(...)` directly anywhere
    in the codebase.
    """
```

### `in_development` decorator

```python
def in_development(fn: Callable) -> Callable:
    """Mark a function/method/async function as actively under development.

    In `active_dev` mode, log lines emitted from within this function (or
    from `get_logger(...).log(...)` calls whose call-stack passes through
    this function) bypass the error-only filter.

    Decorator may be stacked on sync, async, or class methods.
    """
```

### `done` decorator

```python
def done(fn: Callable) -> Callable:
    """Mark a function as complete.

    In `active_dev` mode, the function's logs are suppressed except for
    `ERROR` / `CRITICAL`. Equivalent to "this function is stable; don't
    drown me in its noise while I'm working on something else."

    Has no effect in `dev` or `prod` mode.
    """
```

### `LogMode` enum

```python
class LogMode(str, Enum):
    DEV = "dev"
    PROD = "prod"
    ACTIVE_DEV = "active_dev"
```

## How the decorators interact with the logger

The decorators don't wrap log calls — they register the decorated
function's qualified name (`module.ClassName.method` or `module.func`) in
a process-wide registry, then return the function unmodified.

A custom `logging.Filter` consults the registry at log-emit time:

1. Read the `LogRecord`'s `module` and `funcName` (and inspect the call
   stack one frame up to recover `__qualname__` when needed for methods).
2. Look up the registry entry for that qualified name.
3. Decide whether to emit based on (mode, registry status, log level).

This means a single function's status can be flipped from `@done` to
`@in_development` (or removed) without touching the call sites that use
its logs.

## Log format

Structured key=value, single line per event:

```
2026-05-18T16:30:00Z level=INFO logger=src.memory._manager func=record_user_message session_id=abc msg="appended turn" turn_id=t-def
```

Fields always present: `timestamp`, `level`, `logger`, `func`, `msg`.
Extra fields come from `logger.info("...", extra={"session_id": ...})`.

JSON output is also supported; toggle with `LOG_FORMAT=json` env var.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `LOG_MODE` | `dev` | One of `dev`, `prod`, `active_dev`. |
| `LOG_FORMAT` | `text` | One of `text`, `json`. |
| `LOG_FILE` | _(unset)_ | If set, also write logs to this file (in addition to stderr). |

## Usage patterns

**Module-level logger:**

```python
from src.log import get_logger

logger = get_logger(__name__)   # module-level is fine — the logger object is stateless

def some_function():
    logger.info("doing work", extra={"key": "value"})
```

**Decorating an in-development function:**

```python
from src.log import in_development, get_logger

logger = get_logger(__name__)

@in_development
async def newly_built_thing(x):
    logger.debug("entering", extra={"x": x})
    ...
    logger.info("done", extra={"result": result})
```

When `LOG_MODE=active_dev`, the `debug` and `info` lines emit. Everything
else in the system stays quiet (except errors). When the function
stabilises, swap `@in_development` for `@done` (or remove the decorator).

## Stability and versioning

The five public names above are the contract.

- **Non-breaking:** adding new env vars with defaults; adding new log
  formats; adding new decorator names.
- **Breaking (major version):** removing `setup_logging`, `get_logger`,
  the decorators, or the enum; changing the env var contract.

## Internals

```
log/
  __init__.py          public exports
  _setup.py            setup_logging + handler/formatter config
  _registry.py         function-status registry + decorators
  _filter.py           the custom logging.Filter that consults the registry
  py.typed
```

Underscore-prefixed modules are not part of the public API.

## Anti-patterns

- `print(...)` statements in production code.
- `logging.getLogger(...)` calls outside this module. Always use `get_logger`.
- `logging.basicConfig(...)` outside `setup_logging`.
- Capturing log records in module-level state.
- Bare `logger.error("failed")` with no context — always include the
  relevant ids and inputs.
- Catching an exception and logging nothing.
