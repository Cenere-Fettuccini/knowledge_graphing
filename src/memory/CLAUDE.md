# aimanager.memory

Persistent conversation memory for the AIManager platform. A single
in-process instance backed by an append-only JSONL log per session,
exposed through the `MemoryManager` Protocol. Conversations are stored
as a tree — every turn has a parent, branching is first-class.

**Status:** stable. Public Protocol governs the API contract.

## Installation

Part of the `aimanager` distribution. The package is importable as:

```python
from src.memory import MemoryManager, get_memory_manager
```

## Public API quick reference

The `__init__.py` exports exactly two names:

| Name | Kind | Description |
|---|---|---|
| `MemoryManager` | `typing.Protocol` | Structural type for the singleton. Not a class to instantiate. |
| `get_memory_manager` | function | Returns the shared instance; constructs it on first call. |

### `MemoryManager` methods at a glance

**Turn-level (within a session):**

| Method | Returns | Purpose |
|---|---|---|
| `append(session_id, role, text, *, parent_id=None, metadata=None)` | `str` (new turn id) | Write a turn. The new turn becomes the active leaf. |
| `recent_turns(session_id, *, leaf_id=None, limit=20)` | `list[dict]` | Walk back from a leaf, newest-first. |
| `list_branches(session_id)` | `list[dict]` | All distinct leaves in the session. |
| `set_active(session_id, leaf_id)` | `None` | Change the active leaf. |
| `active_leaf(session_id)` | `str \| None` | Current active leaf id, or `None` for an empty session. |

**Session-level:**

| Method | Returns | Purpose |
|---|---|---|
| `list_sessions()` | `list[dict]` | All known sessions (`{session_id, turn_count, last_active}`). |
| `delete_session(session_id)` | `None` | Remove a session's storage files. |

**Health:**

| Method | Returns | Purpose |
|---|---|---|
| `status()` | `dict` | Health snapshot. |

Eight methods. Each does one thing.

## Mental model

Each session is a tree of turns rooted at the first message. Every turn
has a parent (or `None` for the root). Two turns sharing a parent are
**siblings** — they represent alternative continuations from the same
point. A leaf is a turn with no children; each distinct leaf is one
**branch** of the conversation.

At any moment the session has exactly one **active leaf**. New appends
attach beneath it by default. Switching branches means pointing the
active leaf elsewhere.

This is the same model ChatGPT uses: editing a past message creates a
sibling at that point; regenerating an assistant reply creates a
sibling assistant turn; the branch arrows in the UI map directly to
`set_active`.

## Quick start

```python
from src.memory import get_memory_manager

memory = get_memory_manager()

# Linear conversation
memory.append("s1", "user", "hello")
memory.append("s1", "assistant", "hi there")
memory.append("s1", "user", "what's the weather?")
memory.append("s1", "assistant", "sunny")

# Read what's there
turns = memory.recent_turns("s1", limit=20)

# Edit a past user message — creates a sibling
target = turns[2]
edited_leaf = memory.append(
    "s1", "user", "what's the time?",
    parent_id=target["parent_id"],     # same parent as the original → sibling
)
# `edited_leaf` is now the active leaf; the original branch still exists
memory.append("s1", "assistant", "it's 4pm")

# Switch back to the original branch
branches = memory.list_branches("s1")
memory.set_active("s1", branches[0]["leaf_id"])
```

## Full signatures

```python
from typing import Protocol, Literal, runtime_checkable

Role = Literal["user", "assistant"]


@runtime_checkable
class MemoryManager(Protocol):
    def append(
        self,
        session_id: str,
        role: Role,
        text: str,
        *,
        parent_id: str | None = None,
        metadata: dict | None = None,
    ) -> str:
        """Append a turn to the session.

        The new turn becomes the active leaf. If `parent_id` is None,
        the parent is the current active leaf (or None for the first
        turn in the session).

        Pass `parent_id` explicitly to write a sibling — this is the
        primitive for editing a past message or regenerating a reply.

        Returns the new turn's id.
        """

    def recent_turns(
        self,
        session_id: str,
        *,
        leaf_id: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """Walk back from `leaf_id` (default: active leaf), newest-first.

        Returns up to `limit` turns. Returns `[]` for an empty session
        or an unknown `leaf_id`.
        """

    def list_branches(self, session_id: str) -> list[dict]:
        """Return every distinct leaf in the session.

        Each entry:
            {
                "leaf_id": str,
                "head_role": "user" | "assistant",
                "head_text_preview": str,    # first ~80 chars
                "head_timestamp": str,        # ISO 8601
                "turn_count": int,            # turns from root to this leaf
                "label": str | None,          # metadata["branch_label"], if any
                "is_active": bool,
            }

        Empty list for an empty session.
        """

    def set_active(self, session_id: str, leaf_id: str) -> None:
        """Make `leaf_id` the active leaf. Subsequent appends attach beneath it.

        Raises `ValueError` if `leaf_id` is not a turn in this session.
        """

    def active_leaf(self, session_id: str) -> str | None:
        """Return the active leaf's turn id, or None for an empty session."""

    def list_sessions(self) -> list[dict]:
        """Return every known session.

        Each entry: {"session_id": str, "turn_count": int, "last_active": str}.
        Returns [] if no sessions exist.
        """

    def delete_session(self, session_id: str) -> None:
        """Remove all storage for the session (the .jsonl and .head files).

        No-op if the session does not exist.
        """

    def status(self) -> dict:
        """Health snapshot, e.g. {'conversation_log': 'online'}."""


def get_memory_manager() -> MemoryManager:
    """Return the shared MemoryManager. Constructs the implementation on first call."""
```

