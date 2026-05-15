# Agent Platform — Tools

Agent tools are the functions the LLM can call during a turn. Each tool is a plain
Python function decorated so the agent framework can discover and invoke it.

## Files
| File | Tool(s) | Purpose |
|------|---------|---------|
| `registry.py` | `tools` list | Master list of all active tools — import this to get all tools |
| `memory.py` | `search_memories` | Semantic search over past conversation turns |
| `graph.py` | `search_knowledge_graph` | Read-only search over Neo4j knowledge graph |
| `graph_write.py` | `graph_write` | Unified write surface for entities, beliefs, tasks, edges. Enforces no-isolated-nodes and runs the reachability sweep. |
| `beliefs.py` | `get_belief_trail`, `evolve_belief_tool` | Belief read + supersession |
| `tasks.py` | `list_tasks`, `update_task` | Task read + status update (writes new tasks via `graph_write`) |
| `time_tools.py` | `get_current_time` | Current UTC time |
| `common.py` | Shared helpers | Graph health checks, logging utilities |

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

## Graph writes — all go through `graph_write`
`store_knowledge`, `save_belief`, and `create_task` were retired in S0.10.
Use `graph_write([...intents])` with one of four intent kinds:

```python
{"kind": "entity", "name": "Mom", "label": "Person", "description": "..."}
{"kind": "belief", "content": "...", "about_entity": "Mom", "confidence": 0.9}
{"kind": "task",   "title": "Bake cake", "due_date": "2026-05-20", "for_person": "Mom"}
{"kind": "edge",   "source": "Mom", "target": "Birthday Cake", "rel_type": "WANTS"}
```

The tool enforces an invariant: every node touched in a batch must end up
with ≥1 edge. New entities without an edge in the same batch are rejected.
Beliefs and tasks auto-anchor to the user root if no other anchor resolves.

## Adding a New Tool

1. Create your function in an appropriate file (or a new file in this directory)
2. Give it a clear docstring — the LLM uses the docstring as the tool description
3. Use type annotations on all parameters — these become the tool's input schema
4. Import it in `registry.py` and add it to the `tools` list

```python
# Example tool signature
def my_tool(param_a: str, param_b: int = 5) -> dict:
    """Short description for the LLM. Explain what it does and when to use it."""
    ...
```

## Dependencies Available in Tools
Tools run inside the agent turn and call `get_memory_manager()` directly (not via FastAPI `Depends()`):
```python
from src.memory.manager import get_memory_manager
from src.core.config import settings

def my_tool(param: str) -> str:
    memory = get_memory_manager()
    ...
```

Tools should NOT import from `src.apps.*`.
