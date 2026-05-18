# Rumination — Background Belief Processing

Runs background ticks while the FastAPI server is live. Two cadences:
- **Deep pass** (`deep_pass_tick_seconds`) — triggers `DeepPass` which analyzes
  active beliefs and may push a digest to the bot.
- **Rabbit hole** (`rabbit_hole_tick_seconds`) — reserved for future deep-dive
  exploration of belief clusters.

## Files
| File | Role |
|------|------|
| `engine.py` | `RuminationScheduler` — owns both tick loops, started/stopped in lifespan |
| `deep_pass.py` | `DeepPass` — analyzes active beliefs using `AgentService` |

---

## Called By
| Caller | What it uses |
|--------|-------------|
| `src.platform.app_factory` | `RuminationScheduler` — instantiated in lifespan, `.start()` / `.stop()` called |

---

## Calls Into
| Dependency | What is imported |
|------------|-----------------|
| `src.memory.manager` | `MemoryManager`, `get_memory_manager()` |
| `src.agent_platform.public.agent_service` | `get_agent_service()`, `AgentService` |
| `src.bot.proactive` | `ProactiveBot` — sends belief digests to Telegram |
| `src.core.config` | `settings.deep_pass_tick_seconds`, `settings.rabbit_hole_tick_seconds`, `settings.rumination_enabled` |

---

## Data Flow & Lifecycle

**Phases**: `boot` · `background` · `shutdown`

**State**: `lifespan-scoped`
- `RuminationScheduler` instance built in the FastAPI lifespan. Owns 2 long-running `asyncio` tasks (`_deep_pass_loop`, `_rabbit_hole_loop`) and one `ProactiveBot`.
- Tasks cancelled on lifespan shutdown.

**Inbound**

| From | Trigger | Payload | Mode |
|------|---------|---------|------|
| `src.platform.app_factory` | lifespan startup | `RuminationScheduler(memory).start()` | `async` |
| `src.platform.app_factory` | lifespan shutdown | `.stop()` cancels tasks | `async` |
| internal asyncio sleep | each tick interval | wakes the loop body | `scheduled` |

**Outbound**

| To | Trigger | Payload | Mode |
|----|---------|---------|------|
| `src.memory.manager` | each deep-pass tick | `list_active_beliefs` etc. | `sync` |
| `src.agent_platform.public.agent_service` | each tick | `service.arun(synth prompt)` → Gemini | `async` |
| `src.bot.proactive.ProactiveBot.send_belief_digest` | tick produces digest | digest text | `async` |
| LM Studio (only via `deep_pass`) | direct `LMStudioClient.chat_completion` | tick body | `sync inside async` |

**Diagnostic notes**
- Two ticks run as **independent asyncio tasks** — they do not contend with each other. They DO share Gemini quota with chat traffic via `LLMRouter`.
- `settings.rumination_enabled=False` makes both loops no-op.
- Tick overruns don't overlap (each loop awaits its own body), but they do skew the next tick's start time.

---

## Public API

### `engine.py`
```python
class RuminationScheduler:
    def __init__(
        memory: MemoryManager,
        deep_pass_tick_seconds: int,
        rabbit_hole_tick_seconds: int,
    )
    def start() -> None   # Launches background asyncio tasks
    def stop() -> None    # Cancels all tasks; called on server shutdown
```

### `deep_pass.py`
```python
class DeepPass:
    async def analyze(memory: MemoryManager, service: AgentService) -> dict:
        """Read active beliefs, pass them to the agent for synthesis,
        return a digest dict. Called each deep-pass tick."""
```

---

## Coupling Notes
- Rumination is **purely internal** — nothing outside `platform/app_factory.py`
  should import from here.
- `RuminationScheduler` respects `settings.rumination_enabled = False` — set
  this in `.env` to disable background ticks during development.
- `ProactiveBot` is instantiated inside the scheduler; the scheduler owns its
  lifecycle. The bot's `run_bot.py` process does **not** run rumination — it
  only runs the Telegram polling loop.
- If you add a new tick cadence, add its `_tick_seconds` setting to
  `src/core/config.py` and a new loop method on `RuminationScheduler`.
