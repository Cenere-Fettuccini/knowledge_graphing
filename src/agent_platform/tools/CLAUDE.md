# Agent Platform — Tools

Agent tools are plain Python functions the LLM can call during a turn. The
agent framework discovers them via `registry.py` and passes them to PydanticAI
at initialization time.

## Files
| File | Tool(s) | Purpose |
|------|---------|---------|
| `registry.py` | `tools` list | Master list of all active tools |
| `memory.py` | `search_memories` | Semantic search over past conversation turns |
| `graph.py` | `search_knowledge_graph` | Read-only search over the Neo4j knowledge graph |
| `graph_write.py` | `graph_write` | Unified write surface for entities, beliefs, tasks, edges |
| `beliefs.py` | `get_belief_trail`, `evolve_belief_tool` | Belief read + supersession |
| `tasks.py` | `list_tasks`, `update_task` | Task read + status update |
| `time_tools.py` | `get_current_time` | Current UTC time |
| `common.py` | shared helpers | Graph health check, logger |

---

## Called By
| Caller | What it uses |
|--------|-------------|
| `src.core.agent` | `tools` list from `registry.py` — passed to the PydanticAI `Agent` at init |

Tools themselves are **invoked by the LLM** during a turn; the agent framework
calls them, not application code.

---

## Calls Into
| Dependency | What is called |
|------------|---------------|
| `src.memory.manager` | `get_memory_manager()` — all tools that read/write memory call this |
| `src.core.config` | `settings` — e.g. Google Search API key, Calendar credentials |
| `src.agent_platform.tools.common` | `ensure_graph_online()`, `logger` |
| Google Custom Search API | `search_memories` / `web_search` tools |
| Google Calendar API | `list_events`, `create_event`, `delete_event` tools |

---

## Active Tools (from `registry.py`)
```python
from src.agent_platform.tools.registry import tools
# tools = [
#   search_knowledge_graph,
#   graph_write,
#   search_memories,
#   get_current_time,
#   list_tasks, update_task,
#   get_belief_trail, evolve_belief_tool,
#   web_search, list_events, create_event, delete_event,
# ]
```

---

## Graph Writes — all go through `graph_write`
`store_knowledge`, `save_belief`, and `create_task` were retired in S0.10.
Use `graph_write([...intents])` with one of four intent kinds:

```python
{"kind": "entity", "name": "Mom", "label": "Person", "description": "..."}
{"kind": "belief", "content": "...", "about_entity": "Mom", "confidence": 0.9}
{"kind": "task",   "title": "Bake cake", "due_date": "2026-05-20", "for_person": "Mom"}
{"kind": "edge",   "source": "Mom", "target": "Birthday Cake", "rel_type": "WANTS"}
```

**Invariant enforced:** every node touched in a batch must end up with ≥1 edge.
New entities without an edge in the same batch are rejected. Beliefs and tasks
auto-anchor to the user root if no other anchor resolves.

The LLM anchor-proposal hook (`_Resolver._propose_anchor`) is currently a stub.
The deterministic resolver handles every case in practice. The contract for a
future implementation is in the `_propose_anchor` docstring: input shape,
required output (`EntityIntent | None`), recursion-depth cap, failure modes.

---

## Adding a New Tool

1. Create your function in an appropriate file (or a new file in this directory)
2. Give it a clear docstring — the LLM uses the docstring as the tool description
3. Use type annotations on all parameters — these become the tool's input schema
4. Import it in `registry.py` and add it to the `tools` list

```python
def my_tool(param_a: str, param_b: int = 5) -> dict:
    """Short description for the LLM. Explain what it does and when to use it."""
    memory = get_memory_manager()
    ...
```

---

## Coupling Notes
- Tools call `get_memory_manager()` directly — **not** via FastAPI `Depends()`.
  They run inside an agent turn, not inside a request handler.
- Tools must **not** import from `src.apps.*`. They are infrastructure, not
  feature code.
- Adding a tool only requires editing `registry.py` — the agent picks up the
  new list on next initialization (next server start).
- `common.py::ensure_graph_online()` returns an error string if Neo4j is
  unreachable; graph tools should return that string early rather than crashing.
