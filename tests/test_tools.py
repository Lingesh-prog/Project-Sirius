"""Unit tests for the SIRIUS tool registry, validation, and safety layer."""

import json
import unittest

from app.core.tools import (
    DESTRUCTIVE_TOOLS,
    TOOL_MEMORY_DELETE,
    TOOL_MEMORY_LIST,
    TOOL_MEMORY_SAVE,
    TOOL_MEMORY_SEARCH,
    TOOL_REMINDERS_ADD,
    TOOL_REMINDERS_DELETE,
    TOOL_TASKS_ADD,
    TOOL_TASKS_DELETE,
    TOOL_TASKS_UPDATE,
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

    def test_update_requires_the_task_id(self):
        with self.assertRaisesRegex(ToolValidationError, "task_id"):
            validate_tool_request(TOOL_TASKS_UPDATE, {"title": "New title"})

    def test_update_requires_at_least_one_field(self):
        with self.assertRaisesRegex(ToolValidationError, "At least one field"):
            validate_tool_request(TOOL_TASKS_UPDATE, {"task_id": 1})

    def test_update_accepts_multiple_fields_and_normalizes_them(self):
        arguments = validate_tool_request(
            TOOL_TASKS_UPDATE,
            {
                "task_id": " 2 ",
                "title": "  Renamed  ",
                "priority": "high",
                "due_date": "2026-09-04",
            },
        )

        self.assertEqual(
            arguments,
            {
                "task_id": 2,
                "title": "Renamed",
                "due_date": "2026-09-04",
                "priority": "High",
            },
        )

    def test_update_rejects_protected_fields(self):
        for field in ("status", "created_at", "id"):
            with self.subTest(field=field):
                with self.assertRaisesRegex(ToolValidationError, f"'{field}'"):
                    validate_tool_request(
                        TOOL_TASKS_UPDATE, {"task_id": 1, field: "hacked"}
                    )

    def test_memory_save_requires_key_and_value(self):
        with self.assertRaisesRegex(ToolValidationError, "key"):
            validate_tool_request(TOOL_MEMORY_SAVE, {"value": "v"})

        with self.assertRaisesRegex(ToolValidationError, "value"):
            validate_tool_request(TOOL_MEMORY_SAVE, {"key": "k"})

    def test_memory_save_normalizes_and_keeps_both_fields(self):
        arguments = validate_tool_request(
            TOOL_MEMORY_SAVE, {"key": "  wifi password  ", "value": "  secret  "}
        )

        self.assertEqual(arguments, {"key": "wifi password", "value": "secret"})

    def test_memory_list_takes_no_arguments(self):
        self.assertEqual(validate_tool_request(TOOL_MEMORY_LIST, {}), {})

    def test_memory_delete_requires_the_memory_id(self):
        with self.assertRaisesRegex(ToolValidationError, "memory_id"):
            validate_tool_request(TOOL_MEMORY_DELETE, {})

    def test_memory_delete_accepts_digit_strings(self):
        self.assertEqual(
            validate_tool_request(TOOL_MEMORY_DELETE, {"memory_id": " 4 "}),
            {"memory_id": 4},
        )

    def test_memory_search_requires_the_query(self):
        with self.assertRaisesRegex(ToolValidationError, "query"):
            validate_tool_request(TOOL_MEMORY_SEARCH, {})

    def test_memory_search_rejects_an_empty_query(self):
        with self.assertRaisesRegex(ToolValidationError, "query"):
            validate_tool_request(TOOL_MEMORY_SEARCH, {"query": "   "})

    def test_memory_search_normalizes_surrounding_whitespace(self):
        self.assertEqual(
            validate_tool_request(TOOL_MEMORY_SEARCH, {"query": "  wifi  "}),
            {"query": "wifi"},
        )

    def test_memory_search_rejects_unknown_arguments(self):
        with self.assertRaisesRegex(ToolValidationError, "limit"):
            validate_tool_request(TOOL_MEMORY_SEARCH, {"query": "wifi", "limit": 3})


class ToolSafetyTests(unittest.TestCase):
    def test_exactly_the_delete_tools_are_destructive(self):
        self.assertEqual(
            DESTRUCTIVE_TOOLS,
            {TOOL_TASKS_DELETE, TOOL_REMINDERS_DELETE, TOOL_MEMORY_DELETE},
        )

    def test_catalog_lists_all_thirteen_tools(self):
        catalog = build_tool_catalog()

        for tool in (
            "tasks.add",
            "tasks.update",
            "tasks.list",
            "tasks.complete",
            "tasks.delete",
            "reminders.add",
            "reminders.list",
            "reminders.complete",
            "reminders.delete",
            "memory.save",
            "memory.list",
            "memory.search",
            "memory.delete",
        ):
            with self.subTest(tool=tool):
                self.assertIn(tool, catalog)