# Agent Platform — Tools

Agent tools are the functions the LLM can call during a turn. Each tool is a plain
Python function decorated so the agent framework can discover and invoke it.

## Files
| File | Tool(s) | Purpose |
|------|---------|---------|
| `registry.py` | `tools` list | Master list of all active tools — import this to get all tools |
| `memory.py` | `search_memories` | Semantic search over past conversation turns |
| `graph.py` | `search_knowledge_graph`, `store_knowledge` | Read/write Neo4j knowledge graph |
| `beliefs.py` | `save_belief`, `get_belief_trail`, `evolve_belief_tool` | Belief/fact management |
| `tasks.py` | `create_task`, `list_tasks`, `update_task` | Task graph nodes |
| `time_tools.py` | `get_current_time` | Current UTC time |
| `common.py` | Shared helpers | Graph health checks, logging utilities |

## Active Tools (from `registry.py`)
```python
from src.agent_platform.tools.registry import tools
# tools = [
#   search_knowledge_graph, store_knowledge,
#   search_memories,
#   get_current_time,
#   create_task, list_tasks, update_task,
#   save_belief, get_belief_trail, evolve_belief_tool,
# ]
```

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
