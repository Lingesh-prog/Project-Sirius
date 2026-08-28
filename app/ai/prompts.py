"""Prompt templates for the SIRIUS assistant.

Module 2.1 keeps prompts minimal: one system prompt that defines who SIRIUS
is. Tool-calling and memory prompts arrive with later modules.
"""

SIRIUS_SYSTEM_PROMPT = (
    "You are SIRIUS, a personal assistant that helps with everyday tasks "
    "and reminders. Answer clearly and briefly. You provide information "
    "and suggestions only; you cannot run commands or change anything."
)


def build_system_prompt(extra_instructions=None):
    """Return the SIRIUS system prompt, optionally extended with extra text."""
    if not extra_instructions:
        return SIRIUS_SYSTEM_PROMPT

    return f"{SIRIUS_SYSTEM_PROMPT}\n{extra_instructions.strip()}"


TOOL_CALLING_SYSTEM_PROMPT = (
    "You are the tool dispatcher inside SIRIUS, a personal assistant.\n"
    "Choose exactly one tool from the catalog below and reply with ONLY one\n"
    'JSON object of the form {"tool": "<tool name>", "arguments": {...}}.\n'
    "Rules:\n"
    "- Use the exact tool names and argument names from the catalog.\n"
    "- Convert relative dates and times into ISO format (YYYY-MM-DDTHH:MM)\n"
    "  using the current date provided below.\n"
    '- If the request does not match any tool, reply {"tool": null, "arguments": {}}.\n'
    "- Never invent tools or arguments, and never add explanations or markdown.\n"
    "SIRIUS itself confirms every destructive action with the user; you never\n"
    "execute anything."
)


def build_tool_system_prompt(tool_catalog, today=None):
    """Return the system prompt that turns user text into tool requests."""
    prompt = TOOL_CALLING_SYSTEM_PROMPT
    if today:
        prompt = f"{prompt}\nCurrent date: {today}"

    return f"{prompt}\n\nTool catalog:\n{tool_catalog}"