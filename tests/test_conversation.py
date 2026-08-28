"""Tests for the bounded in-session conversation context."""

import unittest

from app.core.conversation import DEFAULT_MAX_MESSAGES, ConversationContext


class ConversationContextTests(unittest.TestCase):
    def test_new_context_is_empty(self):
        context = ConversationContext()

        self.assertEqual(len(context), 0)
        self.assertEqual(context.get_messages(), ())
        self.assertIsNone(context.render_transcript())

    def test_user_and_assistant_messages_are_stored_with_roles(self):
        context = ConversationContext()
        context.add_user_message("Add a task")
        context.add_assistant_message("Task created successfully! ID: 1")

        self.assertEqual(
            context.get_messages(),
            (("user", "Add a task"), ("assistant", "Task created successfully! ID: 1")),
        )

    def test_messages_keep_conversation_order(self):
        context = ConversationContext()
        context.add_user_message("first")
        context.add_assistant_message("second")
        context.add_user_message("third")

        self.assertEqual(
            [text for _role, text in context.get_messages()],
            ["first", "second", "third"],
        )
        self.assertEqual(
            [role for role, _text in context.get_messages()],
            ["user", "assistant", "user"],
        )

    def test_context_stays_bounded_to_the_maximum(self):
        context = ConversationContext(max_messages=4)
        for index in range(10):
            context.add_user_message(f"message {index}")

        self.assertEqual(len(context), 4)
        self.assertEqual(
            [text for _role, text in context.get_messages()],
            ["message 6", "message 7", "message 8", "message 9"],
        )

    def test_maximum_defaults_to_a_bounded_value(self):
        self.assertIsInstance(DEFAULT_MAX_MESSAGES, int)
        self.assertGreaterEqual(DEFAULT_MAX_MESSAGES, 1)

    def test_maximum_must_be_a_positive_whole_number(self):
        for max_messages in (0, -1, 1.5, "4", None, True):
            with self.subTest(max_messages=max_messages):
                with self.assertRaises(ValueError):
                    ConversationContext(max_messages=max_messages)

    def test_clear_forgets_every_message(self):
        context = ConversationContext()
        context.add_user_message("hello")
        context.add_assistant_message("hi")

        context.clear()

        self.assertEqual(len(context), 0)
        self.assertIsNone(context.render_transcript())

    def test_render_transcript_uses_readable_role_labels(self):
        context = ConversationContext()
        context.add_user_message("Add a task")
        context.add_assistant_message("Task created.")

        self.assertEqual(
            context.render_transcript(), "User: Add a task\nSIRIUS: Task created."
        )

    def test_get_messages_is_immutable_from_outside(self):
        context = ConversationContext()
        context.add_user_message("hello")

        messages = context.get_messages()

        self.assertIsInstance(messages, tuple)
        with self.assertRaises(AttributeError):
            messages.append(("user", "sneaky"))

    def test_empty_or_non_text_messages_are_rejected(self):
        context = ConversationContext()
        for text in ("", "   ", None, 5):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    context.add_user_message(text)

    def test_context_offers_no_persistence_interface(self):
        context = ConversationContext()

        for method in ("save", "load", "persist", "store"):
            self.assertFalse(hasattr(context, method))