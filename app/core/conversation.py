"""Bounded in-session conversation context for SIRIUS.

Keeps the most recent user/assistant messages of the current CLI session in
memory only; the context disappears when the process exits and nothing is
persisted. It exists solely to help the AI resolve follow-up requests and
never bypasses tool validation or confirmation.
"""

from collections import deque


DEFAULT_MAX_MESSAGES = 12

ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"

ROLE_LABELS = {ROLE_USER: "User", ROLE_ASSISTANT: "SIRIUS"}


class ConversationContext:
    """Fixed-capacity transcript of the current session's exchanges."""

    def __init__(self, max_messages=DEFAULT_MAX_MESSAGES):
        if not isinstance(max_messages, int) or isinstance(max_messages, bool):
            raise ValueError("max_messages must be a whole number.")
        if max_messages < 1:
            raise ValueError("max_messages must be at least 1.")

        self._messages = deque(maxlen=max_messages)

    def __len__(self):
        return len(self._messages)

    def add_user_message(self, text):
        """Record a user message, dropping the oldest when full."""
        self._append(ROLE_USER, text)

    def add_assistant_message(self, text):
        """Record a SIRIUS message, dropping the oldest when full."""
        self._append(ROLE_ASSISTANT, text)

    def get_messages(self):
        """Return the bounded transcript as an immutable (role, text) tuple."""
        return tuple(self._messages)

    def render_transcript(self):
        """Return the transcript text for the AI, or None when empty."""
        if not self._messages:
            return None

        return "\n".join(
            f"{ROLE_LABELS[role]}: {text}" for role, text in self._messages
        )

    def clear(self):
        """Forget every message (e.g. when the user starts a new topic)."""
        self._messages.clear()

    def _append(self, role, text):
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Message text cannot be empty.")

        self._messages.append((role, text.strip()))