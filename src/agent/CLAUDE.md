# aimanager.agent

Chat agent runtime for the AIManager platform. A single in-process
`AgentService` instance handles user messages, with iterative tool calls
inside a single invocation. Exposed through the `AgentService` Protocol.

**Status:** stable. Public Protocol governs the API contract.

## Installation

Part of the `aimanager` distribution. The package is importable as:

```python
from src.agent import (
    AgentService,
    AgentRunRequest,
    AgentRunResult,
    get_agent_service,
)
```

## Quick start

```python
from src.agent import AgentRunRequest, get_agent_service

service = get_agent_service()
result = await service.arun(AgentRunRequest(
    session_id="session-1",
    text="what's the weather?",
))
print(result.reply)
```

## Public API quick reference

The `__init__.py` exports exactly four names:

| Name | Kind | Description |
|---|---|---|
| `AgentService` | `typing.Protocol` | Structural type for the singleton. Not a class to instantiate. |
| `AgentRunRequest` | `@dataclass(frozen=True)` | Input payload for `arun`. |
| `AgentRunResult` | `@dataclass(frozen=True)` | Return value from `arun`. |
| `get_agent_service` | function | Returns the shared instance; constructs it on first call. |

### `AgentService` methods at a glance

| Method | Returns | Purpose |
|---|---|---|
| `arun(request)` | `AgentRunResult` | Run the chat agent against one user message. May call tools and iterate. |

## Full signatures

### `AgentService` Protocol

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class AgentService(Protocol):
    async def arun(self, request: AgentRunRequest) -> AgentRunResult:
        """Run the chat agent against one user message.

        The agent may call tools and iterate multiple LLM turns before
        returning. The result contains the final reply text.
        """
```

### `AgentRunRequest`

```python
@dataclass(frozen=True)
class AgentRunRequest:
    session_id: str
    text: str                            # the latest user message
    history: list[dict]                  # past turns oldest-first; INCLUDES the latest user message at the tip
    metadata: dict = field(default_factory=dict)
```

The orchestration layer (`src.backend.conversation.Conversation`) supplies
`history` by reading from memory. The agent uses it to assemble the
prompt; the agent does **not** fetch history itself from memory (its
tools may still read memory for other purposes — search, older turns,
cross-session lookups).

### `AgentRunResult`

```python
@dataclass(frozen=True)
class AgentRunResult:
    reply: str
    session_id: str
    reply_timestamp: str | None = None   # ISO 8601
```

### `get_agent_service`

```python
def get_agent_service() -> AgentService:
    """Return the shared AgentService. Constructs the implementation on first call."""
```

## Execution model

`arun` is not a single LLM call. The chat agent runs a loop:

1. Build the prompt from the supplied `history` and the user `text`.
2. Send the prompt to the configured LLM, along with the tools schema.
3. If the LLM returns a tool call, execute the tool, append its result to the
   in-flight conversation, and return to step 2.
4. If the LLM returns plain text, that text is the reply.
5. Return an `AgentRunResult` carrying the reply.

The loop may iterate as many times as the LLM requests. To the caller it
is a single `await`.

The agent is **stateless across invocations**. Persistence and history
windowing are the orchestration layer's responsibility
(`src.backend.conversation.Conversation`). The agent receives history as a
parameter, returns a reply string, and never writes to the conversation
log itself.

Tools that the agent invokes may still read memory directly (e.g. a
"search older history" tool, a "look up across sessions" tool). That is
not the same as the agent fetching its own base history; the base
context is what the caller passed in.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `LM_STUDIO_BASE_URL` | `http://localhost:1234/v1` | LM Studio OpenAI-compatible endpoint. |
| `LM_STUDIO_MODEL` | _(required)_ | Model identifier to request. |
| `AGENT_TOOL_TIMEOUT_SECONDS` | `30` | Per-tool execution timeout. |
| `AGENT_MAX_ITERATIONS` | `8` | Hard cap on tool/LLM iterations per `arun` call. |

## Usage patterns

**FastAPI route — dependency injection:**

```python
from fastapi import Depends
from src.agent import AgentService, AgentRunRequest, get_agent_service

@router.post("/message")
async def handler(
    body: dict,
    service: AgentService = Depends(get_agent_service),
):
    result = await service.arun(AgentRunRequest(
        session_id=body["session_id"],
        text=body["text"],
    ))
    return {"reply": result.reply}
```

**Service function — parameter passing:**

```python
async def send_message(text: str, *, service: AgentService) -> str:
    result = await service.arun(AgentRunRequest(session_id="...", text=text))
    return result.reply
```

## Stability and versioning

The `AgentService` Protocol and the request/result dataclasses are the
public contract.

- **Non-breaking:** adding new methods on `AgentService`, adding new optional fields with defaults on the dataclasses, adding new tools (tools are not part of the public API).
- **Breaking (major version):** removing methods or fields, narrowing types, making optional fields required, changing existing signatures.

## Internals

Implementation modules are private and may change without notice:

```
agent/
  __init__.py        Protocol + dataclasses + factory (public)
  _service.py        concrete `_AgentService` class
  _loop.py           chat agent loop (LLM + tools iteration)
  _tools/
    __init__.py      TOOLS list (consumed by `_loop`)
    memory.py        memory-related tools
  _models/
    __init__.py      active LLM adapter
    lmstudio.py      LM Studio (OpenAI-compatible) adapter
  py.typed           PEP 561 marker — package ships types
```

The concrete class enforces singleton construction via a private
classmethod (`_AgentService.get()`), invoked only by
`get_agent_service()`. Tools are registered automatically from the
`_tools` package and exposed to the LLM at runtime.

## Anti-patterns

- `AgentService(...)` — the Protocol has no implementation.
- Capturing the instance at module load. Call inside functions, or inject via `Depends`.
- Importing `_service`, `_loop`, `_tools`, `_models`, or any underscore-prefixed module.
- Calling tools directly from outside the agent package.
- Writing to the conversation log from inside the agent.
- Mutating attributes on the returned instance.
