from __future__ import annotations

from datetime import datetime

from langchain_core.tools import tool

from src.agent_platform.tools.common import ensure_graph_online, logger
from src.memory.manager import memory_manager


@tool
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
        node_id = memory_manager.neo4j.add_node("Task", title, properties)
        return f"Task created: '{title}' (ID: {node_id})"
    except Exception as e:
        return f"Error creating task: {str(e)}"


@tool
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

        if status_filter:
            cypher = """
            MATCH (t:Task)
            WHERE toLower(t.status) = toLower($status)
            RETURN t.id AS id, t.name AS title, t.status AS status,
                   t.priority AS priority, t.due_date AS due_date
            ORDER BY t.created_at DESC
            """
            params = {"status": status_filter}
        else:
            cypher = """
            MATCH (t:Task)
            RETURN t.id AS id, t.name AS title, t.status AS status,
                   t.priority AS priority, t.due_date AS due_date
            ORDER BY t.created_at DESC
            """
            params = {}

        results = []
        with memory_manager.neo4j.driver.session() as session:
            records = session.run(cypher, **params)
            for record in records:
                results.append({
                    "id": record["id"],
                    "title": record["title"],
                    "status": record["status"],
                    "priority": record["priority"],
                    "due_date": record["due_date"],
                })
        return results if results else "No tasks found."
    except Exception as e:
        return f"Error listing tasks: {str(e)}"


@tool
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

        set_parts = ["t.updated_at = $now"]
        params = {"title": task_title, "now": datetime.now().isoformat()}
        if new_status:
            set_parts.append("t.status = $status")
            params["status"] = new_status.upper()
        if notes:
            set_parts.append("t.notes = $notes")
            params["notes"] = notes

        cypher = f"""
        MATCH (t:Task)
        WHERE toLower(t.name) CONTAINS toLower($title)
        SET {', '.join(set_parts)}
        RETURN t.name AS title, t.status AS status
        LIMIT 1
        """

        with memory_manager.neo4j.driver.session() as session:
            result = session.run(cypher, **params)
            record = result.single()
            if record:
                return f"Updated task '{record['title']}' -> status: {record['status']}"
            return f"No task found matching '{task_title}'"
    except Exception as e:
        return f"Error updating task: {str(e)}"
