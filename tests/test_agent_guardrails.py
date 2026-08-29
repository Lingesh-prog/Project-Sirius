"""Tests for Module 3.2 agent-loop hardening and observability.

Covers the repetition guard, the deterministic agent trace, and the per-run
observation budget. The AI client is always a scripted fake, so no test can
reach a real provider over the network.
"""

import tempfile
import unittest
from pathlib import Path

from app.core.agent.loop import (
    AGENT_TRACE_FOOTER,
    AGENT_TRACE_HEADER,
    DEFAULT_MAX_OBSERVATION_CHARS,
    AgentLoop,
    AgentStep,
)
from app.core.assistant import handle_command
from app.storage.database import initialize_database
from app.tools.memory import service as memory_service
from app.tools.tasks import service

from tests.test_agent_loop import ScriptedAgentClient, make_context, tool_json


class RepetitionGuardTests(unittest.TestCase):
    """The loop never re-executes an identical (tool, arguments) call."""

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "guardrails-test.db"
        initialize_database(self.database_path)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def make_loop(self, client, **overrides):
        options = {"ai_client": client, "database_path": self.database_path}
        options.update(overrides)
        return AgentLoop(**options)

    def test_identical_repeated_call_is_skipped_and_prior_observation_returned(self):
        service.add_task("Buy milk", database_path=self.database_path)
        client = ScriptedAgentClient(
            replies=[
                tool_json("tasks.list"),
                tool_json("tasks.list"),
                "this reply must never be consumed",
            ]
        )
        loop = self.make_loop(client)

        response = loop.run(make_context("What are my tasks?"))

        self.assertIn("[1] Buy milk", response)
        self.assertEqual(client.calls, 2)
        self.assertEqual(client.replies, ["this reply must never be consumed"])
        self.assertEqual(
            [(step.tool_name, step.skipped_repeat) for step in loop.steps],
            [("tasks.list", False), ("tasks.list", True)],
        )
        self.assertEqual(
            service.get_tasks(database_path=self.database_path)[0][1], "Buy milk"
        )

    def test_same_tool_with_different_arguments_is_not_a_repeat(self):
        memory_service.save_memory("wifi password", "secret123", self.database_path)
        memory_service.save_memory("birthday", "May 5", self.database_path)
        client = ScriptedAgentClient(
            replies=[
                tool_json("memory.search", {"query": "wifi"}),
                tool_json("memory.search", {"query": "birthday"}),
                "done",
            ]
        )
        loop = self.make_loop(client)

        response = loop.run(make_context("Find my wifi password and birthday"))

        self.assertEqual(response, "done")
        self.assertEqual(client.calls, 3)
        self.assertFalse(any(step.skipped_repeat for step in loop.steps))
        self.assertIn("secret123", client.prompts[1])
        self.assertIn("May 5", client.prompts[2])

    def test_repetition_guard_resets_between_runs(self):
        service.add_task("Buy milk", database_path=self.database_path)
        client = ScriptedAgentClient(
            replies=[
                tool_json("tasks.list"),
                "first answer",
                tool_json("tasks.list"),
                "second answer",
            ]
        )
        loop = self.make_loop(client)

        first = loop.run(make_context("What are my tasks?"))
        second = loop.run(make_context("What are my tasks now?"))

        self.assertEqual(first, "first answer")
        self.assertEqual(second, "second answer")
        self.assertEqual(client.calls, 4)
        self.assertFalse(any(step.skipped_repeat for step in loop.steps))

    def test_argument_key_order_does_not_defeat_the_guard(self):
        client = ScriptedAgentClient(
            replies=[
                '{"tool": "memory.search", "arguments": {"query": "wifi"}}',
                '{"arguments": {"query": "wifi"}, "tool": "memory.search"}',
            ]
        )
        loop = self.make_loop(client)

        loop.run(make_context("search wifi"))

        self.assertEqual(
            [(step.tool_name, step.skipped_repeat) for step in loop.steps],
            [("memory.search", False), ("memory.search", True)],
        )

    def test_skipped_repeat_step_repr(self):
        step = AgentStep(step_number=2, tool_name="tasks.list", skipped_repeat=True)
        self.assertEqual(
            repr(step), "AgentStep(step=2, skipped repeat of 'tasks.list')"
        )

    def test_state_modifying_tools_still_execute_once_and_end_the_run(self):
        client = ScriptedAgentClient(
            replies=[tool_json("tasks.add", {"title": "Buy milk"})]
        )
        loop = self.make_loop(client)

        response = loop.run(make_context("Add a task"))

        self.assertEqual(response, "Task created successfully! ID: 1")
        self.assertEqual(client.calls, 1)
        self.assertFalse(any(step.skipped_repeat for step in loop.steps))


