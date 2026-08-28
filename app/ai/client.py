"""Provider-independent AI client abstraction for SIRIUS.

The rest of SIRIUS depends on ``AIClient`` and ``create_ai_client`` from this
module, never on a provider SDK. The Gemini SDK import is lazy and lives only
in this module so SIRIUS - and the test suite - runs without any provider
package installed. Adding a provider later means adding one class here and
one branch in ``create_ai_client``.
"""

from abc import ABC, abstractmethod
import os

from app.ai.prompts import (
    CONVERSATION_HEADER,
    CURRENT_REQUEST_HEADER,
    MEMORY_HEADER,
)


DEFAULT_PROVIDER = "gemini"
DEFAULT_GEMINI_MODEL = "gemini-3.7-flash"

PROVIDER_ENV_VAR = "SIRIUS_AI_PROVIDER"
GEMINI_API_KEY_ENV_VAR = "SIRIUS_GEMINI_API_KEY"
GEMINI_MODEL_ENV_VAR = "SIRIUS_GEMINI_MODEL"

SUPPORTED_PROVIDERS = ("gemini",)


class AIError(Exception):
    """Base class for clean, application-level AI errors."""


class AIConfigurationError(AIError):
    """SIRIUS AI settings are missing or invalid."""


class AIProviderError(AIError):
    """The configured AI provider failed to produce a usable response."""


class AIClient(ABC):
    """Minimal provider-independent text-generation interface.

    SIRIUS modules must program against this interface (or the
    ``create_ai_client`` factory), never against a provider SDK.
    """

    @abstractmethod
    def generate_text(
        self, prompt, system_prompt=None, conversation_history=None, relevant_memories=None
    ):
        """Return generated text for *prompt*, or raise an ``AIError``.

        *conversation_history* is an optional rendered transcript of earlier
        turns in the current session, and *relevant_memories* an optional
        rendering of matching stored memories; each provider decides how to
        include them.
        """


class GeminiClient(AIClient):
    """Gemini provider built on the official google-genai SDK.

    Uses the current Interactions API (``client.interactions.create``) with
    ``store=False`` so Gemini keeps no server-side copy of the exchange.
    An SDK client can be injected for testing; otherwise it is created
    lazily, which keeps the SDK import isolated in this module.
    """

    def __init__(self, api_key, model=DEFAULT_GEMINI_MODEL, sdk_client=None):
        if not api_key or not str(api_key).strip():
            raise AIConfigurationError(
                f"{GEMINI_API_KEY_ENV_VAR} must contain a Gemini API key."
            )

        self._api_key = api_key
        self._model = model
        self._sdk_client = (
            sdk_client if sdk_client is not None else _create_sdk_client(api_key)
        )

    @property
    def model(self):
        """Return the Gemini model used by this client."""
        return self._model

    def generate_text(
        self, prompt, system_prompt=None, conversation_history=None, relevant_memories=None
    ):
        """Return the model's text reply for *prompt*.

        Raises ``AIConfigurationError`` when the local setup is broken and
        ``AIProviderError`` for any provider or API failure.
        """
        request = {
            "model": self._model,
            "input": _compose_input(prompt, conversation_history, relevant_memories),
            "store": False,
        }
        if system_prompt:
            request["instructions"] = system_prompt

        try:
            interaction = self._sdk_client.interactions.create(**request)
        except AIError:
            raise
        except Exception as error:
            raise AIProviderError(f"Gemini request failed: {error}") from error

        return _extract_interaction_text(interaction)


def create_ai_client(environ=None):
    """Build the configured ``AIClient`` from environment settings.

    ``environ`` defaults to ``os.environ`` and is injectable for tests.
    """
    environment = os.environ if environ is None else environ

    provider = (environment.get(PROVIDER_ENV_VAR) or DEFAULT_PROVIDER).strip().lower()
    if provider not in SUPPORTED_PROVIDERS:
        supported = ", ".join(SUPPORTED_PROVIDERS)
        raise AIConfigurationError(
            f"Unsupported AI provider '{provider}'. Supported providers: {supported}."
        )

    return _create_gemini_client(environment)


def _create_gemini_client(environment):
    api_key = environment.get(GEMINI_API_KEY_ENV_VAR)
    if not api_key or not api_key.strip():
        raise AIConfigurationError(
            f"{GEMINI_API_KEY_ENV_VAR} is not set. "
            "Add your Gemini API key to the environment or copy .env.example to .env."
        )

    model = environment.get(GEMINI_MODEL_ENV_VAR) or DEFAULT_GEMINI_MODEL
    return GeminiClient(api_key=api_key, model=model)


def _create_sdk_client(api_key):
    """Create the official SDK client, keeping its import lazily isolated."""
    try:
        from google import genai
    except ImportError as error:
        raise AIConfigurationError(
            "The google-genai package is not installed. "
            "Run: pip install -r requirements.txt"
        ) from error

    return genai.Client(api_key=api_key)


def _extract_interaction_text(interaction):
    """Turn an SDK interaction into plain text with clean error handling."""
    status = getattr(interaction, "status", None)
    if status is not None and status != "completed":
        detail = getattr(interaction, "error", None) or "no error details provided"
        raise AIProviderError(f"Gemini interaction {status}: {detail}")

    output_text = getattr(interaction, "output_text", None)
    if not output_text or not str(output_text).strip():
        raise AIProviderError("Gemini returned an empty response.")

    return output_text


def _compose_input(prompt, conversation_history=None, relevant_memories=None):
    """Combine memories, the session transcript, and the request into one input."""
    if not conversation_history and not relevant_memories:
        return prompt

    sections = []

    if relevant_memories:
        sections.append(f"{MEMORY_HEADER}\n{relevant_memories.strip()}")
    if conversation_history:
        sections.append(f"{CONVERSATION_HEADER}\n{conversation_history.strip()}")

    sections.append(f"{CURRENT_REQUEST_HEADER} {prompt}")

    return "\n\n".join(sections)