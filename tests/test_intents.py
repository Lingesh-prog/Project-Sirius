"""Tests for deterministic command routing."""

import unittest

from app.core.intents import (
    ADD_REMINDER,
    ADD_TASK,
    COMPLETE_REMINDER,
    COMPLETE_TASK,
    DELETE_REMINDER,
    DELETE_TASK,
    LIST_REMINDERS,
    LIST_TASKS,
    UNKNOWN_COMMAND,
    route_command,
)


class IntentRoutingTests(unittest.TestCase):
    def test_add_task_extracts_title(self):
        intent = route_command("  Add   Task   Buy milk  ")
        self.assertEqual(intent.name, ADD_TASK)
        self.assertEqual(intent.title, "Buy milk")

    def test_list_tasks(self):
        self.assertEqual(route_command("list tasks").name, LIST_TASKS)

    def test_complete_task_extracts_id(self):
        intent = route_command("complete task 42")
        self.assertEqual((intent.name, intent.task_id), (COMPLETE_TASK, 42))

    def test_delete_task_extracts_id(self):
        intent = route_command("DELETE TASK 7")
        self.assertEqual((intent.name, intent.task_id), (DELETE_TASK, 7))

    def test_malformed_or_unknown_command_is_unknown(self):
        for command in ("add task", "complete task nope", "show tasks", ""):
            with self.subTest(command=command):
                self.assertEqual(route_command(command).name, UNKNOWN_COMMAND)

    def test_list_reminders(self):
        self.assertEqual(route_command("list reminders").name, LIST_REMINDERS)

    def test_add_reminder_extracts_text_and_datetime(self):
        intent = route_command("add reminder Call dentist at 2026-09-01T10:30")
        self.assertEqual(intent.name, ADD_REMINDER)
        self.assertEqual(intent.text, "Call dentist")
        self.assertEqual(intent.remind_at, "2026-09-01T10:30")

    def test_add_reminder_splits_on_the_last_at_keyword(self):
        intent = route_command("add reminder Meet at cafe at 2026-09-01 10:30")
        self.assertEqual(intent.text, "Meet at cafe")
        self.assertEqual(intent.remind_at, "2026-09-01 10:30")

    def test_complete_reminder_extracts_id(self):
        intent = route_command("complete reminder 42")
        self.assertEqual((intent.name, intent.reminder_id), (COMPLETE_REMINDER, 42))

    def test_delete_reminder_extracts_id(self):
        intent = route_command("DELETE REMINDER 7")
        self.assertEqual((intent.name, intent.reminder_id), (DELETE_REMINDER, 7))

    def test_malformed_reminder_commands_are_unknown(self):
        for command in (
            "add reminder",
            "add reminder at 2026-09-01T10:30",
            "add reminder Call dentist",
            "complete reminder nope",
            "delete reminder nope",
            "show reminders",
        ):
            with self.subTest(command=command):
                self.assertEqual(route_command(command).name, UNKNOWN_COMMAND)
