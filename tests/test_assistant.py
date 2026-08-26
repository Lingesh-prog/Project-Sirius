"""Behavior tests for the task-command assistant."""

import tempfile
import unittest
from pathlib import Path

from app.core.assistant import UNKNOWN_COMMAND_MESSAGE, handle_command
from app.storage.database import initialize_database


class AssistantTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "assistant-test.db"
        initialize_database(self.database_path)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def command(self, text):
        return handle_command(text, database_path=self.database_path)

    def test_add_list_complete_and_delete_task(self):
        self.assertEqual(self.command("add task Write tests"), "Task created successfully! ID: 1")
        self.assertIn("[1] Write tests", self.command("list tasks"))
        self.assertIn("Pending", self.command("list tasks"))
        self.assertEqual(self.command("complete task 1"), "Task completed!")
        self.assertIn("Completed", self.command("list tasks"))
        self.assertEqual(self.command("delete task 1"), "Task deleted.")
        self.assertEqual(self.command("list tasks"), "No tasks found.")

    def test_missing_task_and_unknown_command_are_reported(self):
        self.assertEqual(self.command("complete task 99"), "Task not found.")
        self.assertEqual(self.command("delete task 99"), "Task not found.")
        self.assertEqual(self.command("help"), UNKNOWN_COMMAND_MESSAGE)
