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
