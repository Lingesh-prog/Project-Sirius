"""Tests for the AI natural-language tool path in the assistant.

The AI client is always a scripted fake, so no test can reach a real
provider over the network.
"""

import json
import tempfile
import unittest
from pathlib import Path

from app.ai import AIClient, AIConfigurationError, AIProviderError
from app.core.assistant import UNKNOWN_COMMAND_MESSAGE, handle_command
from app.storage.database import initialize_database
from app.tools.reminders import service as reminder_service
from app.tools.tasks import service


def tool_reply(tool, arguments):
    """Return the JSON body the fake AI client answers with."""
    return json.dumps({"tool": tool, "arguments": arguments})


class FakeAIClient(AIClient):
    """Scripted AI client returning a canned reply or raising an error."""

    def __init__(self, reply="", error=None):
        self.reply = reply
        self.error = error
        self.prompts = []

    def generate_text(self, prompt, system_prompt=None):
        self.prompts.append(system_prompt)
        if self.error is not None:
            raise self.error
        return self.reply


class AIAssistantTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "ai-assistant-test.db"
        initialize_database(self.database_path)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def command(self, text, ai_client=None):
        return handle_command(text, database_path=self.database_path, ai_client=ai_client)

    def fake_client(self, reply):
        return FakeAIClient(reply=reply)

    def test_natural_language_creates_a_task(self):
        client = self.fake_client(
            tool_reply("tasks.add", {"title": "Finish DSD assignment", "priority": "high"})
        )

        response = self.command(
            "Add a high priority task to finish my DSD assignment", ai_client=client
        )

        self.assertEqual(response, "Task created successfully! ID: 1")
        task = service.get_tasks(database_path=self.database_path)[0]
        self.assertEqual(task[1], "Finish DSD assignment")
        self.assertEqual(task[4], "High")

    def test_natural_language_lists_tasks(self):
        service.add_task("Buy milk", database_path=self.database_path)
        client = self.fake_client(tool_reply("tasks.list", {}))

        response = self.command("Show my tasks", ai_client=client)

        self.assertIn("[1] Buy milk", response)

    def test_natural_language_completes_a_task(self):
        task_id = service.add_task("Write tests", database_path=self.database_path)
        client = self.fake_client(tool_reply("tasks.complete", {"task_id": str(task_id)}))

        self.assertEqual(
            self.command("please mark the Write tests task as done", ai_client=client),
            "Task completed!",
        )
        self.assertEqual(
            service.get_tasks(database_path=self.database_path)[0][5], "Completed"
        )

    def test_natural_language_creates_a_reminder(self):
        client = self.fake_client(
            tool_reply("reminders.add", {"text": "Call the dentist", "remind_at": "2026-09-01T10:00"})
        )

        response = self.command(
            "Remind me to call the dentist tomorrow at 10:00", ai_client=client
        )

        self.assertEqual(response, "Reminder created successfully! ID: 1")
        reminder = reminder_service.list_reminders(self.database_path)[0]
        self.assertEqual(reminder[1], "Call the dentist")
        self.assertEqual(reminder[2], "2026-09-01T10:00")

    def test_natural_language_lists_reminders(self):
        reminder_service.create_reminder(
            "Call dentist", "2026-09-01T10:00", self.database_path
        )
        client = self.fake_client(tool_reply("reminders.list", {}))

        response = self.command("What reminders do I have", ai_client=client)

        self.assertIn("[1] Call dentist", response)

    def test_invalid_tool_arguments_are_not_executed(self):
        client = self.fake_client(
            tool_reply("tasks.add", {"title": "X", "priority": "Urgent"})
        )

        response = self.command("Make an urgent task", ai_client=client)

        self.assertIn("That request is not supported", response)
        self.assertEqual(service.get_tasks(database_path=self.database_path), [])

    def test_invalid_reminder_time_is_not_executed(self):
        client = self.fake_client(
            tool_reply("reminders.add", {"text": "Call dentist", "remind_at": "tomorrow"})
        )

        response = self.command("Remind me tomorrow", ai_client=client)

        self.assertIn("That request is not supported", response)
        self.assertEqual(reminder_service.list_reminders(self.database_path), [])

    def test_unknown_tool_is_not_executed(self):
        client = self.fake_client(tool_reply("tasks.drop_all", {}))

        response = self.command("Wipe everything", ai_client=client)

        self.assertIn("That request is not supported", response)
        self.assertIn("tasks.drop_all", response)
        self.assertEqual(service.get_tasks(database_path=self.database_path), [])

    def test_destructive_task_delete_requires_confirmation(self):
        task_id = service.add_task("Delete me", database_path=self.database_path)
        client = self.fake_client(tool_reply("tasks.delete", {"task_id": task_id}))

        response = self.command("please remove the Delete me task", ai_client=client)

        self.assertIn("confirm delete task 1", response)
        self.assertIn("'Delete me'", response)
        self.assertEqual(len(service.get_tasks(database_path=self.database_path)), 1)

    def test_confirmed_task_delete_removes_the_task(self):
        service.add_task("Delete me", database_path=self.database_path)

        self.assertEqual(self.command("confirm delete task 1"), "Task deleted.")
        self.assertEqual(service.get_tasks(database_path=self.database_path), [])

    def test_unconfirmed_destructive_request_keeps_the_task(self):
        task_id = service.add_task("Keep me", database_path=self.database_path)
        client = self.fake_client(tool_reply("tasks.delete", {"task_id": task_id}))

        self.command("please delete the Keep me task", ai_client=client)
        self.command("list tasks")

        self.assertEqual(len(service.get_tasks(database_path=self.database_path)), 1)

    def test_destructive_reminder_delete_requires_confirmation(self):
        reminder_service.create_reminder(
            "Call dentist", "2026-09-01T10:00", self.database_path
        )
        client = self.fake_client(tool_reply("reminders.delete", {"reminder_id": 1}))

        response = self.command("please remove my dentist reminder", ai_client=client)

        self.assertIn("confirm delete reminder 1", response)
        self.assertEqual(len(reminder_service.list_reminders(self.database_path)), 1)

    def test_confirmed_reminder_delete_removes_the_reminder(self):
        reminder_service.create_reminder(
            "Call dentist", "2026-09-01T10:00", self.database_path
        )

        self.assertEqual(self.command("confirm delete reminder 1"), "Reminder deleted.")
        self.assertEqual(reminder_service.list_reminders(self.database_path), [])

    def test_missing_task_on_confirmation_is_reported(self):
        self.assertEqual(self.command("confirm delete task 99"), "Task not found.")

    def test_requests_outside_sirius_are_declined(self):
        client = self.fake_client(tool_reply(None, {}))

        response = self.command("What is the weather", ai_client=client)

        self.assertIn("I can only help with tasks and reminders", response)

    def test_provider_error_is_reported_gracefully(self):
        client = FakeAIClient(error=AIProviderError("quota exceeded"))

        response = self.command("Show my tasks", ai_client=client)

        self.assertIn("AI assistant is unavailable", response)
        self.assertIn("quota exceeded", response)

    def test_configuration_error_is_reported_gracefully(self):
        client = FakeAIClient(error=AIConfigurationError("missing key"))

        response = self.command("Show my tasks", ai_client=client)

        self.assertIn("AI assistant is unavailable", response)

    def test_malformed_ai_responses_are_reported(self):
        for reply in (
            "Sorry, I cannot help with that.",
            "not json at all",
            '{"tool": 123, "arguments": {}}',
        ):
            client = self.fake_client(reply)
            with self.subTest(reply=reply):
                response = self.command("Do a thing", ai_client=client)
                self.assertIn("I could not process that request", response)

    def test_ai_prompt_contains_catalog_and_current_date(self):
        client = self.fake_client(tool_reply("tasks.list", {}))

        self.command("show tasks", ai_client=client)

        system_prompt = client.prompts[0]
        self.assertIn("tasks.add", system_prompt)
        self.assertIn("reminders.delete", system_prompt)
        self.assertIn("Current date:", system_prompt)

    def test_deterministic_commands_bypass_the_ai_client(self):
        client = self.fake_client("should not be used")

        self.assertEqual(
            self.command("add task Direct command"), "Task created successfully! ID: 1"
        )
        self.assertIn("[1] Direct command", self.command("list tasks"))
        self.assertEqual(self.command("complete task 1"), "Task completed!")
        self.assertEqual(self.command("delete task 1"), "Task deleted.")

        self.assertEqual(client.prompts, [])

    def test_unknown_command_without_ai_client_keeps_existing_message(self):
        self.assertEqual(self.command("gibberish"), UNKNOWN_COMMAND_MESSAGE)

    def test_missing_task_on_ai_complete_is_reported(self):
        client = self.fake_client(tool_reply("tasks.complete", {"task_id": 42}))

        self.assertEqual(
            self.command("please complete task number 42", ai_client=client),
            "Task not found.",
        )