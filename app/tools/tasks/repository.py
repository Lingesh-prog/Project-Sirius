"""SQLite persistence operations for Sirius Focus tasks."""

from app.storage.database import get_connection


def insert_task(title, description, due_date, priority, status, created_at, database_path=None):
    """Insert a task and return its database identifier."""
    connection = get_connection(database_path)

    try:
        cursor = connection.execute("""
            INSERT INTO tasks
            (title, description, due_date, priority, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (title, description, due_date, priority, status, created_at))
        connection.commit()
        return cursor.lastrowid
    finally:
        connection.close()


def fetch_tasks(database_path=None):
    """Return all tasks in the current Sirius Focus display order."""
    connection = get_connection(database_path)

    try:
        cursor = connection.execute("""
            SELECT id, title, description, due_date, priority, status, created_at
            FROM tasks
            ORDER BY
                CASE priority
                    WHEN 'High' THEN 1
                    WHEN 'Medium' THEN 2
                    WHEN 'Low' THEN 3
                END,
                id DESC
        """)
        return cursor.fetchall()
    finally:
        connection.close()


def update_task_status(task_id, status, database_path=None):
    """Update a task status and report whether a matching task was found."""
    connection = get_connection(database_path)

    try:
        cursor = connection.execute("""
            UPDATE tasks
            SET status = ?
            WHERE id = ?
        """, (status, task_id))
        connection.commit()
        return cursor.rowcount > 0
    finally:
        connection.close()


def delete_task_by_id(task_id, database_path=None):
    """Delete a task and report whether a matching task was found."""
    connection = get_connection(database_path)

    try:
        cursor = connection.execute("""
            DELETE FROM tasks
            WHERE id = ?
        """, (task_id,))
        connection.commit()
        return cursor.rowcount > 0
    finally:
        connection.close()
