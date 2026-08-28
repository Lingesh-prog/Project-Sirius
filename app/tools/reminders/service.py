"""Business logic for the SIRIUS reminder tool."""

from datetime import datetime

from app.tools.reminders import repository


PENDING_STATUS = "Pending"
COMPLETED_STATUS = "Completed"
VALID_STATUSES = (PENDING_STATUS, COMPLETED_STATUS)


def create_reminder(text, remind_at, database_path=None):
    """Create a pending reminder and return its identifier."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Reminder text cannot be empty.")

    _validate_remind_at(remind_at)
    created_at = datetime.now().isoformat(timespec="seconds")

    return repository.insert_reminder(
        text=text,
        remind_at=remind_at,
        status=PENDING_STATUS,
        created_at=created_at,
        database_path=database_path,
    )


def list_reminders(database_path=None):
    """Return reminders ordered by their reminder time."""
    return repository.fetch_reminders(database_path=database_path)


def mark_reminder_completed(reminder_id, database_path=None):
    """Mark a matching reminder as completed."""
    return repository.update_reminder_status(
        reminder_id,
        COMPLETED_STATUS,
        database_path=database_path,
    )


def delete_reminder(reminder_id, database_path=None):
    """Delete a matching reminder."""
    return repository.delete_reminder_by_id(reminder_id, database_path=database_path)


def _validate_remind_at(remind_at):
    """Ensure a reminder time is an ISO 8601 datetime string."""
    if not isinstance(remind_at, str) or ("T" not in remind_at and " " not in remind_at):
        raise ValueError("remind_at must be a valid ISO datetime.")

    try:
        datetime.fromisoformat(remind_at)
    except ValueError as error:
        raise ValueError("remind_at must be a valid ISO datetime.") from error
