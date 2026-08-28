"""SQLite persistence operations for SIRIUS reminders."""

from app.storage.database import get_connection


def insert_reminder(text, remind_at, status, created_at, database_path=None):
    """Insert a reminder and return its database identifier."""
    connection = get_connection(database_path)

    try:
        cursor = connection.execute("""
            INSERT INTO reminders (text, remind_at, status, created_at)
            VALUES (?, ?, ?, ?)
        """, (text, remind_at, status, created_at))
        connection.commit()
        return cursor.lastrowid
    finally:
        connection.close()


def fetch_reminders(database_path=None):
    """Return all reminders ordered by their reminder time."""
    connection = get_connection(database_path)

    try:
        cursor = connection.execute("""
            SELECT id, text, remind_at, status, created_at
            FROM reminders
            ORDER BY remind_at ASC, id ASC
        """)
        return cursor.fetchall()
    finally:
        connection.close()


def update_reminder_status(reminder_id, status, database_path=None):
    """Update a reminder status and report whether it was found."""
    connection = get_connection(database_path)

    try:
        cursor = connection.execute("""
            UPDATE reminders
            SET status = ?
            WHERE id = ?
        """, (status, reminder_id))
        connection.commit()
        return cursor.rowcount > 0
    finally:
        connection.close()


def delete_reminder_by_id(reminder_id, database_path=None):
    """Delete a reminder and report whether it was found."""
    connection = get_connection(database_path)

    try:
        cursor = connection.execute("""
            DELETE FROM reminders
            WHERE id = ?
        """, (reminder_id,))
        connection.commit()
        return cursor.rowcount > 0
    finally:
        connection.close()
