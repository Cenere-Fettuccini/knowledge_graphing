# Bot — Telegram Interface

Provides the Telegram bot entry point. Runs independently of the FastAPI server
via `run_bot.py`. Uses the same `Agent` and `MemoryManager` singletons as the
web platform.

## Files
| File | Role |
|------|------|
| `telegram_bot.py` | `TelegramBot` class — handlers, session tracking, command dispatch |
| `messages.py` | All user-facing string constants (welcome text, help, errors, etc.) |
| `proactive.py` | `ProactiveBot` — outbound Telegram messages for digests and reconciliation flows |

---

## Called By
| Caller | What it uses |
|--------|-------------|
| `run_bot.py` | `TelegramBot` — instantiates and calls `.run()` |
| `src.rumination.engine` | `ProactiveBot` — instantiated in `RuminationScheduler` for belief digests |

---

## Calls Into
| Dependency | What is imported |
|------------|-----------------|
| `src.core.agent` | `Agent`, `BaseAgent` — bot creates its own `Agent` instance directly (not via `AgentService`) |
| `src.core.config` | `settings` — token, allowed user IDs |
| `src.core.logging_config` | `setup_logging()` |
| `src.memory.manager` | `get_memory_manager()` — `ProactiveBot` accesses memory for digests |
| `src.agent_platform.public.agent_service` | `get_agent_service()` — `ProactiveBot` uses `AgentService` |
| `src.agent_platform.analyzers.refinement_extraction` | `parse_reconciliation_reply()` — CT8 quick-mode reconciliation |
| `telegram` (python-telegram-bot) | All handler and application classes |

---

## Key Classes

### `TelegramBot` (`telegram_bot.py`)
```python
class TelegramBot:
    def run() -> None
    # Registers handlers then calls application.run_polling()
```

**Commands handled:** `/start`, `/help`, `/new` (new session), `/history`,
`/pin <node_id>` (anchor session to a graph node), `/swap` (switch model),
`/status`.

**Session tracking:** `SessionStore` (JSON-persisted, per-user). Stores the
active `session_id` and pinned `node_id` per Telegram `user_id`.

### `ProactiveBot` (`proactive.py`)
```python
class ProactiveBot:
    async def send_belief_digest(chat_id: str) -> None
    async def handle_refinement_reply(chat_id: str, reply_text: str) -> None
```

Called from `RuminationScheduler.deep_pass_tick()` to push outbound digests.
Also called from the CT8 reconciliation flow when a contradiction is resolved.

---

## Coupling Notes
- `TelegramBot` calls `src.core.agent.Agent` **directly** (not `AgentService`)
  because the bot predates the public gateway. This is the one non-app caller
  of `Agent`. If you refactor the bot, migrate it to `AgentService.arun()`.
- `ProactiveBot` is the only non-route caller of `AgentService` — it uses
  `get_agent_service()` rather than `Depends()`.
- `messages.py` has no dependencies — it is a pure constant module. Add all
  user-visible bot strings here, never inline them in handler code.
