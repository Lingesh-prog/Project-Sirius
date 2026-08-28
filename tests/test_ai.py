"""Tests for the provider-independent SIRIUS AI foundation.

Every test uses injected fakes or patched factories; no test can reach a
real AI provider over the network.
"""

import sys
import types
import unittest
from unittest import mock

from app.ai import (
    AIClient,
    AIConfigurationError,
    AIError,
    AIProviderError,
    create_ai_client,
)
from app.ai import client as ai_client_module
from app.ai.client import (
    DEFAULT_GEMINI_MODEL,
    GEMINI_API_KEY_ENV_VAR,
    GEMINI_MODEL_ENV_VAR,
    PROVIDER_ENV_VAR,
    GeminiClient,
)
from app.ai.prompts import (
    SIRIUS_SYSTEM_PROMPT,
    build_system_prompt,
    build_tool_system_prompt,
)


class FakeInteractions:
    """Stand-in for the SDK ``client.interactions`` namespace."""

    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response


class FakeSdkClient:
    """Stand-in for the injected Gemini SDK client; never touches the network."""

    def __init__(self, response=None, error=None):
        self.interactions = FakeInteractions(response, error)

    @classmethod
    def responding(cls, output_text="Hello from SIRIUS."):
        return cls(
            response=types.SimpleNamespace(status="completed", output_text=output_text)
        )


class CreateAIClientTests(unittest.TestCase):
    """Factory configuration, provider selection, and missing-key handling."""

    def setUp(self):
        # Any real SDK construction would be a test bug; intercept the class.
        patcher = mock.patch.object(ai_client_module, "GeminiClient")
        self.gemini_factory = patcher.start()
        self.addCleanup(patcher.stop)

    def test_application_errors_share_the_ai_error_base(self):
        self.assertTrue(issubclass(AIConfigurationError, AIError))
        self.assertTrue(issubclass(AIProviderError, AIError))

    def test_gemini_is_the_default_provider(self):
        client = create_ai_client(environ={GEMINI_API_KEY_ENV_VAR: "key-123"})

        self.gemini_factory.assert_called_once_with(
            api_key="key-123", model=DEFAULT_GEMINI_MODEL
        )
        self.assertIs(client, self.gemini_factory.return_value)

    def test_provider_setting_selects_gemini(self):
        client = create_ai_client(
            environ={PROVIDER_ENV_VAR: "gemini", GEMINI_API_KEY_ENV_VAR: "key-123"}
        )

        self.gemini_factory.assert_called_once_with(
            api_key="key-123", model=DEFAULT_GEMINI_MODEL
        )
        self.assertIs(client, self.gemini_factory.return_value)

    def test_provider_setting_is_case_and_whitespace_insensitive(self):
        create_ai_client(
            environ={PROVIDER_ENV_VAR: "  GEMINI  ", GEMINI_API_KEY_ENV_VAR: "key-123"}
        )

        self.gemini_factory.assert_called_once()

    def test_model_override_is_passed_through(self):
        create_ai_client(
            environ={
                GEMINI_API_KEY_ENV_VAR: "key-123",
                GEMINI_MODEL_ENV_VAR: "gemini-2.5-flash",
            }
        )

        self.gemini_factory.assert_called_once_with(
            api_key="key-123", model="gemini-2.5-flash"
        )

    def test_missing_api_key_raises_clean_configuration_error(self):
        with self.assertRaisesRegex(AIConfigurationError, GEMINI_API_KEY_ENV_VAR):
            create_ai_client(environ={PROVIDER_ENV_VAR: "gemini"})

        self.gemini_factory.assert_not_called()

    def test_blank_api_key_raises_clean_configuration_error(self):
        with self.assertRaisesRegex(AIConfigurationError, GEMINI_API_KEY_ENV_VAR):
            create_ai_client(environ={GEMINI_API_KEY_ENV_VAR: "   "})

    def test_unknown_provider_raises_clean_configuration_error(self):
        with self.assertRaisesRegex(AIConfigurationError, "groq"):
            create_ai_client(
                environ={PROVIDER_ENV_VAR: "groq", GEMINI_API_KEY_ENV_VAR: "key-123"}
            )

        self.gemini_factory.assert_not_called()


