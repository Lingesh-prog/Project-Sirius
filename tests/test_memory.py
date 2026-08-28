"""Service and persistence tests for the SIRIUS memory tool."""

import tempfile
import unittest
from pathlib import Path

from app.storage.database import get_connection, initialize_database
from app.tools.memory import service


class MemoryServiceTests(unittest.TestCase):
    """Exercise memory behavior through disposable SQLite databases."""

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "sirius-test.db"
        initialize_database(self.database_path)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def save_memory(self, key="Test key", value="Test value"):
        """Create a memory in this test's disposable database."""
        return service.save_memory(key, value, self.database_path)

    def test_create_memory_preserves_values_and_sets_timestamps(self):
        memory_id = self.save_memory("wifi password", "correct-horse-battery")

        memory = service.list_memories(self.database_path)[0]

        self.assertEqual(memory[0], memory_id)
        self.assertEqual(memory[1], "wifi password")
        self.assertEqual(memory[2], "correct-horse-battery")
        self.assertTrue(memory[3])
        self.assertTrue(memory[4])

    def test_list_memories_is_empty_for_new_database(self):
        self.assertEqual(service.list_memories(self.database_path), [])

    def test_list_memories_orders_by_key(self):
        self.save_memory("b key", "second")
        self.save_memory("a key", "first")

        self.assertEqual(
            [memory[1] for memory in service.list_memories(self.database_path)],
            ["a key", "b key"],
        )

    def test_saving_an_existing_key_updates_without_duplicating(self):
        memory_id = self.save_memory("preference", "old value")

        updated_id = self.save_memory("preference", "new value")

        memories = service.list_memories(self.database_path)
        self.assertEqual(len(memories), 1)
        self.assertEqual(updated_id, memory_id)
        self.assertEqual(memories[0][0], memory_id)
        self.assertEqual(memories[0][2], "new value")

    def test_saving_an_existing_key_updates_updated_at_not_created_at(self):
        self.save_memory("preference", "old value")
        original = service.list_memories(self.database_path)[0]

        self.save_memory("preference", "new value")
        updated = service.list_memories(self.database_path)[0]

        self.assertEqual(updated[3], original[3])
        self.assertGreaterEqual(updated[4], original[4])

    def test_keys_and_values_are_stripped(self):
        self.save_memory("  spaced key  ", "  spaced value  ")

        memory = service.list_memories(self.database_path)[0]

        self.assertEqual(memory[1], "spaced key")
        self.assertEqual(memory[2], "spaced value")

    def test_empty_key_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Memory key cannot be empty"):
            self.save_memory("", "value")

    def test_whitespace_key_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Memory key cannot be empty"):
            self.save_memory("   ", "value")

    def test_empty_value_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Memory value cannot be empty"):
            self.save_memory("key", "")

    def test_whitespace_value_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Memory value cannot be empty"):
            self.save_memory("key", "   ")

    def test_delete_memory_removes_existing_memory(self):
        memory_id = self.save_memory("temp", "value")

        self.assertTrue(service.delete_memory(memory_id, self.database_path))
        self.assertEqual(service.list_memories(self.database_path), [])

    def test_delete_missing_memory_returns_false(self):
        self.assertFalse(service.delete_memory(9999, self.database_path))

    def test_invalid_memory_id_is_rejected(self):
        for memory_id in (0, -1, "3", None, True, 1.5):
            with self.subTest(memory_id=memory_id):
                with self.assertRaisesRegex(ValueError, "positive whole number"):
                    service.delete_memory(memory_id, self.database_path)

    def test_memory_persists_after_connection_is_reopened(self):
        memory_id = self.save_memory("persistent", "kept value")

        connection = get_connection(self.database_path)
        connection.close()

        memories = service.list_memories(self.database_path)
        self.assertEqual([memory[0] for memory in memories], [memory_id])
        self.assertEqual(memories[0][2], "kept value")