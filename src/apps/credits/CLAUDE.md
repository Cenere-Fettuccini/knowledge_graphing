# App: Credits

Provides detailed LLM quota and rate-limit visibility. Admin-level app that
intentionally has deeper access to router internals than other apps — it exists
specifically to expose and manage model limits.

## Files
| File | Role |
|------|------|
| `api.py` | FastAPI router — thin HTTP layer |
| `services.py` | Aggregates live quota usage, imports limits, detects mismatches |
| `app.py` | `AppDefinition` registration (metadata only) |

---

## Called By
| Caller | What it uses |
|--------|-------------|
| `src.platform.app_factory` | `get_credits_app()` — imports factory to register the app |
| HTTP clients (browser UI) | `GET /apps/credits/`, `POST /apps/credits/limits/import`, `GET /apps/credits/mismatches` |

---

## Calls Into
| Dependency | What is called |
|------------|---------------|
| `src.core.router` | `llm_router` — intentional; credits is the router admin app |
| `src.core.limits_store` | `load_limits()`, `import_from_paste()`, `load_mismatch_log()` |
| `src.platform.registry` | `AppDefinition` (in `app.py`) |

---

## Allowed Imports
```python
from src.core.router import llm_router          # intentional — credits is a router admin app
from src.core.limits_store import import_from_paste, load_limits, load_mismatch_log
```

---

## Public Methods / Attributes Used

### `llm_router` (`src.core.router`)
```python
llm_router.models -> list[ModelSpec]
# ModelSpec fields: model_id, provider, project_scope, capabilities,
#                   rpm_limit, rpd_limit, tpm_limit

llm_router.limiter.get_headroom(model_id, project_scope, rpm_limit, rpd_limit, tpm_limit) -> float
# Returns 0.0–1.0 headroom (1.0 = fully available)

llm_router.limiter._get_state(model_id, project_scope)
# Returns internal RateLimitState with: used_rpm, used_rpd, used_tpm

llm_router.reload_limits() -> None
# Reloads limits from limits_override.json and rebuilds model specs
```

### `limits_store` (`src.core.limits_store`)
```python
load_limits() -> dict                          # {short_model_id: {rpm_limit, rpd_limit, tpm_limit}}
import_from_paste(raw_text: str) -> tuple[dict, list]  # (updated_limits, matched_ids)
load_mismatch_log() -> list[dict]              # recent 429/mismatch events
```

---

## Note on Deep Router Access
Credits is the **one app** that legitimately accesses router internals (limiter
state, model list). This is by design — it is the quota management console.
All other apps must use `agent_service.aquota_status()` for lightweight headroom data.

---

## What NOT to Do
- Do not import from other apps (`src.apps.chat`, `src.apps.explorer`, etc.)
- Do not access `get_memory_manager()` — credits has no memory concerns
- Do not add general-purpose logic here — keep this to quota/limits admin only
