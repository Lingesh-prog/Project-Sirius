"""Unit tests for the SIRIUS tool registry, validation, and safety layer."""

import json
import unittest

from app.core.tools import (
    DESTRUCTIVE_TOOLS,
    TOOL_REMINDERS_ADD,
    TOOL_REMINDERS_DELETE,
    TOOL_TASKS_ADD,
    TOOL_TASKS_DELETE,
    ToolResponseError,
    ToolValidationError,
    build_tool_catalog,
    parse_tool_response,
    validate_tool_request,
)


def tool_request(tool, arguments):
    """Return a JSON tool request the way the LLM is asked to produce one."""
    return json.dumps({"tool": tool, "arguments": arguments})


class ParseToolResponseTests(unittest.TestCase):
    def test_plain_json_object_is_parsed(self):
        self.assertEqual(
            parse_tool_response(tool_request("tasks.list", {})), ("tasks.list", {})
        )

    def test_json_inside_code_fences_is_parsed(self):
        text = "```json\n" + tool_request("tasks.add", {"title": "A"}) + "\n```"

        self.assertEqual(parse_tool_response(text), ("tasks.add", {"title": "A"}))

    def test_json_with_surrounding_prose_is_parsed(self):
        text = "Sure! " + tool_request("reminders.list", {}) + " Done."

        self.assertEqual(parse_tool_response(text), ("reminders.list", {}))

    def test_missing_arguments_default_to_empty_object(self):
        self.assertEqual(parse_tool_response('{"tool": "tasks.list"}'), ("tasks.list", {}))

    def test_null_tool_means_no_matching_tool(self):
        self.assertEqual(
            parse_tool_response('{"tool": null, "arguments": {}}'), (None, {})
        )

    def test_empty_response_is_rejected(self):
        for text in ("", "   ", None):
            with self.subTest(text=text):
                with self.assertRaises(ToolResponseError):
                    parse_tool_response(text)

    def test_response_without_json_is_rejected(self):
        with self.assertRaises(ToolResponseError):
            parse_tool_response("Sorry, I cannot help with that.")

    def test_invalid_json_is_rejected(self):
        with self.assertRaises(ToolResponseError):
            parse_tool_response("{'tool': 'tasks.list'}")

    def test_missing_tool_name_is_rejected(self):
        with self.assertRaises(ToolResponseError):
            parse_tool_response('{"arguments": {}}')

    def test_non_dict_arguments_are_rejected(self):
        with self.assertRaises(ToolResponseError):
            parse_tool_response('{"tool": "tasks.list", "arguments": [1]}')


class ValidateToolRequestTests(unittest.TestCase):
    def test_unknown_tool_is_rejected(self):
        with self.assertRaisesRegex(ToolValidationError, "tasks.drop_all"):
            validate_tool_request("tasks.drop_all", {})

    def test_non_dict_arguments_are_rejected(self):
        with self.assertRaises(ToolValidationError):
            validate_tool_request("tasks.list", ["nope"])

    def test_unknown_argument_is_rejected(self):
        with self.assertRaisesRegex(ToolValidationError, "color"):
            validate_tool_request(TOOL_TASKS_ADD, {"title": "A", "color": "red"})

    def test_missing_required_argument_is_rejected(self):
        with self.assertRaisesRegex(ToolValidationError, "title"):
            validate_tool_request(TOOL_TASKS_ADD, {"priority": "High"})

    def test_empty_required_text_argument_is_rejected(self):
        with self.assertRaisesRegex(ToolValidationError, "title"):
            validate_tool_request(TOOL_TASKS_ADD, {"title": "   "})

    def test_text_arguments_are_stripped_and_optional_empties_dropped(self):
        arguments = validate_tool_request(
            TOOL_TASKS_ADD,
            {"title": "  Finish DSD assignment  ", "description": "  ", "priority": "HIGH"},
        )

        self.assertEqual(
            arguments, {"title": "Finish DSD assignment", "priority": "High"}
        )

    def test_id_arguments_accept_integers_and_digit_strings(self):
        self.assertEqual(
            validate_tool_request("tasks.complete", {"task_id": " 3 "}), {"task_id": 3}
        )
        self.assertEqual(
            validate_tool_request("tasks.complete", {"task_id": 7}), {"task_id": 7}
        )

    def test_id_arguments_reject_non_numbers(self):
        with self.assertRaisesRegex(ToolValidationError, "whole number"):
            validate_tool_request("tasks.complete", {"task_id": "three"})

    def test_remind_at_must_be_an_iso_datetime(self):
        for value in ("tomorrow at 10:00", "2026-09-01", 123, None):
            with self.subTest(value=value):
                with self.assertRaises(ToolValidationError):
                    validate_tool_request(
                        TOOL_REMINDERS_ADD,
                        {"text": "Call dentist", "remind_at": value},
                    )

    def test_valid_remind_at_is_kept(self):
        arguments = validate_tool_request(
            TOOL_REMINDERS_ADD,
            {"text": "Call dentist", "remind_at": "2026-09-01T10:00"},
        )

        self.assertEqual(arguments["remind_at"], "2026-09-01T10:00")

    def test_invalid_priority_is_rejected(self):
        with self.assertRaisesRegex(ToolValidationError, "Low, Medium, High"):
            validate_tool_request(TOOL_TASKS_ADD, {"title": "A", "priority": "Urgent"})


class ToolSafetyTests(unittest.TestCase):
    def test_exactly_the_two_delete_tools_are_destructive(self):
        self.assertEqual(DESTRUCTIVE_TOOLS, {TOOL_TASKS_DELETE, TOOL_REMINDERS_DELETE})

    def test_catalog_lists_all_eight_tools(self):
        catalog = build_tool_catalog()

        for tool in (
            "tasks.add",
            "tasks.list",
            "tasks.complete",
            "tasks.delete",
            "reminders.add",
            "reminders.list",
            "reminders.complete",
            "reminders.delete",
        ):
            with self.subTest(tool=tool):
                self.assertIn(tool, catalog)