Session ids are opaque strings chosen by the caller (typically a UUID).
There is no `create_session` call — a session comes into existence on
its first `append`.

## How common operations map

| Operation | Call |
|---|---|
| Send a new message | `append(s, "user", text)` |
| Continue the conversation | `append(s, role, text)` — auto-parents on active leaf |
| Edit a past user message at turn T | `append(s, "user", new_text, parent_id=T["parent_id"])` |
| Regenerate the last assistant reply | `append(s, "assistant", new_reply, parent_id=last["parent_id"])` |
| Show the conversation | `recent_turns(s)` |
| Show a specific branch | `recent_turns(s, leaf_id=L)` |
| List all branches in the UI | `list_branches(s)` |
| Switch to a branch the user picked | `set_active(s, leaf_id)` |
| Check what branch is showing | `active_leaf(s)` |

There is no separate `fork_from` — forking is just an `append` with an
explicit `parent_id`. The fork and the new message are one operation.

## Data format

Two files per session, both under `<CONVERSATION_LOG_DIR>/`:

### `{session_id}.jsonl` — append-only, every turn ever written

```jsonc
{"id": "t-001", "parent_id": null,     "role": "user",      "text": "hi",      "timestamp": "...", "metadata": {}}
{"id": "t-002", "parent_id": "t-001",  "role": "assistant", "text": "hello",   "timestamp": "...", "metadata": {}}
{"id": "t-003", "parent_id": "t-001",  "role": "user",      "text": "rephrase","timestamp": "...", "metadata": {"branch_label": "alt"}}
{"id": "t-004", "parent_id": "t-003",  "role": "assistant", "text": "OK",      "timestamp": "...", "metadata": {}}
```

### `{session_id}.head` — atomically replaced via rename

```jsonc
{"active_leaf": "t-004", "updated_at": "..."}
```

### Properties

- The JSONL is append-only. Crash-safe — a truncated tail line is skipped on read.
- The `.head` file is rewritten atomically (write `.head.tmp`, rename to `.head`). At any moment the file is either the previous valid head or the new valid head, never partial.
- The data structure is a tree rooted at the first turn (the one with `parent_id == null`).
- A turn id is a UUID4 with a short prefix. Once written, ids are immutable.

### Turn shape (as returned by `recent_turns`)

```python
{
    "id": str,
    "parent_id": str | None,
    "role": "user" | "assistant",
    "text": str,
    "timestamp": str,         # ISO 8601
    "metadata": dict,
}
```

## Configuration

| Variable | Default | Description |
|---|---|---|
| `CONVERSATION_LOG_DIR` | `./data/conversations` | Directory for `.jsonl` + `.head` files. |
| `TURN_ID_PREFIX` | `t-` | Prefix on generated turn ids. |
| `DEFAULT_RECENT_LIMIT` | `20` | Default `limit` for `recent_turns`. |

## Usage patterns

**FastAPI route — dependency injection:**

```python
from fastapi import Depends
from src.memory import MemoryManager, get_memory_manager

@router.post("/message")
async def handler(memory: MemoryManager = Depends(get_memory_manager)):
    memory.append(session_id, "user", text)
    # ... agent runs ...
    memory.append(session_id, "assistant", reply)
```

**Service function — parameter passing:**

```python
def my_service(text: str, *, memory: MemoryManager) -> list[dict]:
    return memory.recent_turns(session_id)
```

**Edit / regenerate from a UI action:**

```python
# UI sends: session_id, target_turn_id, new_text
target = next(t for t in memory.recent_turns(session_id, limit=100) if t["id"] == target_turn_id)
memory.append(session_id, "user", new_text, parent_id=target["parent_id"])
# new branch is now active
```

## Stability and versioning

The `MemoryManager` Protocol is the public contract.

- **Non-breaking:** adding new methods; adding new optional parameters with defaults; adding new fields to returned dicts.
- **Breaking (major version):** removing methods; making optional params required; renaming methods; removing fields from returned dicts.

The on-disk format (`.jsonl` row shape, `.head` shape) is also part of
the contract for direct consumers. Field additions are
backward-compatible; field removal or rename is breaking.

## Internals

Implementation modules are private and may change without notice:

```
memory/
  __init__.py         Protocol + factory (public)
  _manager.py         concrete `_MemoryManager` class
  _conversation.py    JSONL + .head read/write/walk helpers
  _ids.py             turn id generation
  py.typed            PEP 561 marker
```

The concrete class enforces singleton construction via a private
classmethod (`_MemoryManager.get()`), invoked only by
`get_memory_manager()`. All file I/O is wrapped with error handling per
the resilience rule; failures log via `src.log` at `ERROR` and return
safe degraded values.

## Anti-patterns

- `MemoryManager(...)` — the Protocol has no implementation.
- Capturing the instance at module load (`memory = get_memory_manager()` at file top). Call inside functions, or inject via `Depends`.
- Importing `_manager`, `_conversation`, `_ids`, or any underscore-prefixed module.
- Manually editing `.jsonl` or `.head` files outside the manager — corruption risk.
- Reusing a turn id across sessions.
- Treating the conversation log as a linear list (it is a tree; ignoring branches loses data).
- Mutating attributes on the returned instance.
