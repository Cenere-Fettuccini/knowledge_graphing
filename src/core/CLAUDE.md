# Core — Internal Infrastructure (Do Not Import From Apps)

Owns LLM model routing, configuration, rate limiting, prompt assembly, and
logging setup. **Apps must not import from `src.core.*` directly** (except
`src.core.config.settings`, and `src.core.router` which is reserved for the
`credits` admin app only).

## Files
| File | Role |
|------|------|
| `config.py` | `Settings` singleton loaded from `.env` via pydantic-settings |
| `router.py` | `LLMRouter` + `ModelSpec` — selects best model/key for a task |
| `agent.py` | `Agent` class — orchestrates prompt assembly, memory, tools, LLM calls |
| `context.py` | `ContextManager` — assembles conversation context for each turn |
| `limiter.py` | `InternalRateLimiter` — in-memory RPM/RPD/TPM tracking |
| `limits_store.py` | Persistence for manual limit overrides (`limits_override.json`) |
| `logging_config.py` | `setup_logging()` — configures structlog/stdlib logging |
| `prompts.py` | System prompt templates (`SYSTEM_PROMPT`, `CONTEXT_BLOCK`, etc.) |

---

## Called By
| Caller | What it uses |
|--------|-------------|
| `src.agent_platform.public.agent_service` | `Agent`, `BaseAgent` (via `agent.py`); `llm_router` (via `router.py`) |
| `src.agent_platform.tools.*` | `get_memory_manager()` indirectly; `settings` |
| `src.agent_platform.analyzers.*` | `settings` |
| `src.memory.manager` | `settings` |
| `src.memory.stores.*` | `settings` |
| `src.bot.telegram_bot` | `Agent`, `BaseAgent`, `settings`, `setup_logging()` |
| `src.platform.app_factory` | `settings`, `setup_logging()` |
| `src.rumination.engine` | `settings` |
| `src.ingestion.*` | `settings` |
| `src.apps.credits` | `llm_router`, `limits_store` (intentional — credits is the router admin app) |

---

## Calls Into
| Dependency | What is called |
|------------|---------------|
| `pydantic_ai` | `Agent`, `RunContext`, usage tracking |
| `google.generativeai` | LLM API calls (via `router.py` model selection) |
| `src.memory.manager` | `MemoryManager`, `get_memory_manager()` (from `agent.py`) |
| `src.core.context` | `ContextManager` (from `agent.py`) |
| `src.core.router` | `llm_router`, `ModelSpec` (from `agent.py`) |
| `src.agent_platform.tools.registry` | `tools` list (from `agent.py`) |
| `src.core.prompts` | Prompt templates (from `agent.py`) |
| `src.core.limiter` | `InternalRateLimiter` (from `router.py`) |
| `src.core.limits_store` | Limit persistence (from `router.py`) |

---

## Public Surface

### `settings` (`src.core.config`)
```python
settings.google_api_keys: str           # comma-separated raw keys
settings.api_keys: list[str]            # parsed list
settings.google_key_configs: list[dict] # [{api_key, project_scope}, ...]
settings.allowed_user_ids: set[str]
settings.llm_model: str
settings.neo4j_uri / neo4j_user / neo4j_password: str
settings.chroma_persist_dir / chroma_collection: str
settings.context_window_turns: int
settings.rag_top_k: int
settings.graph_ingest_threshold: int
settings.cloud_belief_threshold: int
settings.rumination_enabled: bool
settings.deep_pass_tick_seconds: int
settings.rabbit_hole_tick_seconds: int
settings.lm_studio_base_url: str
settings.lm_studio_model: str
settings.graph_ingest_secret: str
```

### `Agent` / `BaseAgent` (`src.core.agent`)
```python
class BaseAgent(ABC):
    @abstractmethod
    def process_message(user_id, text, session_id) -> str
    @abstractmethod
    async def aprocess_message(user_id, text, session_id) -> str
    @abstractmethod
    def status(force=False) -> dict
    @abstractmethod
    async def astatus(force=False) -> dict
    @abstractmethod
    def get_history(session_id, limit=20) -> list[dict]
    @abstractmethod
    def clear_session(session_id) -> None

class Agent(BaseAgent):
    def __init__(memory: MemoryManager | None = None)
    # Implements all abstract methods above
```

`Agent` is consumed by `AgentService` (public gateway) and `TelegramBot`.
New consumers should use `AgentService` instead of importing `Agent` directly.

### `llm_router` (`src.core.router`) — credits app only
```python
llm_router.models: list[ModelSpec]
llm_router.get_best_model(task_type: str) -> ModelSpec
llm_router.track_usage(model_id, project_scope, tokens) -> None
llm_router.track_429(model_id, project_scope) -> None
llm_router.reload_limits() -> None
llm_router.limiter.get_headroom(model_id, project_scope, rpm_limit, rpd_limit, tpm_limit) -> float
llm_router.limiter._get_state(model_id, project_scope) -> RateLimitState
```

### `setup_logging()` (`src.core.logging_config`)
```python
def setup_logging() -> None
# Call once at startup — invoked by app_factory.py and run_bot.py
```

---

## Coupling Notes
- `agent.py` is the highest-coupling module in core: it imports `ContextManager`,
  `llm_router`, `MemoryManager`, `tools`, and `prompts`. Changes to any of those
  propagate here.
- The `credits` app is the only app permitted to import `llm_router` directly.
  All other apps use `AgentService.aquota_status()` for headroom data.
- `config.py` is effectively a global — nearly every module imports `settings`.
  Do not put mutable state here; it is read-only after startup.
