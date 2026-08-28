"""Parse the small, deterministic Sirius command vocabulary."""

from dataclasses import dataclass
import re


ADD_TASK = "add_task"
LIST_TASKS = "list_tasks"
COMPLETE_TASK = "complete_task"
DELETE_TASK = "delete_task"
CONFIRM_DELETE_TASK = "confirm_delete_task"
ADD_REMINDER = "add_reminder"
LIST_REMINDERS = "list_reminders"
COMPLETE_REMINDER = "complete_reminder"
DELETE_REMINDER = "delete_reminder"
CONFIRM_DELETE_REMINDER = "confirm_delete_reminder"
CONFIRM_DELETE_MEMORY = "confirm_delete_memory"
UNKNOWN_COMMAND = "unknown_command"


@dataclass(frozen=True)
class Intent:
    """A command recognized by the deterministic command router."""

    name: str
    title: str | None = None
    task_id: int | None = None
    text: str | None = None
    remind_at: str | None = None
    reminder_id: int | None = None
    memory_id: int | None = None


def route_command(command):
    """Return the intent represented by *command*, without using an LLM."""
    normalized = " ".join(command.strip().split())

    if normalized.lower() == "list tasks":
        return Intent(LIST_TASKS)

    if normalized.lower() == "list reminders":
        return Intent(LIST_REMINDERS)

    add_match = re.fullmatch(r"add task\s+(.+)", normalized, flags=re.IGNORECASE)
    if add_match:
        return Intent(ADD_TASK, title=add_match.group(1))

    add_reminder_match = re.fullmatch(
        r"add reminder\s+(.+)\s+at\s+(.+)", normalized, flags=re.IGNORECASE
    )
    if add_reminder_match:
        return Intent(
            ADD_REMINDER,
            text=add_reminder_match.group(1),
            remind_at=add_reminder_match.group(2),
        )

    for intent_name, pattern in (
        (COMPLETE_TASK, r"complete task\s+(\d+)"),
        (DELETE_TASK, r"delete task\s+(\d+)"),
        (CONFIRM_DELETE_TASK, r"confirm delete task\s+(\d+)"),
    ):
        match = re.fullmatch(pattern, normalized, flags=re.IGNORECASE)
        if match:
            return Intent(intent_name, task_id=int(match.group(1)))

    for intent_name, pattern in (
        (COMPLETE_REMINDER, r"complete reminder\s+(\d+)"),
        (DELETE_REMINDER, r"delete reminder\s+(\d+)"),
        (CONFIRM_DELETE_REMINDER, r"confirm delete reminder\s+(\d+)"),
    ):
        match = re.fullmatch(pattern, normalized, flags=re.IGNORECASE)
        if match:
            return Intent(intent_name, reminder_id=int(match.group(1)))

    confirm_memory_match = re.fullmatch(
        r"confirm delete memory\s+(\d+)", normalized, flags=re.IGNORECASE
    )
    if confirm_memory_match:
        return Intent(
            CONFIRM_DELETE_MEMORY, memory_id=int(confirm_memory_match.group(1))
        )

    return Intent(UNKNOWN_COMMAND)
