from __future__ import annotations

import uuid
from datetime import datetime

from src.agent_platform.tools.common import ensure_graph_online, logger
from src.memory.manager import get_memory_manager


def create_task(title: str, due_date: str = None, priority: str = "medium"):
    """
    Create a new task or goal for the user.
    Example: title="Finish project", due_date="2024-05-10", priority="high"
    """
    logger.info("Tool Call: create_task -> %s", title)
    try:
        properties = {
            "status": "TODO",
            "due_date": due_date,
            "priority": priority,
            "created_at": datetime.now().isoformat(),
        }
        node_id = str(uuid.uuid4())
        get_memory_manager().upsert_node(
            node_id=node_id,
            labels=["Task"],
            name=title,
            properties=properties,
        )
        return f"Task created: '{title}' (ID: {node_id})"
    except Exception as e:
        return f"Error creating task: {str(e)}"


def list_tasks(status_filter: str = ""):
    """
    List tasks from the Knowledge Graph, optionally filtered by status.
    Valid statuses: TODO, IN_PROGRESS, DONE, BLOCKED, CANCELLED.
    Leave empty to list all tasks.
    """
    logger.info("Tool Call: list_tasks -> filter=%s", status_filter)
    try:
        offline = ensure_graph_online()
        if offline:
            return offline

        tasks = get_memory_manager().graph_active_tasks()
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