class AgentTraceTests(unittest.TestCase):
    """render_trace() is deterministic, compact, and complete."""

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "trace-test.db"
        initialize_database(self.database_path)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_trace_is_empty_without_steps(self):
        loop = AgentLoop(
            ai_client=ScriptedAgentClient(), database_path=self.database_path
        )
        self.assertEqual(loop.render_trace(), "")

    def test_trace_lists_state_modifying_tool_with_arguments(self):
        client = ScriptedAgentClient(
            replies=[tool_json("tasks.add", {"title": "Buy milk"})]
        )
        loop = AgentLoop(ai_client=client, database_path=self.database_path)

        loop.run(make_context("Add a task"))

        lines = loop.render_trace().splitlines()
        self.assertEqual(lines[0], AGENT_TRACE_HEADER)
        self.assertEqual(lines[1], '[1] tasks.add(title="Buy milk")')
        self.assertEqual(lines[-1], AGENT_TRACE_FOOTER)

    def test_trace_marks_skipped_repeats(self):
        service.add_task("Buy milk", database_path=self.database_path)
        client = ScriptedAgentClient(
            replies=[tool_json("tasks.list"), tool_json("tasks.list")]
        )
        loop = AgentLoop(ai_client=client, database_path=self.database_path)

        loop.run(make_context("What are my tasks?"))

        lines = loop.render_trace().splitlines()
        self.assertEqual(lines[1], "[1] tasks.list()")
        self.assertEqual(lines[2], "[2] tasks.list() (skipped: repeated call)")
        self.assertEqual(lines[-1], AGENT_TRACE_FOOTER)

    def test_trace_ends_with_final_response_marker(self):
        service.add_task("Buy milk", database_path=self.database_path)
        client = ScriptedAgentClient(
            replies=[tool_json("tasks.list"), "All done."]
        )
        loop = AgentLoop(ai_client=client, database_path=self.database_path)

        loop.run(make_context("What are my tasks?"))

        lines = loop.render_trace().splitlines()
        self.assertEqual(lines[1], "[1] tasks.list()")
        self.assertEqual(lines[2], "[2] final response")
        self.assertEqual(lines[-1], AGENT_TRACE_FOOTER)

    def test_trace_renders_arguments_sorted_and_deterministic(self):
        client = ScriptedAgentClient(
            replies=[
                tool_json("tasks.add", {"title": "Buy milk", "priority": "high"})
            ]
        )
        loop = AgentLoop(ai_client=client, database_path=self.database_path)

        loop.run(make_context("Add a task"))

        self.assertIn(
            '[1] tasks.add(priority="High", title="Buy milk")',
            loop.render_trace(),
        )


