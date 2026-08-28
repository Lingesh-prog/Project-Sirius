"""Task business logic for the Sirius Focus tool."""

from datetime import datetime

from app.tools.tasks import repository


VALID_PRIORITIES = ("Low", "Medium", "High")
PENDING_STATUS = "Pending"
COMPLETED_STATUS = "Completed"


def add_task(title, description="", due_date=None, priority="Medium", database_path=None):
    """Create a pending task and return its identifier."""
    if not title.strip():
        raise ValueError("Task title cannot be empty.")

    if priority not in VALID_PRIORITIES:
        raise ValueError("Priority must be Low, Medium, or High.")

    created_at = datetime.now().isoformat(timespec="seconds")

    return repository.insert_task(
        title=title,
        description=description,
        due_date=due_date,
        priority=priority,
        status=PENDING_STATUS,
        created_at=created_at,
        database_path=database_path,
    )


def get_tasks(database_path=None):
    """Return tasks in the Sirius Focus display order."""
    return repository.fetch_tasks(database_path=database_path)


def complete_task(task_id, database_path=None):
    """Mark a matching task as completed."""
    return repository.update_task_status(
        task_id,
        COMPLETED_STATUS,
        database_path=database_path,
    )


def delete_task(task_id, database_path=None):
    """Delete a matching task."""
    return repository.delete_task_by_id(task_id, database_path=database_path)


UPDATABLE_FIELDS = ("title", "description", "due_date", "priority")
PROTECTED_FIELDS = ("status", "created_at", "id")


def update_task(task_id, database_path=None, **fields):
    """Update the given fields of one existing task.

    Only title, description, due_date, and priority can be changed. Status,
    created_at, and id are protected. At least one updatable field must be
    supplied. Returns True when a matching task was found.
    """
    updates = {}
    for name, value in fields.items():
        if name in PROTECTED_FIELDS:
            raise ValueError(f"Field '{name}' cannot be updated.")
        if name not in UPDATABLE_FIELDS:
            raise ValueError(f"Unknown task field '{name}'.")
        if value is None:
            continue
        updates[name] = value

    if not updates:
        raise ValueError("At least one field must be supplied to update a task.")

    if "title" in updates and not updates["title"].strip():
        raise ValueError("Task title cannot be empty.")

    if "priority" in updates and updates["priority"] not in VALID_PRIORITIES:
        raise ValueError("Priority must be Low, Medium, or High.")

    return repository.update_task_fields(task_id, updates, database_path=database_path)
