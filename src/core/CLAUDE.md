# Core — Internal Module (Do Not Import From Apps)

Owns LLM model routing, configuration, rate limiting, and logging setup.
**Apps must not import from `src.core.*` directly** (except `src.core.config.settings`,
and `src.core.router` which is reserved for the `credits` admin app only).

## Files
| File | Role |
|------|------|
| `config.py` | `Settings` singleton loaded from `.env` via pydantic-settings |
| `router.py` | `LLMRouter` + `ModelSpec` — selects best model/key for a task |
| `agent.py` | `Agent` class — orchestrates prompt assembly, memory, tools, LLM calls |
| `context.py` | `ContextManager` — assembles conversation context for each turn |
| `limiter.py` | `InternalRateLimiter` — in-memory RPM/RPD/TPM tracking |
| `limits_store.py` | Persistence for manual limit overrides (`limits_override.json`) |
| `tools.py` | Tool registry wiring for the agent |
| `logging_config.py` | Logging setup |
| `prompts.py` | System prompt templates |

## Public Surface (for the credits app and internal use)

### `settings` (src.core.config)
```python
settings.google_api_keys: str          # comma-separated raw keys
settings.api_keys: list[str]           # parsed list
settings.google_key_configs: list[dict] # [{api_key, project_scope}, ...]
settings.allowed_user_ids: set[str]
settings.llm_model: str
settings.neo4j_uri / neo4j_user / neo4j_password: str
settings.chroma_persist_dir / chroma_collection: str
settings.context_window_turns: int
settings.rag_top_k: int
```

### `llm_router` (src.core.router) — credits app only
```python
llm_router.models: list[ModelSpec]
llm_router.get_best_model(task_type: str) -> ModelSpec
llm_router.track_usage(model_id, project_scope, tokens) -> None
llm_router.track_429(model_id, project_scope) -> None
llm_router.reload_limits() -> None
llm_router.limiter.get_headroom(model_id, project_scope, rpm_limit, rpd_limit, tpm_limit) -> float
```

## Who May Import From Here
- `src.agent_platform.*` — agent internals
- `src.memory.*` — storage backends
- `src.apps.credits` — credits admin app (llm_router only)
- Nobody else — apps use `get_agent_service()` and `get_memory_manager()` instead
