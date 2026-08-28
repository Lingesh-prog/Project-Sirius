"""SQLite persistence operations for SIRIUS memories."""

from app.storage.database import get_connection


def insert_memory(key, value, created_at, updated_at, database_path=None):
    """Insert a memory and return its database identifier."""
    connection = get_connection(database_path)

    try:
        cursor = connection.execute("""
            INSERT INTO memories (key, value, created_at, updated_at)
            VALUES (?, ?, ?, ?)
        """, (key, value, created_at, updated_at))
        connection.commit()
        return cursor.lastrowid
    finally:
        connection.close()


def find_memory_by_key(key, database_path=None):
    """Return the memory with this key, or None when it does not exist."""
    connection = get_connection(database_path)

    try:
        cursor = connection.execute("""
            SELECT id, key, value, created_at, updated_at
            FROM memories
            WHERE key = ?
        """, (key,))
        return cursor.fetchone()
    finally:
        connection.close()


def update_memory_value(key, value, updated_at, database_path=None):
    """Update the value and updated_at of the memory with this key."""
    connection = get_connection(database_path)

    try:
        cursor = connection.execute("""
            UPDATE memories
            SET value = ?, updated_at = ?
            WHERE key = ?
        """, (value, updated_at, key))
        connection.commit()
        return cursor.rowcount > 0
    finally:
        connection.close()


def fetch_memories(database_path=None):
    """Return all memories ordered by their key."""
    connection = get_connection(database_path)

    try:
        cursor = connection.execute("""
            SELECT id, key, value, created_at, updated_at
            FROM memories
            ORDER BY key ASC, id ASC
        """)
        return cursor.fetchall()
    finally:
        connection.close()


def search_memories(query, database_path=None):
    """Return memories whose key or value contains *query* (case-insensitive).

    The query is matched as a literal substring: LIKE wildcards inside the
    query are escaped and the pattern is always a bound parameter, never
    concatenated into the SQL text. Results are ordered deterministically
    by key.
    """
    connection = get_connection(database_path)

    try:
        pattern = f"%{_escape_like_pattern(query)}%"
        cursor = connection.execute("""
            SELECT id, key, value, created_at, updated_at
            FROM memories
            WHERE key LIKE ? ESCAPE '\\' OR value LIKE ? ESCAPE '\\'
            ORDER BY key ASC, id ASC
        """, (pattern, pattern))
        return cursor.fetchall()
    finally:
        connection.close()


def _escape_like_pattern(query):
    """Escape LIKE wildcards so the query matches as literal text."""
    return (
        query.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


def delete_memory_by_id(memory_id, database_path=None):
    """Delete a memory and report whether a matching memory was found."""
    connection = get_connection(database_path)

    try:
        cursor = connection.execute("""
            DELETE FROM memories
            WHERE id = ?
        """, (memory_id,))
        connection.commit()
        return cursor.rowcount > 0
    finally:
        connection.close()