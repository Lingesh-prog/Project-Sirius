"""Tests for deterministic task command routing."""

import unittest

from app.core.intents import (
    ADD_TASK,
    COMPLETE_TASK,
    DELETE_TASK,
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
