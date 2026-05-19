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
    AgentRunError,
    RegistryLookupError,
    UnknownAgentError,
    UnknownModelError,
    UnknownToolError,
    DEFAULT_AGENT,
    get_agent_service,
)
```

## Quick start

```python
from src.agent import AgentRunRequest, get_agent_service

service = get_agent_service("chat")          # name defaults to DEFAULT_AGENT ("chat")
result = await service.arun(AgentRunRequest(
    session_id="session-1",
    text="what's the weather?",
))
print(result.reply)
```

`get_agent_service` is a **per-agent factory**: each registered agent
name maps to its own cached `_AgentService` instance. A future
graph-builder agent will simply add a new file under
`src/agent/_agents/` and become reachable as
`get_agent_service("graph_builder")` without any wiring change.

## Public API quick reference

The `__init__.py` exports:

| Name | Kind | Description |
|---|---|---|
| `AgentService` | `typing.Protocol` | Structural type for a per-name agent singleton. Not a class to instantiate. |
| `AgentRunRequest` | `@dataclass(frozen=True)` | Input payload for `arun`. |
| `AgentRunResult` | `@dataclass(frozen=True)` | Return value from `arun`. |
| `AgentRunError` | `RuntimeError` subclass | Raised by `arun` on LLM-unreachable, malformed response, or iteration-cap exhaustion. |
| `RegistryLookupError` | `LookupError` subclass | Base for the three `Unknown*Error` types below. |
| `UnknownAgentError` | `RegistryLookupError` | Raised by `get_agent_service` (or the underlying agent registry) on an unregistered name. |
| `UnknownModelError` | `RegistryLookupError` | Raised when an agent references a model not in `BaseModel._registry`. |
| `UnknownToolError` | `RegistryLookupError` | Raised when an agent references a tool not in `BaseTool._registry`. |
| `DEFAULT_AGENT` | `str` constant (`"chat"`) | Name used when `get_agent_service()` is called without an argument. |
| `get_agent_service` | function | `get_agent_service(name=DEFAULT_AGENT)` → per-agent cached singleton. |

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
DEFAULT_AGENT = "chat"

def get_agent_service(name: str = DEFAULT_AGENT) -> AgentService:
    """Return the shared service for ``name``.

    Each registered agent has its own cached service. The first call
    for a given name resolves the agent's declared model + tools
    through their registries. Raises ``UnknownAgentError`` /
    ``UnknownModelError`` / ``UnknownToolError`` when a referenced
    name isn't registered.
    """
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

Implementation modules are private and may change without notice. The
package is organised as three parallel registries — agents, models,
tools — each with a base class that auto-registers concrete subclasses
on import. Adding a new agent / model / tool is one new file; nothing
else changes.

```
agent/
  __init__.py            Protocol + dataclasses + errors + factory (public)
  _errors.py             AgentRunError + RegistryLookupError family
  _service.py            concrete `_AgentService` (one cached instance per agent name)
  _loop.py               LLM + tools iteration; parameterised on prompt/llm/tools
  _agents/
    __init__.py          imports every concrete agent → registry populated
    _base.py             `BaseAgent` + `BaseAgent._registry` + `get`/`all_names`/`identify`
    chat.py              `CHAT_AGENT_PROMPT` constant + `ChatAgent(BaseAgent)`
  _models/
    __init__.py          imports every concrete model → registry populated
    _base.py             `BaseModel` + `BaseModel._registry` + `get`/`all_names`/`identify`
    lmstudio.py          `LMStudioModel(BaseModel)`
  _tools/
    __init__.py          imports every concrete tool → registry populated
    _base.py             `BaseTool` + `BaseTool._registry` + `schema` + `get`/`all_names`/`identify`
    memory.py            `RecallRecentTool(BaseTool)`
  py.typed               PEP 561 marker
```

### The registration pattern (template for new agents / models / tools)

Each base class follows the same shape:

1. **Class-level metadata** describes the artifact (`name`,
   `description`, plus per-kind fields — `prompt`/`model`/`tools` for
   agents, `parameters` for tools).
2. **`__init_subclass__`** auto-inserts the subclass (or a singleton
   instance, for models and tools) into a class-level `_registry`
   dict, keyed by `name`. Empty `name` skips registration (used for
   abstract intermediates and test doubles).
3. **`get(name)`** raises a typed `Unknown{Agent,Model,Tool}Error` —
   subclass of `RegistryLookupError` — on miss. Misnamed references
   fail at boot, not at request time.
4. **`identify()`** returns a `dict` self-description used by
   diagnostics (and by the future `/flows` page).
5. **`all_names()`** lists every registered name, sorted.

### Adding a new agent

```python
# src/agent/_agents/graph_builder.py
"""Graph-builder agent — extracts entities and edges from conversation."""

GRAPH_BUILDER_PROMPT = """You are a knowledge-graph extractor..."""

from src.agent._agents._base import BaseAgent


class GraphBuilderAgent(BaseAgent):
    name = "graph_builder"
    description = "Extracts entity / edge intents from a conversation slice."
    prompt = GRAPH_BUILDER_PROMPT
    model = "lmstudio"                  # any name registered in BaseModel._registry
    tools = ["recall_recent"]           # any names registered in BaseTool._registry
```

Then add `from src.agent._agents import graph_builder` to
`_agents/__init__.py` so the import side-effect fires on package load.
The agent is immediately reachable as `get_agent_service("graph_builder")`.

Adding a new model or tool follows the same shape — subclass
`BaseModel` / `BaseTool`, set `name`, implement `chat` / `run`, register
the module in the corresponding package `__init__.py`.

## Anti-patterns

- `AgentService(...)` — the Protocol has no implementation.
- Capturing the instance at module load. Call inside functions, or inject via `Depends`.
- Importing `_service`, `_loop`, `_tools`, `_models`, `_agents`, or any underscore-prefixed module.
- Calling tools directly from outside the agent package.
- Writing to the conversation log from inside the agent.
- Mutating attributes on the returned instance.
- Bypassing the registries — e.g. constructing `LMStudioModel()` ad-hoc and passing it to the loop. Always go through `get_model(name)` / `get_tool(name)` so misnamed references fail at the registry boundary instead of producing surprises at request time.
- Defining two artifacts under the same `name`. `__init_subclass__` rejects the duplicate at import time.
