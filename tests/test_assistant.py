"""Behavior tests for the Sirius command assistant."""

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

    def test_add_list_complete_and_delete_reminder(self):
        self.assertEqual(
            self.command("add reminder Call dentist at 2026-09-01T10:30"),
            "Reminder created successfully! ID: 1",
        )
        listed = self.command("list reminders")
        self.assertIn("[1] Call dentist", listed)
        self.assertIn("Pending", listed)
        self.assertEqual(self.command("complete reminder 1"), "Reminder completed!")
        self.assertIn("Completed", self.command("list reminders"))
        self.assertEqual(self.command("delete reminder 1"), "Reminder deleted.")
        self.assertEqual(self.command("list reminders"), "No reminders found.")

    def test_missing_reminder_is_reported(self):
        self.assertEqual(self.command("complete reminder 99"), "Reminder not found.")
        self.assertEqual(self.command("delete reminder 99"), "Reminder not found.")

    def test_add_reminder_with_invalid_time_is_reported_not_raised(self):
        self.assertEqual(
            self.command("add reminder Take a break at 2026-13-99T99:00"),
            "Reminder not created. remind_at must be a valid ISO datetime.",
        )
