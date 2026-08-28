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