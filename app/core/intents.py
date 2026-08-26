"""Parse the small, deterministic Sirius task-command vocabulary."""

from dataclasses import dataclass
import re


ADD_TASK = "add_task"
LIST_TASKS = "list_tasks"
COMPLETE_TASK = "complete_task"
DELETE_TASK = "delete_task"
UNKNOWN_COMMAND = "unknown_command"


@dataclass(frozen=True)
class Intent:
    """A command recognized by the deterministic task router."""

    name: str
    title: str | None = None
    task_id: int | None = None


def route_command(command):
    """Return the intent represented by *command*, without using an LLM."""
    normalized = " ".join(command.strip().split())

    if normalized.lower() == "list tasks":
        return Intent(LIST_TASKS)

    add_match = re.fullmatch(r"add task\s+(.+)", normalized, flags=re.IGNORECASE)
    if add_match:
        return Intent(ADD_TASK, title=add_match.group(1))

    for intent_name, pattern in (
        (COMPLETE_TASK, r"complete task\s+(\d+)"),
        (DELETE_TASK, r"delete task\s+(\d+)"),
    ):
        match = re.fullmatch(pattern, normalized, flags=re.IGNORECASE)
        if match:
            return Intent(intent_name, task_id=int(match.group(1)))

    return Intent(UNKNOWN_COMMAND)
