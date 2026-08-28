"""Tests for deterministic memory pre-retrieval for AI requests."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.core import memory_context
from app.storage.database import initialize_database
from app.tools.memory import service as memory_service


class CollectRelevantMemoriesTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = (
            Path(self.temporary_directory.name) / "memory-context-test.db"
        )
        initialize_database(self.database_path)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_requests_without_usable_tokens_search_nothing(self):
        with mock.patch.object(memory_service, "search_memories") as search:
            result = memory_context.collect_relevant_memories(
                "ok? go", database_path=self.database_path
            )

        self.assertEqual(result, [])
        search.assert_not_called()

    def test_words_shorter_than_four_characters_are_ignored(self):
        with mock.patch.object(memory_service, "search_memories") as search:
            result = memory_context.collect_relevant_memories(
                "ok the is an", database_path=self.database_path
            )

        self.assertEqual(result, [])
        search.assert_not_called()

    def test_non_text_requests_search_nothing(self):
        with mock.patch.object(memory_service, "search_memories") as search:
            result = memory_context.collect_relevant_memories(
                None, database_path=self.database_path
            )

        self.assertEqual(result, [])
        search.assert_not_called()

    def test_matching_memories_are_returned(self):
        memory_service.save_memory("wifi password", "secret123", self.database_path)

        result = memory_context.collect_relevant_memories(
            "what is my wifi password", database_path=self.database_path
        )

        self.assertEqual([memory[1] for memory in result], ["wifi password"])

    def test_memories_are_ranked_by_number_of_matching_words(self):
        memory_service.save_memory(
            "wifi password", "secret123", self.database_path
        )
        memory_service.save_memory(
            "password policy", "rotate yearly", self.database_path
        )
        memory_service.save_memory("birthday", "May 5", self.database_path)

        result = memory_context.collect_relevant_memories(
            "what is my wifi password", database_path=self.database_path
        )

        # "wifi" and "password" both match the first memory; only "password"
        # matches the second. Irrelevant memories are excluded entirely.
        self.assertEqual(
            [memory[1] for memory in result],
            ["wifi password", "password policy"],
        )

    def test_at_most_three_memories_are_returned(self):
        for index in range(5):
            memory_service.save_memory(
                f"note {index}", "shared keyword here", self.database_path
            )

        result = memory_context.collect_relevant_memories(
            "anything about the shared keyword", database_path=self.database_path
        )

        self.assertEqual(len(result), memory_context.MAX_MEMORY_CONTEXT_MEMORIES)

    def test_render_memories_formats_key_value_lines(self):
        self.assertIsNone(memory_context.render_memories([]))
        self.assertIsNone(memory_context.render_memories(None))

        rendered = memory_context.render_memories(
            [(1, "wifi password", "secret123", "2026-01-01", "2026-01-01")]
        )

        self.assertEqual(rendered, "wifi password: secret123")

    def test_render_memories_handles_multiple_rows(self):
        rendered = memory_context.render_memories(
            [
                (1, "a key", "a value", "", ""),
                (2, "b key", "b value", "", ""),
            ]
        )

        self.assertEqual(rendered, "a key: a value\nb key: b value")