class GeminiClientTests(unittest.TestCase):
    """Response handling with injected fakes; real API calls are impossible."""

    def test_gemini_client_satisfies_the_ai_client_abstraction(self):
        client = GeminiClient(api_key="key-123", sdk_client=FakeSdkClient.responding())

        self.assertIsInstance(client, AIClient)

    def test_generate_text_returns_the_model_output_text(self):
        sdk_client = FakeSdkClient.responding("Reminder noted.")
        client = GeminiClient(
            api_key="key-123", model="gemini-2.5-flash", sdk_client=sdk_client
        )

        self.assertEqual(client.generate_text("Hello"), "Reminder noted.")
        self.assertEqual(
            sdk_client.interactions.requests,
            [{"model": "gemini-2.5-flash", "input": "Hello", "store": False}],
        )

    def test_generate_text_sends_system_prompt_as_instructions(self):
        sdk_client = FakeSdkClient.responding()
        client = GeminiClient(api_key="key-123", sdk_client=sdk_client)

        client.generate_text("Hello", system_prompt="Be brief.")

        self.assertEqual(
            sdk_client.interactions.requests[0]["instructions"], "Be brief."
        )

    def test_generate_text_omits_instructions_when_no_system_prompt(self):
        sdk_client = FakeSdkClient.responding()
        client = GeminiClient(api_key="key-123", sdk_client=sdk_client)

        client.generate_text("Hello")

        self.assertNotIn("instructions", sdk_client.interactions.requests[0])

    def test_provider_exception_is_converted_to_a_clean_application_error(self):
        sdk_client = FakeSdkClient(error=Exception("503 backend broken"))
        client = GeminiClient(api_key="key-123", sdk_client=sdk_client)

        with self.assertRaisesRegex(AIProviderError, "503 backend broken"):
            client.generate_text("Hello")

    def test_failed_interaction_status_is_converted_to_a_clean_error(self):
        sdk_client = FakeSdkClient(
            response=types.SimpleNamespace(status="failed", error="quota exceeded")
        )
        client = GeminiClient(api_key="key-123", sdk_client=sdk_client)

        with self.assertRaisesRegex(AIProviderError, "quota exceeded"):
            client.generate_text("Hello")

    def test_empty_output_is_converted_to_a_clean_error(self):
        sdk_client = FakeSdkClient(
            response=types.SimpleNamespace(status="completed", output_text="   ")
        )
        client = GeminiClient(api_key="key-123", sdk_client=sdk_client)

        with self.assertRaises(AIProviderError):
            client.generate_text("Hello")

    def test_missing_sdk_package_raises_clean_configuration_error(self):
        with mock.patch.dict(sys.modules, {"google": None}):
            with self.assertRaisesRegex(AIConfigurationError, "google-genai"):
                GeminiClient(api_key="key-123")

    def test_missing_api_key_is_rejected_before_touching_the_sdk(self):
        with self.assertRaisesRegex(AIConfigurationError, GEMINI_API_KEY_ENV_VAR):
            GeminiClient(api_key="   ")

    def test_generate_text_embeds_conversation_history_in_the_request(self):
        sdk_client = FakeSdkClient.responding("Done.")
        client = GeminiClient(api_key="key-123", sdk_client=sdk_client)

        client.generate_text(
            "make it completed",
            conversation_history=(
                "User: Add a task to finish my DSD assignment\n"
                "SIRIUS: Task created successfully! ID: 1"
            ),
        )

        request = sdk_client.interactions.requests[0]
        self.assertIn("Recent conversation:", request["input"])
        self.assertIn("User: Add a task to finish my DSD assignment", request["input"])
        self.assertIn("Task created successfully! ID: 1", request["input"])
        self.assertIn("Current request: make it completed", request["input"])

    def test_generate_text_embeds_relevant_memories_before_the_conversation(self):
        sdk_client = FakeSdkClient.responding("Done.")
        client = GeminiClient(api_key="key-123", sdk_client=sdk_client)

        client.generate_text(
            "what is my wifi password",
            conversation_history="User: hello\nSIRIUS: Hi!",
            relevant_memories="wifi password: secret123",
        )

        input_text = sdk_client.interactions.requests[0]["input"]
        self.assertIn("Relevant stored memories:\nwifi password: secret123", input_text)
        self.assertIn("Recent conversation:\nUser: hello\nSIRIUS: Hi!", input_text)
        self.assertIn("Current request: what is my wifi password", input_text)
        self.assertLess(
            input_text.index("Relevant stored memories:"),
            input_text.index("Recent conversation:"),
        )

    def test_generate_text_without_sections_keeps_the_prompt_unchanged(self):
        sdk_client = FakeSdkClient.responding("Done.")
        client = GeminiClient(api_key="key-123", sdk_client=sdk_client)

        client.generate_text("plain request")

        self.assertEqual(
            sdk_client.interactions.requests[0]["input"], "plain request"
        )


class PromptsTests(unittest.TestCase):
    """System prompt foundation for the SIRIUS assistant."""

    def test_system_prompt_describes_sirius_without_tool_permissions(self):
        self.assertIn("SIRIUS", SIRIUS_SYSTEM_PROMPT)
        self.assertIn("cannot run commands", SIRIUS_SYSTEM_PROMPT)

    def test_build_system_prompt_without_extra_returns_the_base_prompt(self):
        self.assertEqual(build_system_prompt(), SIRIUS_SYSTEM_PROMPT)
        self.assertEqual(build_system_prompt(None), SIRIUS_SYSTEM_PROMPT)

    def test_build_system_prompt_appends_extra_instructions(self):
        combined = build_system_prompt("  Prefer bullet points.  ")

        self.assertTrue(combined.startswith(SIRIUS_SYSTEM_PROMPT))
        self.assertTrue(combined.endswith("Prefer bullet points."))

    def test_tool_calling_prompt_explains_conversation_context(self):
        prompt = build_tool_system_prompt("- tasks.add()", today="2026-09-01 (Tuesday)")

        self.assertIn("Recent conversation:", prompt)
        self.assertIn("Current request:", prompt)