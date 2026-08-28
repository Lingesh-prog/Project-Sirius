"""Unit tests for the SIRIUS AI response handling and reliability layer."""

import unittest
from unittest import mock

from app.ai import AIConfigurationError, AIProviderError
from app.core.context_assembly import assemble_context
from app.core.response_handler import (
    DECLINED_REQUEST_MESSAGE,
    EMPTY_RESPONSE_MESSAGE,
    MULTIPLE_TOOLS_MESSAGE,
    UNEXPECTED_ERROR_MESSAGE,
    handle_ai_interaction,
    process_ai_response,
)


class ResponseHandlerTests(unittest.TestCase):
    """Test suite for deterministic AI response processing and error handling."""

    def test_successful_normal_ai_response(self):
        reply = "RAM is volatile memory used for active processes, while ROM is permanent."
        result = process_ai_response(reply)
        self.assertEqual(result, reply)

    def test_empty_ai_response(self):
        for empty_reply in ("", "   ", None):
            with self.subTest(empty_reply=empty_reply):
                result = process_ai_response(empty_reply)
                self.assertEqual(result, EMPTY_RESPONSE_MESSAGE)

    def test_whitespace_only_response(self):
        result = process_ai_response("   \n\t   ")
        self.assertEqual(result, EMPTY_RESPONSE_MESSAGE)

    def test_provider_error_handling(self):
        mock_client = mock.Mock()
        mock_client.generate_text.side_effect = AIProviderError("503 Service Unavailable")
        context = assemble_context("test command")

        result = handle_ai_interaction(mock_client, context)
        self.assertIn("AI assistant is unavailable right now", result)
        self.assertIn("503 Service Unavailable", result)

    def test_configuration_error_handling(self):
        mock_client = mock.Mock()
        mock_client.generate_text.side_effect = AIConfigurationError("API key missing")
        context = assemble_context("test command")

        result = handle_ai_interaction(mock_client, context)
        self.assertIn("AI assistant is unavailable right now", result)
        self.assertIn("API key missing", result)

    def test_unexpected_ai_client_exception_is_handled_gracefully(self):
        mock_client = mock.Mock()
        mock_client.generate_text.side_effect = RuntimeError("Fatal crash in network socket")
        context = assemble_context("test command")

        result = handle_ai_interaction(mock_client, context)
        self.assertEqual(result, UNEXPECTED_ERROR_MESSAGE)
        self.assertNotIn("Fatal crash", result)
        self.assertNotIn("socket", result)

    def test_valid_tool_request(self):
        execute_mock = mock.Mock(return_value="Task created!")
        reply = '{"tool": "tasks.add", "arguments": {"title": "Finish DSD"}}'

        result = process_ai_response(reply, execute_tool_fn=execute_mock)

        self.assertEqual(result, "Task created!")
        execute_mock.assert_called_once_with(
            "tasks.add", {"title": "Finish DSD"}, None
        )

    def test_json_inside_code_fences(self):
        execute_mock = mock.Mock(return_value="Tasks listed.")
        reply = '```json\n{"tool": "tasks.list", "arguments": {}}\n```'

        result = process_ai_response(reply, execute_tool_fn=execute_mock)

        self.assertEqual(result, "Tasks listed.")
        execute_mock.assert_called_once_with("tasks.list", {}, None)

    def test_malformed_json_tool_request(self):
        reply = '```json\n{"tool": "tasks.add", "arguments": {broken\n```'
        result = process_ai_response(reply)
        self.assertIn("I could not process that request", result)

    def test_unknown_tool_is_rejected(self):
        reply = '{"tool": "system.reboot", "arguments": {}}'
        result = process_ai_response(reply)
        self.assertIn("That request is not supported", result)
        self.assertIn("system.reboot", result)

    def test_invalid_arguments_are_rejected(self):
        reply = '{"tool": "tasks.add", "arguments": {"title": "A", "priority": "Critical"}}'
        result = process_ai_response(reply)
        self.assertIn("That request is not supported", result)
        self.assertIn("Low, Medium, High", result)

    def test_missing_required_arguments_are_rejected(self):
        reply = '{"tool": "tasks.add", "arguments": {"priority": "High"}}'
        result = process_ai_response(reply)
        self.assertIn("That request is not supported", result)
        self.assertIn("Missing required argument 'title'", result)

    def test_multiple_tool_requests_in_text(self):
        reply = (
            '{"tool": "tasks.add", "arguments": {"title": "Task 1"}}\n'
            '{"tool": "tasks.add", "arguments": {"title": "Task 2"}}'
        )
        result = process_ai_response(reply)
        self.assertEqual(result, MULTIPLE_TOOLS_MESSAGE)

    def test_multiple_tool_requests_in_json_array(self):
        reply = '[{"tool": "tasks.add", "arguments": {"title": "1"}}, {"tool": "tasks.add", "arguments": {"title": "2"}}]'
        result = process_ai_response(reply)
        self.assertEqual(result, MULTIPLE_TOOLS_MESSAGE)

    def test_destructive_tool_requires_confirmation(self):
        confirm_mock = mock.Mock(return_value="Please confirm delete.")
        reply = '{"tool": "tasks.delete", "arguments": {"task_id": 42}}'

        result = process_ai_response(reply, build_confirmation_fn=confirm_mock)

        self.assertEqual(result, "Please confirm delete.")
        confirm_mock.assert_called_once_with("tasks.delete", {"task_id": 42}, None)

    def test_declined_tool_request_returns_clear_message(self):
        reply = '{"tool": null, "arguments": {}}'
        result = process_ai_response(reply)
        self.assertEqual(result, DECLINED_REQUEST_MESSAGE)

    def test_non_dict_arguments_are_rejected(self):
        reply = '{"tool": "tasks.add", "arguments": ["not a dict"]}'
        result = process_ai_response(reply)
        self.assertIn("I could not process that request", result)
        self.assertIn("arguments must be a JSON object", result)

    def test_missing_or_empty_tool_name_is_rejected(self):
        for bad_tool in ('{"arguments": {}}', '{"tool": "", "arguments": {}}', '{"tool": 123}'):
            with self.subTest(bad_tool=bad_tool):
                result = process_ai_response(bad_tool)
                self.assertIn("I could not process that request", result)
                self.assertIn("tool name", result)
