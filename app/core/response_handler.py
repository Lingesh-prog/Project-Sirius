"""Reliability and response-handling layer for SIRIUS AI interactions.

Establishes a deterministic contract for processing AI model outputs:
1. Valid structured tool requests -> validated and executed safely
2. Ordinary natural-language responses -> returned cleanly as text
3. Destructive tool requests -> routed to confirmation layer
4. Malformed tool requests / invalid JSON -> clean fallback message
5. Multiple tool requests -> rejected (only one action allowed at a time)
6. Provider failures / unexpected exceptions -> safe, graceful fallback

The AI never gains execution authority: all database mutations and tool calls
must pass through the strict validation and confirmation layers in core.tools.
"""

import json
import re

from app.ai import AIError
from app.core.tools import (
    DESTRUCTIVE_TOOLS,
    ToolResponseError,
    ToolValidationError,
    parse_tool_response,
    validate_tool_request,
)


EMPTY_RESPONSE_MESSAGE = "The AI returned an empty response."
UNEXPECTED_ERROR_MESSAGE = (
    "An unexpected error occurred while communicating with the AI assistant."
)
MULTIPLE_TOOLS_MESSAGE = (
    "I could not process that request. "
    "Multiple tool requests were returned, but only one action is allowed at a time."
)
DECLINED_REQUEST_MESSAGE = "I can only help with tasks and reminders right now."


def handle_ai_interaction(
    ai_client,
    context,
    database_path=None,
    execute_tool_fn=None,
    build_confirmation_fn=None,
):
    """Execute the AI request with full exception safety and process the response."""
    try:
        reply = ai_client.generate_text(
            context.user_request,
            system_prompt=context.system_prompt,
            conversation_history=context.conversation_history,
            relevant_memories=context.relevant_memories,
        )
    except AIError as error:
        return f"AI assistant is unavailable right now: {error}"
    except Exception:
        return UNEXPECTED_ERROR_MESSAGE

    return process_ai_response(
        reply,
        database_path=database_path,
        execute_tool_fn=execute_tool_fn,
        build_confirmation_fn=build_confirmation_fn,
    )


def process_ai_response(
    reply,
    database_path=None,
    execute_tool_fn=None,
    build_confirmation_fn=None,
):
    """Process an AI reply string according to the deterministic response contract."""
    if not isinstance(reply, str) or not reply.strip():
        return EMPTY_RESPONSE_MESSAGE

    clean_reply = reply.strip()

    # Detect if this is an attempted structured tool call or natural language
    if _is_attempted_tool_call(clean_reply):
        return _process_tool_call(
            clean_reply,
            database_path=database_path,
            execute_tool_fn=execute_tool_fn,
            build_confirmation_fn=build_confirmation_fn,
        )

    # Valid ordinary natural language response
    return clean_reply


def _is_attempted_tool_call(text):
    """Check if the text appears to be or contain a JSON tool request."""
    # Check for markdown code fences with json
    if re.search(r"```(?:json)?\s*\{", text, flags=re.IGNORECASE):
        return True

    # Check for JSON objects containing "tool" key
    if re.search(r'\{[^{}]*"tool"\s*:', text) or re.search(
        r'\[\s*\{[^{}]*"tool"', text
    ):
        return True

    # Check if text is a single JSON object
    if text.startswith("{") and text.endswith("}"):
        return True

    # Check if text is a JSON list
    if text.startswith("[") and text.endswith("]"):
        return True

    return False


def _process_tool_call(
    text,
    database_path=None,
    execute_tool_fn=None,
    build_confirmation_fn=None,
):
    """Parse, validate, and execute a structured tool request."""
    candidates = _extract_json_candidates(text)

    if len(candidates) > 1:
        return MULTIPLE_TOOLS_MESSAGE

    if len(candidates) == 1 and isinstance(candidates[0], list):
        if len(candidates[0]) > 1:
            return MULTIPLE_TOOLS_MESSAGE
        if len(candidates[0]) == 1 and isinstance(candidates[0][0], dict):
            raw_request = candidates[0][0]
        else:
            return "I could not process that request. The AI response was not valid JSON."
    elif len(candidates) == 1 and isinstance(candidates[0], dict):
        raw_request = candidates[0]
    else:
        try:
            tool, arguments = parse_tool_response(text)
            raw_request = {"tool": tool, "arguments": arguments}
        except ToolResponseError as error:
            return f"I could not process that request. {error}"

    tool = raw_request.get("tool")
    arguments = raw_request.get("arguments", {})

    if "tool" in raw_request and tool is None:
        return DECLINED_REQUEST_MESSAGE

    if not isinstance(tool, str) or not tool.strip():
        return "I could not process that request. The AI response is missing a tool name."

    if not isinstance(arguments, dict):
        return "I could not process that request. Tool arguments must be a JSON object."

    tool = tool.strip()

    try:
        validated_args = validate_tool_request(tool, arguments)
    except ToolValidationError as error:
        return f"That request is not supported: {error}"

    if tool in DESTRUCTIVE_TOOLS:
        if build_confirmation_fn is not None:
            return build_confirmation_fn(tool, validated_args, database_path)
        return f"Destructive tool '{tool}' requires confirmation."

    if execute_tool_fn is not None:
        return execute_tool_fn(tool, validated_args, database_path)

    return f"Tool '{tool}' validated successfully."


def _extract_json_candidates(text):
    """Extract all top-level JSON objects or arrays from text."""
    code_blocks = re.findall(
        r"```(?:json)?\s*([\s\S]*?)\s*```", text, flags=re.IGNORECASE
    )
    if code_blocks:
        results = []
        for block in code_blocks:
            results.extend(_decode_json_tokens(block.strip()))
        if results:
            return results

    return _decode_json_tokens(text)


def _decode_json_tokens(s):
    decoder = json.JSONDecoder()
    pos = 0
    results = []
    while pos < len(s):
        idx_brace = s.find("{", pos)
        idx_bracket = s.find("[", pos)

        if idx_brace == -1 and idx_bracket == -1:
            break
        elif idx_brace != -1 and (idx_bracket == -1 or idx_brace < idx_bracket):
            start = idx_brace
        else:
            start = idx_bracket

        try:
            obj, end = decoder.raw_decode(s, idx=start)
            results.append(obj)
            pos = end
        except json.JSONDecodeError:
            pos = start + 1
    return results

