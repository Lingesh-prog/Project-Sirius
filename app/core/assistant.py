"""Assistant that coordinates the Sirius Focus tools."""

from app.core.intents import (
    ADD_REMINDER,
    ADD_TASK,
    COMPLETE_REMINDER,
    COMPLETE_TASK,
    DELETE_REMINDER,
    DELETE_TASK,
    LIST_REMINDERS,
    LIST_TASKS,
    route_command,
)
from app.tools.reminders import service as reminder_service
from app.tools.tasks import service


UNKNOWN_COMMAND_MESSAGE = (
    "Unknown command. Try: add task <title>, list tasks, "
    "complete task <id>, or delete task <id>, "
    "add reminder <text> at <YYYY-MM-DDTHH:MM>, list reminders, "
    "complete reminder <id>, or delete reminder <id>."
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


def format_reminders(reminders):
    """Format reminder rows returned by the reminder service for the terminal."""
    if not reminders:
        return "No reminders found."

    lines = ["========== YOUR REMINDERS =========="]
    for reminder_id, text, remind_at, status, _created_at in reminders:
        lines.extend((
            f"[{reminder_id}] {text}",
            f"    Remind at: {remind_at}",
            f"    Status   : {status}",
        ))
    lines.append("====================================")
    return "\n".join(lines)


def handle_command(command, database_path=None):
    """Execute one supported command and return a user-facing response."""
    intent = route_command(command)

    if intent.name == ADD_TASK:
        task_id = service.add_task(intent.title, database_path=database_path)
        return f"Task created successfully! ID: {task_id}"

    if intent.name == ADD_REMINDER:
        try:
            reminder_id = reminder_service.create_reminder(
                intent.text, intent.remind_at, database_path=database_path
            )
        except ValueError as error:
            return f"Reminder not created. {error}"
        return f"Reminder created successfully! ID: {reminder_id}"

    if intent.name == LIST_TASKS:
        return format_tasks(service.get_tasks(database_path=database_path))

    if intent.name == LIST_REMINDERS:
        return format_reminders(
            reminder_service.list_reminders(database_path=database_path)
        )

    if intent.name == COMPLETE_TASK:
        if service.complete_task(intent.task_id, database_path=database_path):
            return "Task completed!"
        return "Task not found."

    if intent.name == DELETE_TASK:
        if service.delete_task(intent.task_id, database_path=database_path):
            return "Task deleted."
        return "Task not found."

    if intent.name == COMPLETE_REMINDER:
        if reminder_service.mark_reminder_completed(
            intent.reminder_id, database_path=database_path
        ):
            return "Reminder completed!"
        return "Reminder not found."

    if intent.name == DELETE_REMINDER:
        if reminder_service.delete_reminder(
            intent.reminder_id, database_path=database_path
        ):
            return "Reminder deleted."
        return "Reminder not found."

    return UNKNOWN_COMMAND_MESSAGE
