from __future__ import annotations

from src.agent_platform.tools.beliefs import evolve_belief_tool, get_belief_trail
from src.agent_platform.tools.graph import search_knowledge_graph
from src.agent_platform.tools.graph_write import graph_write
from src.agent_platform.tools.memory import search_memories
from src.agent_platform.tools.tasks import list_tasks, update_task
from src.agent_platform.tools.time_tools import get_current_time
from src.tools.calendar import create_event, delete_event, list_events
from src.tools.search import web_search

# After S0.10, `graph_write` is the single agent-facing write surface for
# entities, beliefs, tasks, and edges. The old direct-write tools
# (store_knowledge, save_belief, create_task) are retired — they bypassed
# the isolation guard and reachability sweep.
tools = [
    search_knowledge_graph,
    graph_write,
    search_memories,
    get_current_time,
    list_tasks,
    update_task,
    get_belief_trail,
    evolve_belief_tool,
    web_search,
    list_events,
    create_event,
    delete_event,
]
