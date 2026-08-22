from datetime import datetime
from database import get_connection


VALID_PRIORITIES = ["Low", "Medium", "High"]


def add_task(title, description="", due_date=None, priority="Medium"):
    if priority not in VALID_PRIORITIES:
        raise ValueError("Priority must be Low, Medium, or High.")

    created_at = datetime.now().isoformat(timespec="seconds")

    connection = get_connection()

    cursor = connection.execute("""
        INSERT INTO tasks
        (title, description, due_date, priority, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        title,
        description,
        due_date,
        priority,
        "Pending",
        created_at
    ))

    connection.commit()

    task_id = cursor.lastrowid

    connection.close()

    return task_id


def get_tasks():
    connection = get_connection()

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

    tasks = cursor.fetchall()

    connection.close()

    return tasks


def complete_task(task_id):
    connection = get_connection()

    cursor = connection.execute("""
        UPDATE tasks
        SET status = 'Completed'
        WHERE id = ?
    """, (task_id,))

    connection.commit()

    updated = cursor.rowcount > 0

    connection.close()

    return updated


def delete_task(task_id):
    connection = get_connection()

    cursor = connection.execute("""
        DELETE FROM tasks
        WHERE id = ?
    """, (task_id,))

    connection.commit()

    deleted = cursor.rowcount > 0

    connection.close()

    return deleted