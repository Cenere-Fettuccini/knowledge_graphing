from __future__ import annotations

from src.agent_platform.tools.common import ensure_graph_online, logger
from src.memory.manager import get_memory_manager

# create_task was retired in S0.10 — use graph_write with a TaskIntent.
# Tasks must connect to the entity they relate to (for_person or about_entity);
# they are NOT owned by the user root.


def list_tasks(status_filter: str = "", include_completed: bool = False):
    """
    List tasks from the Knowledge Graph.

    By default only live tasks are returned — DONE and CANCELLED are hidden
    so the punch-list stays focused. Set include_completed=True to see the
    full history. Pass status_filter to further narrow within whatever set
    is returned (TODO, IN_PROGRESS, DONE, BLOCKED, CANCELLED).
    """
    logger.info(
        "Tool Call: list_tasks -> filter=%s include_completed=%s",
        status_filter, include_completed,
    )
    try:
        offline = ensure_graph_online()
        if offline:
            return offline

        tasks = get_memory_manager().graph_active_tasks(
            include_completed=include_completed
        )
        if status_filter:
            tasks = [
                t for t in tasks
                if t.get("status", "").upper() == status_filter.upper()
            ]
        return tasks if tasks else "No tasks found."
    except Exception as e:
        return f"Error listing tasks: {str(e)}"


def update_task(task_title: str, new_status: str = "", notes: str = ""):
    """
    Update an existing task's status or add notes.
    Find the task by title (partial match).
    Valid statuses: TODO, IN_PROGRESS, DONE, BLOCKED, CANCELLED.
    """
    logger.info("Tool Call: update_task -> %s status=%s", task_title, new_status)
    try:
        offline = ensure_graph_online()
        if offline:
            return offline

        return get_memory_manager().update_task(task_title, new_status, notes)
    except Exception as e:
        return f"Error updating task: {str(e)}"
