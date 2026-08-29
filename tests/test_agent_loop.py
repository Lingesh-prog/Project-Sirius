"""Tests for the Module 3.1 multi-step agent reasoning and execution loop.

The AI client is always a scripted fake, so no test can reach a real
provider over the network.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.ai import AIClient, AIProviderError
from app.core.agent.loop import (
    DEFAULT_MAX_STEPS,
    AgentLoop,
    AgentStep,
    run_agent_loop,
)
from app.core.context_assembly import assemble_context
from app.core.response_handler import EMPTY_RESPONSE_MESSAGE, UNEXPECTED_ERROR_MESSAGE
from app.core.tool_registry import SafetyTier, Tool, ToolRegistry
from app.core.tools import TOOL_ARGUMENT_SPECS, TOOL_TASKS_LIST, build_tool_catalog
from app.storage.database import initialize_database
from app.tools.memory import service as memory_service
from app.tools.reminders import service as reminder_service
from app.tools.tasks import service


def tool_json(tool, arguments=None):
    """Return the JSON body a scripted AI client answers with."""
    return json.dumps({"tool": tool, "arguments": arguments or {}})


def make_context(request, conversation=None, memories=None):
    """Assemble the same structured context the assistant builds."""
    return assemble_context(
        request,
        conversation_history=conversation,
        relevant_memories=memories,
        tool_catalog=build_tool_catalog(),
        today="2026-08-29 (Saturday)",
    )


class ScriptedAgentClient(AIClient):
    """Scripted fake client: one canned reply per call, or a raised error."""

    def __init__(self, replies=(), error=None):
        self.replies = list(replies)
        self.error = error
        self.calls = 0
        self.prompts = []
        self.system_prompts = []
        self.conversations = []
        self.memories = []

    def generate_text(
        self, prompt, system_prompt=None, conversation_history=None, relevant_memories=None
    ):
        self.calls += 1
        self.prompts.append(prompt)
        self.system_prompts.append(system_prompt)
        self.conversations.append(conversation_history)
        self.memories.append(relevant_memories)
        if self.error is not None:
            raise self.error
        return self.replies.pop(0)


class AgentLoopTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "agent-loop-test.db"
        initialize_database(self.database_path)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def make_loop(self, client, **overrides):
        options = {"ai_client": client, "database_path": self.database_path}
        options.update(overrides)
        return AgentLoop(**options)

    # ------------------------------------------------------------------
    # Response contract
    # ------------------------------------------------------------------

    def test_natural_language_reply_ends_the_loop_without_tool_execution(self):
        client = ScriptedAgentClient(replies=["You have no tasks yet."])
        loop = self.make_loop(client)

        response = loop.run(make_context("What should I do today?"))

        self.assertEqual(response, "You have no tasks yet.")
        self.assertEqual(client.calls, 1)
        self.assertEqual([step.is_final for step in loop.steps], [True])
        self.assertEqual(service.get_tasks(database_path=self.database_path), [])

    def test_state_modifying_tool_executes_once_and_returns_the_observation(self):
        client = ScriptedAgentClient(
            replies=[tool_json("tasks.add", {"title": "Buy milk"})]
        )
        loop = self.make_loop(client)

        response = loop.run(make_context("Add a task to buy milk"))

        self.assertEqual(response, "Task created successfully! ID: 1")
        self.assertEqual(client.calls, 1)
        self.assertEqual([step.tool_name for step in loop.steps], ["tasks.add"])
        self.assertEqual(
            service.get_tasks(database_path=self.database_path)[0][1], "Buy milk"
        )

    def test_read_only_observation_is_fed_back_to_produce_a_final_answer(self):
        service.add_task("Buy milk", database_path=self.database_path)
        client = ScriptedAgentClient(
            replies=[tool_json("tasks.list"), "You have one task: Buy milk."]
        )
        loop = self.make_loop(client)

        response = loop.run(make_context("What are my tasks?"))

        self.assertEqual(response, "You have one task: Buy milk.")
        self.assertEqual(client.calls, 2)
        self.assertEqual(
            [(step.tool_name, step.is_final) for step in loop.steps],
            [("tasks.list", False), (None, True)],
        )
        follow_up_prompt = client.prompts[1]
        self.assertIn("Current request: What are my tasks?", follow_up_prompt)
        self.assertIn("Previous tool actions:", follow_up_prompt)
        self.assertIn("Step 1: Called tasks.list", follow_up_prompt)
        self.assertIn("[1] Buy milk", follow_up_prompt)

    def test_read_only_tools_can_chain_across_steps(self):
        service.add_task("Buy milk", database_path=self.database_path)
        reminder_service.create_reminder(
            "Call dentist", "2026-09-01T10:00", self.database_path
        )
        client = ScriptedAgentClient(
            replies=[
                tool_json("tasks.list"),
                tool_json("reminders.list"),
                "You have 1 task and 1 reminder.",
            ]
        )
        loop = self.make_loop(client)

        response = loop.run(make_context("Summarize my tasks and reminders"))

        self.assertEqual(response, "You have 1 task and 1 reminder.")
        self.assertEqual(client.calls, 3)
        self.assertEqual(
            [step.tool_name for step in loop.steps],
            ["tasks.list", "reminders.list", None],
        )
        self.assertIn("Called tasks.list", client.prompts[2])
        self.assertIn("Called reminders.list", client.prompts[2])

    def test_requests_outside_sirius_are_declined(self):
        client = ScriptedAgentClient(replies=[tool_json(None)])
        loop = self.make_loop(client)

        response = loop.run(make_context("What is the weather"))

        self.assertEqual(
            response, "I can only help with tasks and reminders right now."
        )

    # ------------------------------------------------------------------
    # Safety boundaries
    # ------------------------------------------------------------------

    def test_destructive_tool_halts_the_loop_and_never_executes(self):
        task_id = service.add_task("Delete me", database_path=self.database_path)
        client = ScriptedAgentClient(
            replies=[
                tool_json("tasks.delete", {"task_id": task_id}),
                "this reply must never be consumed",
            ]
        )
        confirmation = mock.Mock(return_value="Please confirm the deletion.")
        loop = self.make_loop(client, build_confirmation_fn=confirmation)

        response = loop.run(make_context("Delete the task"))

        self.assertEqual(response, "Please confirm the deletion.")
        confirmation.assert_called_once_with(
            "tasks.delete", {"task_id": task_id}, self.database_path
        )
        self.assertEqual(client.calls, 1)
        self.assertEqual(client.replies, ["this reply must never be consumed"])
        self.assertEqual(len(service.get_tasks(database_path=self.database_path)), 1)
        self.assertEqual(loop.steps, [])

    def test_destructive_reminder_delete_halts_for_confirmation(self):
        reminder_service.create_reminder(
            "Call dentist", "2026-09-01T10:00", self.database_path
        )
        client = ScriptedAgentClient(
            replies=[tool_json("reminders.delete", {"reminder_id": 1})]
        )
        confirmation = mock.Mock(return_value="Please confirm.")
        loop = self.make_loop(client, build_confirmation_fn=confirmation)

        response = loop.run(make_context("Remove my reminder"))

        self.assertEqual(response, "Please confirm.")
        confirmation.assert_called_once_with(
            "reminders.delete", {"reminder_id": 1}, self.database_path
        )
        self.assertEqual(len(reminder_service.list_reminders(self.database_path)), 1)

    def test_destructive_tool_without_a_confirmation_callback_is_refused(self):
        task_id = service.add_task("Keep me", database_path=self.database_path)
        client = ScriptedAgentClient(
            replies=[tool_json("tasks.delete", {"task_id": task_id})]
        )
        loop = self.make_loop(client, build_confirmation_fn=None)

        response = loop.run(make_context("Delete the task"))

        self.assertEqual(
            response, "Destructive tool 'tasks.delete' requires confirmation."
        )
        self.assertEqual(len(service.get_tasks(database_path=self.database_path)), 1)

    def test_unknown_tools_are_rejected_without_execution(self):
        client = ScriptedAgentClient(replies=[tool_json("tasks.drop_all")])
        loop = self.make_loop(client)

        response = loop.run(make_context("Wipe everything"))

        self.assertIn("That request is not supported", response)
        self.assertIn("tasks.drop_all", response)
        self.assertEqual(service.get_tasks(database_path=self.database_path), [])

    def test_invalid_arguments_are_rejected_before_execution(self):
        client = ScriptedAgentClient(
            replies=[tool_json("tasks.add", {"title": "X", "priority": "Urgent"})]
        )
        loop = self.make_loop(client)

        response = loop.run(make_context("Make an urgent task"))

        self.assertIn("That request is not supported", response)
        self.assertEqual(service.get_tasks(database_path=self.database_path), [])

    def test_custom_registry_restricts_the_available_tools(self):
        executed = []
        registry = ToolRegistry()
        registry.register(
            Tool(
                name=TOOL_TASKS_LIST,
                description="Probe replacement for tasks.list.",
                argument_spec=TOOL_ARGUMENT_SPECS[TOOL_TASKS_LIST],
                safety_tier=SafetyTier.READ_ONLY,
                executor=lambda arguments, database_path=None: executed.append("listed")
                or "no tasks at all",
            )
        )
        client = ScriptedAgentClient(
            replies=[
                tool_json("reminders.list"),
                tool_json("tasks.list"),
                "nothing to show",
            ]
        )
        loop = AgentLoop(ai_client=client, tool_registry=registry, database_path=None)

        self.assertIn(
            "That request is not supported: Unknown tool 'reminders.list'.",
            loop.run(make_context("show reminders")),
        )
        self.assertEqual(loop.run(make_context("show tasks")), "nothing to show")
        self.assertEqual(executed, ["listed"])

    # ------------------------------------------------------------------
    # Reliability and error handling
    # ------------------------------------------------------------------

    def test_multiple_tool_requests_are_rejected(self):
        client = ScriptedAgentClient(
            replies=[
                '{"tool": "tasks.add", "arguments": {"title": "One"}}\n'
                '{"tool": "tasks.add", "arguments": {"title": "Two"}}'
            ]
        )
        loop = self.make_loop(client)

        response = loop.run(make_context("Add two tasks"))

        self.assertIn("I could not process that request", response)
        self.assertIn("only one action is allowed", response)

    def test_malformed_tool_requests_are_reported(self):
        client = ScriptedAgentClient(
            replies=['```json\n{"tool": "tasks.add", "arguments": {broken\n```']
        )
        loop = self.make_loop(client)

        response = loop.run(make_context("Do a thing"))

        self.assertIn("I could not process that request", response)

    def test_empty_first_response_is_reported_cleanly(self):
        client = ScriptedAgentClient(replies=["   "])
        loop = self.make_loop(client)

        self.assertEqual(loop.run(make_context("hello?")), EMPTY_RESPONSE_MESSAGE)

    def test_empty_follow_up_after_a_read_only_step_returns_the_observation(self):
        service.add_task("Buy milk", database_path=self.database_path)
        client = ScriptedAgentClient(replies=[tool_json("tasks.list"), "   "])
        loop = self.make_loop(client)

        response = loop.run(make_context("What are my tasks?"))

        self.assertIn("[1] Buy milk", response)

    def test_provider_error_on_the_first_step_is_reported_gracefully(self):
        client = ScriptedAgentClient(error=AIProviderError("quota exceeded"))
        loop = self.make_loop(client)

        response = loop.run(make_context("Show tasks"))

        self.assertIn("AI assistant is unavailable right now", response)
        self.assertIn("quota exceeded", response)

    def test_unexpected_error_on_the_first_step_leaks_no_details(self):
        client = ScriptedAgentClient(error=RuntimeError("socket exploded"))
        loop = self.make_loop(client)

        response = loop.run(make_context("Show tasks"))

        self.assertEqual(response, UNEXPECTED_ERROR_MESSAGE)
        self.assertNotIn("socket", response)

    def test_exhausted_single_reply_script_returns_the_last_observation(self):
        # Compatibility: scripted single-turn fakes raise IndexError when the
        # loop asks for a follow-up step; the loop then degrades gracefully to
        # the observation it already collected.
        service.add_task("Buy milk", database_path=self.database_path)
        client = ScriptedAgentClient(replies=[tool_json("tasks.list")])
        loop = self.make_loop(client)

        response = loop.run(make_context("What are my tasks?"))

        self.assertIn("[1] Buy milk", response)
        self.assertEqual(client.calls, 2)

    # ------------------------------------------------------------------
    # Step bounds and bookkeeping
    # ------------------------------------------------------------------

    def test_max_steps_bounds_the_loop(self):
        service.add_task("Buy milk", database_path=self.database_path)
        client = ScriptedAgentClient(
            replies=[
                tool_json("tasks.list"),
                tool_json("memory.list"),
                "unused final answer",
            ]
        )
        loop = self.make_loop(client, max_steps=2)

        response = loop.run(make_context("What are my tasks?"))

        self.assertEqual(response, "No memories found.")
        self.assertEqual(client.calls, 2)
        self.assertEqual(client.replies, ["unused final answer"])
        self.assertEqual(
            [step.tool_name for step in loop.steps], ["tasks.list", "memory.list"]
        )

    def test_default_max_steps_is_five(self):
        self.assertEqual(DEFAULT_MAX_STEPS, 5)

    def test_max_steps_must_be_a_positive_whole_number(self):
        for bad_max_steps in (0, -1, 2.5, "3", True):
            with self.subTest(max_steps=bad_max_steps):
                with self.assertRaises(ValueError):
                    AgentLoop(ai_client=ScriptedAgentClient(), max_steps=bad_max_steps)

    def test_step_history_resets_between_runs(self):
        client = ScriptedAgentClient(
            replies=[
                tool_json("tasks.add", {"title": "First"}),
                tool_json("tasks.add", {"title": "Second"}),
            ]
        )
        loop = self.make_loop(client)

        loop.run(make_context("Add a task"))
        self.assertEqual([step.tool_name for step in loop.steps], ["tasks.add"])

        loop.run(make_context("Add another task"))
        self.assertEqual([step.tool_name for step in loop.steps], ["tasks.add"])
        self.assertEqual(len(service.get_tasks(database_path=self.database_path)), 2)

    def test_agent_step_repr_describes_tool_and_final_steps(self):
        self.assertEqual(
            repr(AgentStep(step_number=1, tool_name="tasks.list")),
            "AgentStep(step=1, tool='tasks.list')",
        )
        self.assertEqual(
            repr(AgentStep(step_number=2, is_final=True, final_response="Done")),
            "AgentStep(step=2, final='Done')",
        )

    # ------------------------------------------------------------------
    # Context plumbing and the convenience wrapper
    # ------------------------------------------------------------------

    def test_context_sections_are_forwarded_on_every_step(self):
        conversation = "User: hello\nSIRIUS: Hi there!"
        memories = "wifi password: secret123"
        client = ScriptedAgentClient(
            replies=[tool_json("tasks.list"), "final answer"]
        )
        loop = self.make_loop(client)

        loop.run(
            make_context(
                "What are my tasks?", conversation=conversation, memories=memories
            )
        )

        self.assertEqual(client.conversations, [conversation, conversation])
        self.assertEqual(client.memories, [memories, memories])
        self.assertEqual(client.system_prompts[0], client.system_prompts[1])
        self.assertIn("Tool catalog:", client.system_prompts[0])
        self.assertEqual(client.prompts[0], "What are my tasks?")

    def test_run_agent_loop_wrapper_uses_the_default_registry(self):
        client = ScriptedAgentClient(
            replies=[tool_json("tasks.add", {"title": "Wrapped"})]
        )

        response = run_agent_loop(
            ai_client=client,
            context=make_context("Add a task"),
            database_path=self.database_path,
        )

        self.assertEqual(response, "Task created successfully! ID: 1")

    def test_memory_is_never_written_by_the_agent_loop_itself(self):
        client = ScriptedAgentClient(
            replies=[tool_json("tasks.list"), "here is your list"]
        )
        loop = self.make_loop(client)

        loop.run(make_context("What are my tasks?"))

        self.assertEqual(memory_service.list_memories(self.database_path), [])


if __name__ == "__main__":
    unittest.main()




