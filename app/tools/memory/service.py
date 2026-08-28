"""Memory business logic for the SIRIUS memory tool.

Memory is always explicit: only a memory.save call (via the memory.save AI
tool) writes anything. SIRIUS never extracts or profiles conversation
content on its own.
"""

from datetime import datetime

from app.tools.memory import repository


def save_memory(key, value, database_path=None):
    """Create or update a memory and return its identifier.

    Saving an existing key updates its value and updated_at instead of
    creating a duplicate.
    """
    key = _validate_text("key", key)
    value = _validate_text("value", value)
    now = datetime.now().isoformat(timespec="seconds")

    existing = repository.find_memory_by_key(key, database_path=database_path)
    if existing is not None:
        repository.update_memory_value(
            key, value, updated_at=now, database_path=database_path
        )
        return existing[0]

    return repository.insert_memory(
        key=key,
        value=value,
        created_at=now,
        updated_at=now,
        database_path=database_path,
    )


def list_memories(database_path=None):
    """Return all memories ordered by their key."""
    return repository.fetch_memories(database_path=database_path)


def search_memories(query, database_path=None):
    """Return memories whose key or value contains the query.

    Matching is a case-insensitive substring search performed by the
    repository with parameterized SQL. Read-only; never modifies memory.
    """
    query = _validate_text("query", query)

    return repository.search_memories(query, database_path=database_path)


def delete_memory(memory_id, database_path=None):
    """Delete a matching memory and report whether it was found."""
    _validate_memory_id(memory_id)

    return repository.delete_memory_by_id(memory_id, database_path=database_path)


def _validate_text(field_name, text):
    if not isinstance(text, str) or not text.strip():
        raise ValueError(f"Memory {field_name} cannot be empty.")

    return text.strip()


def _validate_memory_id(memory_id):
    if (
        not isinstance(memory_id, int)
        or isinstance(memory_id, bool)
        or memory_id < 1
    ):
        raise ValueError("Memory id must be a positive whole number.")