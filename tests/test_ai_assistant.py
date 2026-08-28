"""Tests for the AI natural-language tool path in the assistant.

The AI client is always a scripted fake, so no test can reach a real
provider over the network.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.ai import AIClient, AIConfigurationError, AIProviderError
from app.core.assistant import UNKNOWN_COMMAND_MESSAGE, handle_command
from app.core.conversation import ConversationContext
from app.storage.database import initialize_database
from app.tools.memory import service as memory_service
from app.tools.reminders import service as reminder_service
from app.tools.tasks import service


def tool_reply(tool, arguments):
    """Return the JSON body the fake AI client answers with."""
    return json.dumps({"tool": tool, "arguments": arguments})


class FakeAIClient(AIClient):
    """Scripted AI client returning canned replies or raising an error."""

    def __init__(self, reply="", error=None, replies=None):
        self.error = error
        self.prompts = []
        self.conversations = []
        self.memories = []
        self._replies = list(replies) if replies is not None else [reply]

    def generate_text(
        self, prompt, system_prompt=None, conversation_history=None, relevant_memories=None
    ):
        self.prompts.append(system_prompt)
        self.conversations.append(conversation_history)
        self.memories.append(relevant_memories)
        if self.error is not None:
            raise self.error
        return self._replies.pop(0)


class AIAssistantTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "ai-assistant-test.db"
        initialize_database(self.database_path)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def command(self, text, ai_client=None, conversation=None):
        return handle_command(
            text,
            database_path=self.database_path,
            ai_client=ai_client,
            conversation=conversation,
        )

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

    def test_followup_uses_previous_context_to_resolve_the_request(self):
        context = ConversationContext()
        client = FakeAIClient(
            replies=[
                tool_reply("tasks.add", {"title": "Finish DSD assignment"}),
                tool_reply("tasks.complete", {"task_id": 1}),
            ]
        )

        self.command(
            "Add a task to finish my DSD assignment",
            ai_client=client,
            conversation=context,
        )
        response = self.command(
            "make it completed", ai_client=client, conversation=context
        )

        self.assertEqual(response, "Task completed!")
        self.assertEqual(
            service.get_tasks(database_path=self.database_path)[0][5], "Completed"
        )
        history = client.conversations[1]
        self.assertIn("Add a task to finish my DSD assignment", history)
        self.assertIn("Task created successfully! ID: 1", history)
        self.assertNotIn("Current request:", history)

    def test_followup_requesting_a_missing_capability_is_declined(self):
        context = ConversationContext()
        client = FakeAIClient(
            replies=[
                tool_reply("tasks.add", {"title": "Finish DSD assignment"}),
                tool_reply(None, {}),  # no existing tool can change a task's priority
            ]
        )

        self.command(
            "Add a task to finish my DSD assignment",
            ai_client=client,
            conversation=context,
        )
        response = self.command(
            "make it high priority", ai_client=client, conversation=context
        )

        self.assertIn("I can only help with tasks and reminders", response)
        self.assertEqual(
            service.get_tasks(database_path=self.database_path)[0][4], "Medium"
        )

    def test_conversation_records_deterministic_exchanges_too(self):
        context = ConversationContext()
        client = self.fake_client("should not be used")

        self.command("add task Direct command", ai_client=client, conversation=context)
        self.assertIn(
            "[1] Direct command", self.command("list tasks", conversation=context)
        )

        self.assertEqual(client.prompts, [])
        self.assertEqual(
            [role for role, _text in context.get_messages()],
            ["user", "assistant", "user", "assistant"],
        )

    def test_destructive_followup_still_requires_confirmation(self):
        context = ConversationContext()
        client = FakeAIClient(
            replies=[
                tool_reply("tasks.add", {"title": "Finish DSD assignment"}),
                tool_reply("tasks.delete", {"task_id": 1}),
            ]
        )

        self.command(
            "Add a task to finish my DSD assignment",
            ai_client=client,
            conversation=context,
        )
        response = self.command(
            "delete it please", ai_client=client, conversation=context
        )

        self.assertIn("confirm delete task 1", response)
        self.assertEqual(len(service.get_tasks(database_path=self.database_path)), 1)

    def test_malformed_reply_with_context_is_handled_safely(self):
        context = ConversationContext()
        client = self.fake_client("no json here")

        response = self.command("do something", ai_client=client, conversation=context)

        self.assertIn("I could not process that request", response)
        self.assertEqual(len(context), 2)

    def test_context_stays_bounded_across_exchanges(self):
        context = ConversationContext(max_messages=2)
        client = FakeAIClient(replies=[tool_reply("tasks.list", {})] * 3)

        self.command("first request", ai_client=client, conversation=context)
        self.command("second request", ai_client=client, conversation=context)
        self.command("third request", ai_client=client, conversation=context)

        history = client.conversations[2]
        self.assertIsNotNone(history)
        self.assertNotIn("first request", history)
        self.assertIn("second request", history)
        self.assertNotIn("third request", history)

    def test_natural_language_updates_a_task(self):
        task_id = service.add_task(
            "DSD assignment", description="Start here", database_path=self.database_path
        )
        client = self.fake_client(
            tool_reply(
                "tasks.update",
                {"task_id": task_id, "title": "Finish DSD assignment", "priority": "high"},
            )
        )

        response = self.command(
            "rename my DSD task to Finish DSD assignment and make it high priority",
            ai_client=client,
        )

        self.assertEqual(response, "Task updated.")
        task = service.get_tasks(database_path=self.database_path)[0]
        self.assertEqual(task[1], "Finish DSD assignment")
        self.assertEqual(task[2], "Start here")
        self.assertEqual(task[4], "High")

    def test_conversation_context_enables_make_it_high_priority(self):
        context = ConversationContext()
        client = FakeAIClient(
            replies=[
                tool_reply("tasks.add", {"title": "Finish DSD assignment"}),
                tool_reply("tasks.update", {"task_id": 1, "priority": "High"}),
            ]
        )

        self.command(
            "Add a task to finish my DSD assignment",
            ai_client=client,
            conversation=context,
        )
        response = self.command(
            "make it high priority", ai_client=client, conversation=context
        )

        self.assertEqual(response, "Task updated.")
        self.assertEqual(
            service.get_tasks(database_path=self.database_path)[0][4], "High"
        )
        history = client.conversations[1]
        self.assertIn("Add a task to finish my DSD assignment", history)
        self.assertIn("Task created successfully! ID: 1", history)

    def test_update_via_ai_requires_at_least_one_field(self):
        task_id = service.add_task("Untouched", database_path=self.database_path)
        client = self.fake_client(tool_reply("tasks.update", {"task_id": task_id}))

        response = self.command("update task 1", ai_client=client)

        self.assertIn("That request is not supported", response)
        self.assertEqual(
            service.get_tasks(database_path=self.database_path)[0][1], "Untouched"
        )

    def test_update_via_ai_rejects_protected_fields(self):
        task_id = service.add_task("Protected", database_path=self.database_path)
        client = self.fake_client(
            tool_reply("tasks.update", {"task_id": task_id, "status": "Completed"})
        )

        response = self.command(
            "mark task 1 as done without completing it", ai_client=client
        )

        self.assertIn("That request is not supported", response)
        self.assertEqual(
            service.get_tasks(database_path=self.database_path)[0][5], "Pending"
        )

    def test_update_via_ai_reports_missing_task(self):
        client = self.fake_client(
            tool_reply("tasks.update", {"task_id": 42, "title": "Ghost"})
        )

        self.assertEqual(
            self.command("rename task 42 to Ghost", ai_client=client), "Task not found."
        )

    def test_natural_language_saves_a_memory(self):
        client = self.fake_client(
            tool_reply("memory.save", {"key": "wifi password", "value": "secret123"})
        )

        response = self.command(
            "remember that my wifi password is secret123", ai_client=client
        )

        self.assertEqual(response, "Memory saved with ID: 1.")
        memory = memory_service.list_memories(self.database_path)[0]
        self.assertEqual(memory[1], "wifi password")
        self.assertEqual(memory[2], "secret123")

    def test_natural_language_lists_memories(self):
        memory_service.save_memory("wifi password", "secret123", self.database_path)
        client = self.fake_client(tool_reply("memory.list", {}))

        response = self.command("what do you remember about me", ai_client=client)

        self.assertIn("[1] wifi password", response)
        self.assertIn("secret123", response)

    def test_natural_language_saving_an_existing_key_updates_it(self):
        memory_service.save_memory("wifi password", "old", self.database_path)
        client = self.fake_client(
            tool_reply("memory.save", {"key": "wifi password", "value": "new"})
        )

        response = self.command(
            "update my wifi password memory to new", ai_client=client
        )

        self.assertEqual(response, "Memory saved with ID: 1.")
        memories = memory_service.list_memories(self.database_path)
        self.assertEqual(len(memories), 1)
        self.assertEqual(memories[0][2], "new")

    def test_memory_delete_requires_confirmation(self):
        memory_service.save_memory(
            "old project notes", "obsolete", self.database_path
        )
        client = self.fake_client(tool_reply("memory.delete", {"memory_id": 1}))

        response = self.command("Forget memory 1", ai_client=client)

        self.assertIn("confirm delete memory 1", response)
        self.assertIn("'old project notes'", response)
        self.assertEqual(len(memory_service.list_memories(self.database_path)), 1)

    def test_confirmed_memory_delete_removes_it(self):
        memory_service.save_memory("old project notes", "obsolete", self.database_path)

        self.assertEqual(self.command("confirm delete memory 1"), "Memory deleted.")
        self.assertEqual(memory_service.list_memories(self.database_path), [])

    def test_unconfirmed_memory_delete_keeps_it(self):
        memory_service.save_memory("keep me", "value", self.database_path)
        client = self.fake_client(tool_reply("memory.delete", {"memory_id": 1}))

        self.command("Forget memory 1", ai_client=client)
        self.command("list tasks")

        self.assertEqual(len(memory_service.list_memories(self.database_path)), 1)

    def test_memory_delete_of_missing_memory_confirms_then_reports(self):
        client = self.fake_client(tool_reply("memory.delete", {"memory_id": 42}))

        response = self.command("forget memory 42", ai_client=client)

        self.assertIn("confirm delete memory 42", response)
        self.assertEqual(self.command("confirm delete memory 42"), "Memory not found.")

    def test_memory_save_with_invalid_arguments_is_not_executed(self):
        client = self.fake_client(
            tool_reply("memory.save", {"key": "   ", "value": "v"})
        )

        response = self.command("remember something", ai_client=client)

        self.assertIn("That request is not supported", response)
        self.assertEqual(memory_service.list_memories(self.database_path), [])

    def test_memory_search_through_ai_returns_relevant_memories(self):
        memory_service.save_memory("wifi password", "secret123", self.database_path)
        memory_service.save_memory("birthday", "May 5", self.database_path)
        client = self.fake_client(tool_reply("memory.search", {"query": "wifi"}))

        response = self.command("what is my wifi password", ai_client=client)

        self.assertIn("[1] wifi password", response)
        self.assertIn("secret123", response)
        self.assertNotIn("birthday", response)

    def test_memory_search_through_ai_handles_no_matches(self):
        client = self.fake_client(
            tool_reply("memory.search", {"query": "nonexistent"})
        )

        response = self.command("what is my passphrase", ai_client=client)

        self.assertEqual(response, "No matching memories found.")

    def test_memory_search_never_modifies_memory(self):
        memory_service.save_memory("wifi password", "secret123", self.database_path)
        client = self.fake_client(tool_reply("memory.search", {"query": "wifi"}))

        self.command("what is my wifi password", ai_client=client)

        memories = memory_service.list_memories(self.database_path)
        self.assertEqual(len(memories), 1)
        self.assertEqual(memories[0][1], "wifi password")
        self.assertEqual(memories[0][2], "secret123")

    def test_memory_search_with_malformed_request_is_handled_safely(self):
        client = self.fake_client(tool_reply("memory.search", {"query": "   "}))

        response = self.command("search my memories", ai_client=client)

        self.assertIn("That request is not supported", response)

    def test_save_then_find_memory_through_the_ai_path(self):
        client = FakeAIClient(
            replies=[
                tool_reply(
                    "memory.save", {"key": "wifi password", "value": "secret123"}
                ),
                tool_reply("memory.search", {"query": "wifi"}),
            ]
        )

        self.command("remember that my wifi password is secret123", ai_client=client)
        response = self.command("what is my wifi password", ai_client=client)

        self.assertIn("secret123", response)

    def test_relevant_memories_reach_the_ai_separated_from_conversation(self):
        context = ConversationContext()
        context.add_user_message("hello")
        context.add_assistant_message("Hi there!")
        memory_service.save_memory("wifi password", "secret123", self.database_path)
        client = self.fake_client(tool_reply("memory.list", {}))

        self.command(
            "what is my wifi password", ai_client=client, conversation=context
        )

        memories = client.memories[0]
        history = client.conversations[0]
        self.assertIn("wifi password: secret123", memories)
        self.assertNotIn("Recent conversation:", memories)
        self.assertIsNotNone(history)
        self.assertNotIn("Relevant stored memories:", history)
        self.assertNotIn("secret123", history)

    def test_deterministic_commands_do_not_search_memory_or_call_the_ai(self):
        memory_service.save_memory("wifi password", "secret123", self.database_path)
        context = ConversationContext()
        client = self.fake_client("should not be used")

        with mock.patch.object(memory_service, "search_memories") as search:
            self.command("list tasks", ai_client=client, conversation=context)

        search.assert_not_called()
        self.assertEqual(client.prompts, [])

    def test_ai_requests_never_create_memory_automatically(self):
        client = FakeAIClient(
            replies=[tool_reply("tasks.list", {}), "no json here"]
        )

        self.command("what tasks do I have", ai_client=client)
        self.command("hello there", ai_client=client)

        self.assertEqual(memory_service.list_memories(self.database_path), [])