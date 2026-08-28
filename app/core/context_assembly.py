"""Deterministic context assembly layer for SIRIUS AI requests.

Prepares the structured context given to the AI model by coordinating:
1. Relevant persistent memories (pre-retrieved via memory_context)
2. Recent conversation transcript (bounded in-session transcript)
3. Current user request
4. System instructions and tool catalog

This module is strictly read-only: it never modifies memories, executes
tools, accesses SQLite, or calls AI providers directly.
"""

from app.ai.prompts import (
    CONVERSATION_HEADER,
    CURRENT_REQUEST_HEADER,
    MEMORY_HEADER,
    build_tool_system_prompt,
)
from app.core.conversation import ConversationContext
from app.core.memory_context import render_memories


AVAILABLE_TOOLS_HEADER = "Tool catalog:"


class AssembledContext:
    """Immutable data container for assembled AI context."""

    def __init__(
        self,
        user_request,
        prompt_input,
        system_prompt=None,
        conversation_history=None,
        relevant_memories=None,
        tool_catalog=None,
    ):
        self._user_request = user_request
        self._prompt_input = prompt_input
        self._system_prompt = system_prompt
        self._conversation_history = conversation_history
        self._relevant_memories = relevant_memories
        self._tool_catalog = tool_catalog

    @property
    def user_request(self):
        """The normalized current user request string."""
        return self._user_request

    @property
    def prompt_input(self):
        """The composed input prompt combining memories, transcript, and request."""
        return self._prompt_input

    @property
    def system_prompt(self):
        """The system prompt / instructions for the model, or None."""
        return self._system_prompt

    @property
    def conversation_history(self):
        """The rendered conversation transcript, or None when empty."""
        return self._conversation_history

    @property
    def relevant_memories(self):
        """The rendered relevant memories text, or None when empty."""
        return self._relevant_memories

    @property
    def tool_catalog(self):
        """The tool catalog string, or None."""
        return self._tool_catalog

    def render_full_context(self):
        """Render all present context sections into an unambiguous debugging view."""
        sections = []
        if self._system_prompt:
            sections.append(f"System instructions:\n{self._system_prompt}")
        if self._relevant_memories:
            sections.append(f"{MEMORY_HEADER}\n{self._relevant_memories}")
        if self._conversation_history:
            sections.append(f"{CONVERSATION_HEADER}\n{self._conversation_history}")
        sections.append(f"{CURRENT_REQUEST_HEADER} {self._user_request}")
        return "\n\n".join(sections)

    def __repr__(self):
        return (
            f"AssembledContext(user_request={self._user_request!r}, "
            f"has_memories={self._relevant_memories is not None}, "
            f"has_conversation={self._conversation_history is not None}, "
            f"has_system_prompt={self._system_prompt is not None})"
        )


def assemble_context(
    user_request,
    conversation_history=None,
    relevant_memories=None,
    tool_catalog=None,
    system_prompt=None,
    today=None,
):
    """Assemble all context sections for an AI request deterministically.

    Raises ValueError when user_request is empty/invalid, or when any section
    has an unrecognized shape. Empty sections are normalized to None and
    omitted from prompt sections.
    """
    clean_request = _validate_user_request(user_request)
    rendered_conversation = _normalize_conversation(conversation_history)
    rendered_memories = _normalize_memories(relevant_memories)
    clean_system_prompt = _resolve_system_prompt(
        system_prompt=system_prompt, tool_catalog=tool_catalog, today=today
    )
    clean_tool_catalog = (
        tool_catalog.strip()
        if isinstance(tool_catalog, str) and tool_catalog.strip()
        else None
    )

    prompt_input = assemble_prompt_input(
        clean_request,
        conversation_history=rendered_conversation,
        relevant_memories=rendered_memories,
    )

    return AssembledContext(
        user_request=clean_request,
        prompt_input=prompt_input,
        system_prompt=clean_system_prompt,
        conversation_history=rendered_conversation,
        relevant_memories=rendered_memories,
        tool_catalog=clean_tool_catalog,
    )


def assemble_prompt_input(
    user_request, conversation_history=None, relevant_memories=None
):
    """Combine memories, transcript, and current request into one input string."""
    clean_request = _validate_user_request(user_request)
    rendered_conversation = _normalize_conversation(conversation_history)
    rendered_memories = _normalize_memories(relevant_memories)

    if not rendered_conversation and not rendered_memories:
        return clean_request

    sections = []
    if rendered_memories:
        sections.append(f"{MEMORY_HEADER}\n{rendered_memories}")
    if rendered_conversation:
        sections.append(f"{CONVERSATION_HEADER}\n{rendered_conversation}")

    sections.append(f"{CURRENT_REQUEST_HEADER} {clean_request}")
    return "\n\n".join(sections)


def _validate_user_request(user_request):
    if not isinstance(user_request, str) or not user_request.strip():
        raise ValueError("User request cannot be empty.")
    return user_request.strip()


def _normalize_conversation(conversation_history):
    if conversation_history is None:
        return None

    if isinstance(conversation_history, ConversationContext):
        return conversation_history.render_transcript()

    if isinstance(conversation_history, str):
        return conversation_history.strip() or None

    if isinstance(conversation_history, (list, tuple)):
        if not conversation_history:
            return None
        lines = []
        for item in conversation_history:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                role, text = item
                label = "User" if str(role).lower() == "user" else "SIRIUS"
                lines.append(f"{label}: {str(text).strip()}")
            else:
                raise ValueError("Conversation items must be (role, text) pairs.")
        return "\n".join(lines) if lines else None

    raise ValueError(
        "Conversation history must be a string, ConversationContext, sequence of pairs, or None."
    )


def _normalize_memories(relevant_memories):
    if relevant_memories is None:
        return None

    if isinstance(relevant_memories, str):
        return relevant_memories.strip() or None

    if isinstance(relevant_memories, (list, tuple)):
        return render_memories(relevant_memories)

    raise ValueError(
        "Relevant memories must be a string, sequence of memory rows, or None."
    )


def _resolve_system_prompt(system_prompt=None, tool_catalog=None, today=None):
    if system_prompt is not None:
        if not isinstance(system_prompt, str):
            raise ValueError("System prompt must be a string or None.")
        return system_prompt.strip() or None

    if tool_catalog is not None:
        if not isinstance(tool_catalog, str):
            raise ValueError("Tool catalog must be a string or None.")
        clean_catalog = tool_catalog.strip()
        if not clean_catalog:
            return None
        return build_tool_system_prompt(clean_catalog, today=today)

    return None

