"""Task-command assistant backed by the existing task service."""

from app.core.intents import (
    ADD_TASK,
    COMPLETE_TASK,
    DELETE_TASK,
    LIST_TASKS,
    route_command,
)
from app.tools.tasks import service


UNKNOWN_COMMAND_MESSAGE = (
    "Unknown command. Try: add task <title>, list tasks, "
    "complete task <id>, or delete task <id>."
)


def format_tasks(tasks):
    """Format task rows returned by the existing task service for the terminal."""
    if not tasks:
        return "No tasks found."

    lines = ["========== YOUR TASKS =========="]
    for task_id, title, description, due_date, priority, status, _created_at in tasks:
        lines.extend((
            f"[{task_id}] {title}",
            f"    Priority : {priority}",
            f"    Status   : {status}",
            f"    Due      : {due_date or 'No deadline'}",
        ))
        if description:
            lines.append(f"    Details  : {description}")
    lines.append("================================")
    return "\n".join(lines)


def handle_command(command, database_path=None):
    """Execute one supported task command and return a user-facing response."""
    intent = route_command(command)

    if intent.name == ADD_TASK:
        task_id = service.add_task(intent.title, database_path=database_path)
        return f"Task created successfully! ID: {task_id}"

    if intent.name == LIST_TASKS:
        return format_tasks(service.get_tasks(database_path=database_path))

    if intent.name == COMPLETE_TASK:
        if service.complete_task(intent.task_id, database_path=database_path):
            return "Task completed!"
        return "Task not found."

    if intent.name == DELETE_TASK:
        if service.delete_task(intent.task_id, database_path=database_path):
            return "Task deleted."
        return "Task not found."

    return UNKNOWN_COMMAND_MESSAGE
