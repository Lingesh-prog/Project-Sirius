"""Unit tests for the SIRIUS context assembly layer."""

import unittest

from app.ai.prompts import (
    CONVERSATION_HEADER,
    CURRENT_REQUEST_HEADER,
    MEMORY_HEADER,
)
from app.core.context_assembly import (
    AVAILABLE_TOOLS_HEADER,
    AssembledContext,
    assemble_context,
    assemble_prompt_input,
)
from app.core.conversation import ConversationContext


class ContextAssemblyTests(unittest.TestCase):
    """Test suite for deterministic AI context assembly."""

    def test_current_request_only(self):
        context = assemble_context("what tasks do I have")

        self.assertEqual(context.user_request, "what tasks do I have")
        self.assertEqual(context.prompt_input, "what tasks do I have")
        self.assertIsNone(context.conversation_history)
        self.assertIsNone(context.relevant_memories)
        self.assertIsNone(context.system_prompt)
        self.assertIsNone(context.tool_catalog)

    def test_request_plus_conversation(self):
        context = assemble_context(
            "make it high priority",
            conversation_history="User: add task DSD\nSIRIUS: Task created successfully! ID: 1",
        )

        self.assertEqual(context.user_request, "make it high priority")
        self.assertEqual(
            context.conversation_history,
            "User: add task DSD\nSIRIUS: Task created successfully! ID: 1",
        )
        self.assertIsNone(context.relevant_memories)

        expected_prompt = (
            f"{CONVERSATION_HEADER}\n"
            "User: add task DSD\nSIRIUS: Task created successfully! ID: 1\n\n"
            f"{CURRENT_REQUEST_HEADER} make it high priority"
        )
        self.assertEqual(context.prompt_input, expected_prompt)

    def test_request_plus_memories(self):
        context = assemble_context(
            "what is my wifi password",
            relevant_memories="wifi password: secret123",
        )

        self.assertEqual(context.user_request, "what is my wifi password")
        self.assertEqual(context.relevant_memories, "wifi password: secret123")
        self.assertIsNone(context.conversation_history)

        expected_prompt = (
            f"{MEMORY_HEADER}\n"
            "wifi password: secret123\n\n"
            f"{CURRENT_REQUEST_HEADER} what is my wifi password"
        )
        self.assertEqual(context.prompt_input, expected_prompt)

    def test_request_plus_conversation_plus_memories(self):
        context = assemble_context(
            "what is my wifi password",
            conversation_history="User: hello\nSIRIUS: Hi!",
            relevant_memories="wifi password: secret123",
        )

        self.assertEqual(context.user_request, "what is my wifi password")
        self.assertEqual(context.relevant_memories, "wifi password: secret123")
        self.assertEqual(context.conversation_history, "User: hello\nSIRIUS: Hi!")

        expected_prompt = (
            f"{MEMORY_HEADER}\n"
            "wifi password: secret123\n\n"
            f"{CONVERSATION_HEADER}\n"
            "User: hello\nSIRIUS: Hi!\n\n"
            f"{CURRENT_REQUEST_HEADER} what is my wifi password"
        )
        self.assertEqual(context.prompt_input, expected_prompt)

    def test_deterministic_ordering_of_sections(self):
        """Memories always precede recent conversation, which precedes the request."""
        context = assemble_context(
            "final question",
            conversation_history="User: previous\nSIRIUS: answer",
            relevant_memories="stored fact: 42",
        )

        prompt = context.prompt_input
        self.assertIn(MEMORY_HEADER, prompt)
        self.assertIn(CONVERSATION_HEADER, prompt)
        self.assertIn(CURRENT_REQUEST_HEADER, prompt)

        mem_idx = prompt.index(MEMORY_HEADER)
        conv_idx = prompt.index(CONVERSATION_HEADER)
        req_idx = prompt.index(CURRENT_REQUEST_HEADER)

        self.assertLess(mem_idx, conv_idx)
        self.assertLess(conv_idx, req_idx)

    def test_empty_sections_are_handled_cleanly(self):
        for empty_val in ("", "   ", None):
            with self.subTest(empty_val=empty_val):
                context = assemble_context(
                    "just a request",
                    conversation_history=empty_val,
                    relevant_memories=empty_val,
                )
                self.assertEqual(context.prompt_input, "just a request")
                self.assertIsNone(context.conversation_history)
                self.assertIsNone(context.relevant_memories)
                self.assertNotIn(MEMORY_HEADER, context.prompt_input)
                self.assertNotIn(CONVERSATION_HEADER, context.prompt_input)

    def test_whitespace_handling_and_normalization(self):
        context = assemble_context(
            "   padded user request   \n",
            conversation_history="  User: hi \n SIRIUS: hello  ",
            relevant_memories="  wifi: secret123  \n",
        )

        self.assertEqual(context.user_request, "padded user request")
        self.assertEqual(context.conversation_history, "User: hi \n SIRIUS: hello")
        self.assertEqual(context.relevant_memories, "wifi: secret123")

    def test_context_does_not_mutate_supplied_conversation_or_memory_data(self):
        conv = ConversationContext(max_messages=5)
        conv.add_user_message("hello")
        conv.add_assistant_message("hi")

        mem_rows = [
            (1, "wifi", "secret", "2026-01-01", "2026-01-01"),
            (2, "pin", "1234", "2026-01-01", "2026-01-01"),
        ]
        mem_copy = list(mem_rows)

        context = assemble_context(
            "request",
            conversation_history=conv,
            relevant_memories=mem_rows,
        )

        self.assertEqual(len(conv), 2)
        self.assertEqual(
            conv.get_messages(),
            (("user", "hello"), ("assistant", "hi")),
        )
        self.assertEqual(mem_rows, mem_copy)

    def test_bounded_conversation_behavior_remains_intact(self):
        conv = ConversationContext(max_messages=2)
        conv.add_user_message("msg 1")
        conv.add_assistant_message("reply 1")
        conv.add_user_message("msg 2")
        conv.add_assistant_message("reply 2")

        context = assemble_context("follow up", conversation_history=conv)

        self.assertNotIn("msg 1", context.conversation_history)
        self.assertNotIn("reply 1", context.conversation_history)
        self.assertIn("User: msg 2", context.conversation_history)
        self.assertIn("SIRIUS: reply 2", context.conversation_history)

    def test_conversation_as_sequence_of_pairs(self):
        pairs = [("user", "my task"), ("assistant", "task 1 created")]
        context = assemble_context("check it", conversation_history=pairs)

        self.assertEqual(
            context.conversation_history,
            "User: my task\nSIRIUS: task 1 created",
        )

    def test_memories_as_sequence_of_rows(self):
        rows = [
            (1, "server ip", "192.168.1.1", "2026-01-01", "2026-01-01"),
            (2, "ssh port", "22", "2026-01-01", "2026-01-01"),
        ]
        context = assemble_context("connect", relevant_memories=rows)

        self.assertEqual(
            context.relevant_memories,
            "server ip: 192.168.1.1\nssh port: 22",
        )

    def test_malformed_user_request_raises_value_error(self):
        for bad_req in ("", "   ", None, 123, ["list"]):
            with self.subTest(bad_req=bad_req):
                with self.assertRaisesRegex(ValueError, "User request cannot be empty"):
                    assemble_context(bad_req)

    def test_malformed_conversation_history_raises_value_error(self):
        for bad_conv in (123, {"role": "user"}, [1, 2, 3]):
            with self.subTest(bad_conv=bad_conv):
                with self.assertRaises(ValueError):
                    assemble_context("valid request", conversation_history=bad_conv)

    def test_malformed_relevant_memories_raises_value_error(self):
        for bad_mem in (123, {"key": "val"}):
            with self.subTest(bad_mem=bad_mem):
                with self.assertRaises(ValueError):
                    assemble_context("valid request", relevant_memories=bad_mem)

    def test_system_prompt_generated_from_catalog_and_today(self):
        context = assemble_context(
            "list tasks",
            tool_catalog="- tasks.list()\n- tasks.add()",
            today="2026-09-01 (Tuesday)",
        )

        self.assertIsNotNone(context.system_prompt)
        self.assertIn("Tool catalog:\n- tasks.list()\n- tasks.add()", context.system_prompt)
        self.assertIn("Current date: 2026-09-01 (Tuesday)", context.system_prompt)
        self.assertEqual(context.tool_catalog, "- tasks.list()\n- tasks.add()")

    def test_explicit_system_prompt_overrides_catalog(self):
        context = assemble_context(
            "custom request",
            system_prompt="Custom instructions for the model.",
            tool_catalog="- tasks.list()",
        )

        self.assertEqual(context.system_prompt, "Custom instructions for the model.")

    def test_render_full_context_produces_unambiguous_view(self):
        context = assemble_context(
            "what is my server ip",
            conversation_history="User: login\nSIRIUS: logged in",
            relevant_memories="server ip: 10.0.0.1",
            system_prompt="You are SIRIUS.",
        )

        full = context.render_full_context()
        self.assertIn("System instructions:\nYou are SIRIUS.", full)
        self.assertIn("Relevant stored memories:\nserver ip: 10.0.0.1", full)
        self.assertIn("Recent conversation:\nUser: login\nSIRIUS: logged in", full)
        self.assertIn("Current request: what is my server ip", full)

    def test_assembled_context_repr(self):
        context = assemble_context("test command")
        repr_str = repr(context)
        self.assertIn("AssembledContext", repr_str)
        self.assertIn("test command", repr_str)