class AssistantTraceIntegrationTests(unittest.TestCase):
    """The assistant exposes the agent trace only for AI-driven turns."""

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = (
            Path(self.temporary_directory.name) / "assistant-trace-test.db"
        )
        initialize_database(self.database_path)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_ai_command_appends_the_rendered_trace(self):
        client = ScriptedAgentClient(
            replies=[tool_json("tasks.add", {"title": "Buy milk"})]
        )
        trace = []

        response = handle_command(
            "Add a task to buy milk",
            database_path=self.database_path,
            ai_client=client,
            agent_trace=trace,
        )

        self.assertEqual(response, "Task created successfully! ID: 1")
        self.assertEqual(len(trace), 1)
        self.assertIn(AGENT_TRACE_HEADER, trace[0])
        self.assertIn("tasks.add", trace[0])

    def test_deterministic_commands_leave_the_trace_untouched(self):
        client = ScriptedAgentClient(replies=["should not be used"])
        trace = []

        self.assertEqual(
            handle_command(
                "add task Direct command",
                database_path=self.database_path,
                ai_client=client,
                agent_trace=trace,
            ),
            "Task created successfully! ID: 1",
        )
        handle_command(
            "list tasks",
            database_path=self.database_path,
            ai_client=client,
            agent_trace=trace,
        )

        self.assertEqual(trace, [])
        self.assertEqual(client.calls, 0)

    def test_trace_collection_is_opt_in(self):
        client = ScriptedAgentClient(
            replies=[tool_json("tasks.add", {"title": "Buy milk"})]
        )

        response = handle_command(
            "Add a task to buy milk",
            database_path=self.database_path,
            ai_client=client,
        )

        self.assertEqual(response, "Task created successfully! ID: 1")

    def test_destructive_confirmation_turn_has_no_trace_steps(self):
        service.add_task("Delete me", database_path=self.database_path)
        client = ScriptedAgentClient(
            replies=[tool_json("tasks.delete", {"task_id": 1})]
        )
        trace = []

        response = handle_command(
            "please remove the Delete me task",
            database_path=self.database_path,
            ai_client=client,
            agent_trace=trace,
        )

        self.assertIn("confirm delete task 1", response)
        self.assertEqual(trace, [])
        self.assertEqual(len(service.get_tasks(database_path=self.database_path)), 1)

    def test_ai_command_trace_marks_skipped_repeats(self):
        service.add_task("Buy milk", database_path=self.database_path)
        client = ScriptedAgentClient(
            replies=[tool_json("tasks.list"), tool_json("tasks.list")]
        )
        trace = []

        response = handle_command(
            "What are my tasks?",
            database_path=self.database_path,
            ai_client=client,
            agent_trace=trace,
        )

        self.assertIn("[1] Buy milk", response)
        self.assertIn("(skipped: repeated call)", trace[0])


class ObservationBudgetTests(unittest.TestCase):
    """Observations fed back to the AI are size-bounded per run."""

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "budget-test.db"
        initialize_database(self.database_path)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_oversized_observation_is_truncated_in_follow_up_prompt(self):
        service.add_task("B" * 300, database_path=self.database_path)
        client = ScriptedAgentClient(
            replies=[tool_json("tasks.list"), "final answer"]
        )
        loop = AgentLoop(
            ai_client=client,
            database_path=self.database_path,
            max_observation_chars=80,
        )

        loop.run(make_context("What are my tasks?"))

        follow_up = client.prompts[1]
        self.assertIn("[observation truncated]", follow_up)
        observation_portion = (
            follow_up.split("Observation: ", 1)[1].split("\n\nBased on", 1)[0]
        )
        self.assertEqual(
            len(observation_portion), 80 + len("\n... [observation truncated]")
        )
        self.assertTrue(observation_portion.startswith("========== YOUR TASKS =========="))
        # The full observation is still recorded on the step itself.
        self.assertIn("B" * 300, loop.steps[0].observation)

    def test_small_observations_are_not_truncated(self):
        service.add_task("Buy milk", database_path=self.database_path)
        client = ScriptedAgentClient(
            replies=[tool_json("tasks.list"), "final answer"]
        )
        loop = AgentLoop(ai_client=client, database_path=self.database_path)

        loop.run(make_context("What are my tasks?"))

        self.assertNotIn("[observation truncated]", client.prompts[1])
        self.assertIn("[1] Buy milk", client.prompts[1])

    def test_default_observation_budget(self):
        self.assertEqual(DEFAULT_MAX_OBSERVATION_CHARS, 1200)

    def test_max_observation_chars_must_be_a_positive_whole_number(self):
        for bad_value in (0, -1, 1.5, "10", True):
            with self.subTest(max_observation_chars=bad_value):
                with self.assertRaises(ValueError):
                    AgentLoop(
                        ai_client=ScriptedAgentClient(), max_observation_chars=bad_value
                    )


if __name__ == "__main__":
    unittest.main()



