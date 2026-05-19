# aimanager.bot

Telegram bot entry point. Runs as a separate process from the FastAPI
server (`python -m src.bot`), using the same `MemoryManager` and
`AgentService` instances.

**Status:** planned, not yet implemented. The folder shape and public
API below are reserved.

## Folder shape

```
bot/
  __init__.py          Public export — only the bot class
  __main__.py          `python -m src.bot` entry point
  _bot.py              Concrete _TelegramBot implementation
  _handlers.py         Per-command handlers
  _session_store.py    Per-user session tracking (JSON on disk)
  messages.py          User-facing string constants (importable)
```

## Public API

`__init__.py` exports exactly one name:

| Name | Kind | Description |
|---|---|---|
| `TelegramBot` | `typing.Protocol` | Structural type for the bot. |
| `run` | function | Constructs the bot and starts its polling loop. Blocks. |

### `TelegramBot` Protocol

```python
@runtime_checkable
class TelegramBot(Protocol):
    def run(self) -> None:
        """Start the Telegram polling loop. Blocks until interrupted."""

    async def stop(self) -> None:
        """Shut down the polling loop cleanly."""
```

### `run`

```python
def run() -> None:
    """Construct and run the Telegram bot. Blocks. Invoked by `python -m src.bot`."""
```

## Configuration

| Variable | Default | Description |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | _(required)_ | Bot token from BotFather. |
| `TELEGRAM_ALLOWED_USER_IDS` | _(required)_ | Comma-separated list of allowed Telegram user ids. |
| `BOT_SESSION_STORE_PATH` | `./data/bot_sessions.json` | Per-user active session file. |

## Commands

| Command | Description |
|---|---|
| `/start` | Welcome message and current session id. |
| `/help` | Command reference. |
| `/new` | Start a new conversation session. |
| `/history` | Return the most recent turns. |
| `/status` | Report agent and memory health. |

Plain text messages are routed to the chat agent via
`AgentService.arun()` using the same path as the `apps.chat` HTTP route.

## Flow

```
1. Telegram → bot polling loop receives Update
2. _handlers._handle_message:
     - resolve user_id → session_id via _session_store
     - result = await conversation.handle_turn(session_id, text)
     - update.message.reply_text(result.reply)
```

The bot uses the **same `Conversation` orchestrator** as the HTTP chat
app. The bot must not call `AgentService` or `MemoryManager` directly
for the turn flow — that bypass is the duplication this architecture
exists to prevent. Session lookups (`list_sessions`, `delete_session`)
for slash-commands like `/history` may still call `MemoryManager`
directly since they are not turn operations.

## Stability and versioning

The `TelegramBot` Protocol and the `run` entry point are the contract.

- **Non-breaking:** adding new commands, adding new env vars with defaults, adding optional Protocol methods.
- **Breaking (major version):** removing commands, renaming Protocol methods, changing the env var contract.

## Internals

`_bot.py`, `_handlers.py`, `_session_store.py`, and any module starting
with `_` are not part of the public API and may change without notice.

## Anti-patterns

- Direct construction of `_TelegramBot` from outside the package.
- Importing private modules (`_bot`, `_handlers`, `_session_store`).
- Bypassing `AgentService.arun()` to call agent internals directly.
- Writing turns to anywhere other than `MemoryManager.record_*_message`.
- Module-level Telegram client instantiation (build inside `_TelegramBot.__init__`).
