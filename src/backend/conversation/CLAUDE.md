# aimanager.conversation

Single orchestration layer that runs a conversational turn end-to-end.
Sits between the entry points (HTTP routes, Telegram bot) and the agent
runtime. Centralises memory bookends, history fetch, and response
packaging so that every channel uses the same flow.

**Status:** stable. Protocol governs the API contract.

## Installation

Part of the `aimanager` distribution. Importable as:

```python
from src.backend.conversation import Conversation, TurnResult, get_conversation
```

## Public API quick reference

`__init__.py` exports exactly three names:

| Name | Kind | Description |
|---|---|---|
| `Conversation` | `typing.Protocol` | Structural type for the singleton. |
| `TurnResult` | `@dataclass(frozen=True)` | Result of one turn. |
| `get_conversation` | function | Returns the shared instance; constructs it on first call. |

### `Conversation` methods at a glance

| Method | Returns | Purpose |
|---|---|---|
| `handle_turn(session_id, text, *, parent_turn_id=None, metadata=None)` | `TurnResult` | Run one conversational turn end-to-end. |

One method. Every entry point — HTTP chat route, Telegram bot — calls
this and gets back a result.

## Quick start

```python
from src.backend.conversation import get_conversation

conversation = get_conversation()
result = await conversation.handle_turn(session_id="s1", text="hello")
print(result.reply)
```

## Full signatures

```python
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class TurnResult:
    reply: str
    session_id: str
    user_turn_id: str          # id of the user message just appended
    assistant_turn_id: str     # id of the assistant reply just appended
    reply_timestamp: str       # ISO 8601
    metadata: dict = field(default_factory=dict)


@runtime_checkable
class Conversation(Protocol):
    async def handle_turn(
        self,
        session_id: str,
        text: str,
        *,
        parent_turn_id: str | None = None,
        metadata: dict | None = None,
    ) -> TurnResult:
        """Run one conversational turn end-to-end.

        Sequence:
            1. Append the user turn to memory (under `parent_turn_id` if given,
               else under the session's active leaf).
            2. Read recent turns from memory (oldest-first).
            3. Call the agent with the user text and the history.
            4. Append the agent's reply to memory.
            5. Return a TurnResult describing both turns and the reply.

        `parent_turn_id` lets callers branch — passing the parent of an
        existing turn produces a sibling, which is the underlying
        operation for "edit" and "regenerate" UI actions.
        """


def get_conversation() -> Conversation:
    """Return the shared Conversation. Constructs the implementation on first call."""
```

## Lifecycle of one call

```
caller invokes handle_turn(session_id, text)
  ↓
memory.append(session_id, "user", text, parent_id=parent_turn_id)
  ↓ user_turn_id
memory.recent_turns(session_id, limit=HISTORY_TURNS)
  ↓ history (newest-first; orchestrator reverses to oldest-first)
agent.arun(AgentRunRequest(session_id, text, history))
  ↓ AgentRunResult(reply, …)
memory.append(session_id, "assistant", result.reply)
  ↓ assistant_turn_id
return TurnResult(reply, session_id, user_turn_id, assistant_turn_id, …)
```

If any step fails, the orchestrator logs at `ERROR` via `src.log` and
raises a typed exception (`ConversationError`). Partial writes are
acceptable — the user turn may exist without an assistant reply if the
agent crashed. Callers may retry; idempotency is not guaranteed by this
layer.

## Why this layer exists

Both the HTTP chat route (`apps/chat/api.py`) and the Telegram bot
(`bot/_handlers.py`) need the same sequence of operations around the
agent. Without this layer, each would duplicate:

- The decision of when to write the user turn (before the agent runs).
- The history-window size.
- The conversion from `recent_turns` order to agent-friendly order.
- The decision of when to write the assistant turn (after the agent
  returns).
- The shape of the response payload.

Centralising means **identical behaviour across channels** and a single
place to change the flow when the policy evolves (e.g. switching to a
RAG-driven history selection, or streaming).

## What this layer does NOT do

- Assemble the LLM prompt. The agent does that.
- Call LLMs directly.
- Parse HTTP or Telegram payloads — that's the entry layer.
- Manage sessions (create, list, delete) — that's `memory`.
- Provide streaming (planned post-MVP; will be a sibling method `astream_turn`).

## Dependencies

- `src.memory.MemoryManager` — for persistence and history reads
- `src.agent.AgentService` — to run the agent

Both injected at construction. The factory wires them:

```python
def get_conversation() -> Conversation:
    from ._service import _Conversation
    return _Conversation.get()
```

The concrete `_Conversation` calls `get_memory_manager()` and
`get_agent_service()` once when constructed. No module-level state.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `HISTORY_TURNS` | `20` | Number of recent turns passed to the agent. |
| `CONVERSATION_FAIL_LOUDLY` | `true` | If `false`, swallow agent errors and return a degraded reply ("I'm having trouble — please try again"). If `true`, raise. |

## Usage patterns

**FastAPI route — dependency injection:**

```python
from fastapi import Depends
from src.backend.conversation import Conversation, get_conversation

@router.post("/message")
async def handler(
    body: dict,
    conversation: Conversation = Depends(get_conversation),
):
    result = await conversation.handle_turn(
        session_id=body["session_id"],
        text=body["text"],
        parent_turn_id=body.get("parent_turn_id"),
    )
    return {
        "reply": result.reply,
        "user_turn_id": result.user_turn_id,
        "assistant_turn_id": result.assistant_turn_id,
        "timestamp": result.reply_timestamp,
    }
```

**Telegram bot handler:**

```python
async def handle_message(update, context):
    session_id = sessions.get(update.effective_user.id)
    result = await conversation.handle_turn(
        session_id=session_id,
        text=update.message.text,
    )
    await update.message.reply_text(result.reply)
```

Same call, different shells around it.

## Errors

The orchestrator defines one public exception:

```python
class ConversationError(Exception):
    """Raised when a turn cannot complete.

    Attributes:
        session_id: The session that failed.
        user_turn_id: The user turn that was appended before failure (may be None).
        cause: The underlying exception.
    """
```

Callers should catch `ConversationError` if they want to render an
error to the user. Underlying exceptions (`MemoryError`, agent errors,
etc.) are wrapped — never propagated raw.

## Stability and versioning

The `Conversation` Protocol, `TurnResult`, and `ConversationError` are
the public contract.

- **Non-breaking:** new methods on `Conversation`, new optional fields on `TurnResult`, new optional kwargs on `handle_turn`.
- **Breaking (major version):** removing methods or fields, renaming, changing existing signatures.

## Internals

Implementation modules are private and may change without notice:

```
conversation/
  __init__.py        Protocol + dataclass + factory (public)
  _service.py        concrete `_Conversation` class
  py.typed           PEP 561 marker
```

The concrete class enforces singleton construction via a private
classmethod (`_Conversation.get()`), invoked only by
`get_conversation()`.

## Anti-patterns

- Assembling LLM prompts here (belongs in the agent).
- Skipping the memory bookends — the contract is "every turn is persisted."
- Reaching into the agent or memory internals.
- Capturing the instance at module load.
- Importing `_service` directly.
