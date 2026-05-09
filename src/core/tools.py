"""Compatibility shim for the shared agent tool registry."""

from src.agent_platform.tools.beliefs import (
    evolve_belief_tool,
    get_belief_trail,
    save_belief,
)
from src.agent_platform.tools.graph import search_knowledge_graph, store_knowledge
from src.agent_platform.tools.memory import search_memories
from src.agent_platform.tools.registry import tools
from src.agent_platform.tools.tasks import create_task, list_tasks, update_task
from src.agent_platform.tools.time_tools import get_current_time

__all__ = [
    "search_knowledge_graph",
    "store_knowledge",
    "search_memories",
    "get_current_time",
    "create_task",
    "list_tasks",
    "update_task",
    "save_belief",
    "get_belief_trail",
    "evolve_belief_tool",
    "tools",
]
