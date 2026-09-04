"""Explicit SIRIUS tools, plus the validation and safety layer for AI requests.

The LLM can only *request* one of the tools defined here. Requests are parsed
from the model's JSON reply and validated before any service is called.
Destructive tools are never executed from the AI path; they always produce a
user confirmation prompt instead.

Automation tools (automation.open_url, automation.launch_app) are validated
here as well: only well-formed http/https URLs and identifiers from the fixed
application allowlist can ever pass this layer (Module 3.3).
"""

from datetime import datetime
import json
import re
from urllib.parse import urlsplit


TOOL_TASKS_ADD = "tasks.add"
TOOL_TASKS_LIST = "tasks.list"
TOOL_TASKS_COMPLETE = "tasks.complete"
TOOL_TASKS_UPDATE = "tasks.update"
TOOL_TASKS_DELETE = "tasks.delete"
TOOL_REMINDERS_ADD = "reminders.add"
TOOL_REMINDERS_LIST = "reminders.list"
TOOL_REMINDERS_COMPLETE = "reminders.complete"
TOOL_REMINDERS_DELETE = "reminders.delete"
TOOL_MEMORY_SAVE = "memory.save"
TOOL_MEMORY_LIST = "memory.list"
TOOL_MEMORY_SEARCH = "memory.search"
TOOL_MEMORY_DELETE = "memory.delete"
TOOL_AUTOMATION_OPEN_URL = "automation.open_url"
TOOL_AUTOMATION_LAUNCH_APP = "automation.launch_app"

# Tools that permanently remove data. Requests for these from the AI path are
# never executed directly; the user must confirm with an explicit command.
DESTRUCTIVE_TOOLS = frozenset(
    {TOOL_TASKS_DELETE, TOOL_REMINDERS_DELETE, TOOL_MEMORY_DELETE}
)

# Tools that change existing data and must receive at least one update field.
UPDATE_FIELD_TOOLS = frozenset({TOOL_TASKS_UPDATE})

TEXT_ARGUMENT = "text"
ID_ARGUMENT = "id"
PRIORITY_ARGUMENT = "priority"
DATETIME_ARGUMENT = "datetime"
DATE_TEXT_ARGUMENT = "date_text"
URL_ARGUMENT = "url"
APP_ARGUMENT = "app"

TOOL_ARGUMENT_SPECS = {
    TOOL_TASKS_ADD: {
        "title": (True, TEXT_ARGUMENT),
        "description": (False, TEXT_ARGUMENT),
        "due_date": (False, DATE_TEXT_ARGUMENT),
        "priority": (False, PRIORITY_ARGUMENT),
    },
    TOOL_TASKS_LIST: {},
    TOOL_TASKS_COMPLETE: {"task_id": (True, ID_ARGUMENT)},
    TOOL_TASKS_UPDATE: {
        "task_id": (True, ID_ARGUMENT),
        "title": (False, TEXT_ARGUMENT),
        "description": (False, TEXT_ARGUMENT),
        "due_date": (False, DATE_TEXT_ARGUMENT),
        "priority": (False, PRIORITY_ARGUMENT),
    },
    TOOL_TASKS_DELETE: {"task_id": (True, ID_ARGUMENT)},
    TOOL_REMINDERS_ADD: {
        "text": (True, TEXT_ARGUMENT),
        "remind_at": (True, DATETIME_ARGUMENT),
    },
    TOOL_REMINDERS_LIST: {},
    TOOL_REMINDERS_COMPLETE: {"reminder_id": (True, ID_ARGUMENT)},
    TOOL_REMINDERS_DELETE: {"reminder_id": (True, ID_ARGUMENT)},
    TOOL_MEMORY_SAVE: {
        "key": (True, TEXT_ARGUMENT),
        "value": (True, TEXT_ARGUMENT),
    },
    TOOL_MEMORY_LIST: {},
    TOOL_MEMORY_SEARCH: {"query": (True, TEXT_ARGUMENT)},
    TOOL_MEMORY_DELETE: {"memory_id": (True, ID_ARGUMENT)},
    TOOL_AUTOMATION_OPEN_URL: {"url": (True, URL_ARGUMENT)},
    TOOL_AUTOMATION_LAUNCH_APP: {"app": (True, APP_ARGUMENT)},
}

VALID_PRIORITIES = ("low", "medium", "high")

# Module 3.3 safe automation allowlist: the only applications SIRIUS can
# launch, each with its fixed Windows executable. Validation accepts exactly
# these identifiers (case-insensitively) and nothing else -- no paths, no
# shell commands, no arguments, and no arbitrary executables.
SAFE_AUTOMATION_APPS = {
    "notepad": {"display_name": "Notepad", "executable": "notepad.exe"},
    "calculator": {"display_name": "Calculator", "executable": "calc.exe"},
}

# The only URL schemes the automation layer may open; every other scheme
# (file, javascript, data, custom protocol handlers, ...) is rejected before
# any OS call happens.
ALLOWED_URL_SCHEMES = ("http", "https")


class ToolValidationError(ValueError):
    """A tool request failed the validation/safety layer."""


class ToolResponseError(ValueError):
    """The AI reply could not be parsed into a tool request."""


def parse_tool_response(text):
    """Extract one ``{"tool": ..., "arguments": {...}}`` request from an AI reply.

    Returns ``(None, {})`` when the AI explicitly reports that the request
    matches no SIRIUS tool.
    """
    if not isinstance(text, str) or not text.strip():
        raise ToolResponseError("The AI returned an empty response.")

    match = re.search(r"\{.*\}", text.strip(), flags=re.DOTALL)
    if match is None:
        raise ToolResponseError("The AI response did not contain a JSON object.")

    try:
        request = json.loads(match.group(0))
    except json.JSONDecodeError as error:
        raise ToolResponseError("The AI response was not valid JSON.") from error

    if not isinstance(request, dict):
        raise ToolResponseError("The AI response must be one JSON object.")

    tool = request.get("tool")
    arguments = request.get("arguments", {})

    if "tool" in request and tool is None:
        return None, {}
    if not isinstance(tool, str) or not tool.strip():
        raise ToolResponseError("The AI response is missing a tool name.")
    if not isinstance(arguments, dict):
        raise ToolResponseError("Tool arguments must be a JSON object.")

    return tool.strip(), arguments


def validate_tool_request(tool, arguments):
    """Validate a tool request and return its normalized arguments.

    Raises ``ToolValidationError`` for unknown tools, unknown arguments,
    missing required arguments, or values of the wrong shape. Normalization
    happens before any service is called.
    """
    if tool not in TOOL_ARGUMENT_SPECS:
        raise ToolValidationError(f"Unknown tool '{tool}'.")

    if not isinstance(arguments, dict):
        raise ToolValidationError("Tool arguments must be a JSON object.")

    spec = TOOL_ARGUMENT_SPECS[tool]
    for name in arguments:
        if name not in spec:
            raise ToolValidationError(f"Unknown argument '{name}' for tool '{tool}'.")

    normalized = {}
    for name, (required, kind) in spec.items():
        value = arguments.get(name)
        if value is None or (isinstance(value, str) and not value.strip()):
            if required:
                raise ToolValidationError(
                    f"Missing required argument '{name}' for tool '{tool}'."
                )
            continue
        normalized[name] = _coerce_argument(tool, name, kind, value)

    if tool in UPDATE_FIELD_TOOLS:
        update_fields = [
            name for name, (required, _kind) in spec.items() if not required
        ]
        if not any(name in normalized for name in update_fields):
            raise ToolValidationError(
                f"At least one field to update must be supplied for tool '{tool}'."
            )

    return normalized


def build_tool_catalog():
    """Return a short catalog of the allowed tools for the AI system prompt."""
    hints = {
        TEXT_ARGUMENT: "<text>",
        ID_ARGUMENT: "<id>",
        PRIORITY_ARGUMENT: "Low|Medium|High",
        DATETIME_ARGUMENT: "<YYYY-MM-DDTHH:MM>",
        DATE_TEXT_ARGUMENT: "<YYYY-MM-DD or text>",
        URL_ARGUMENT: "<http or https URL>",
        APP_ARGUMENT: "<allowlisted app>",
    }

    lines = []
    for tool, spec in TOOL_ARGUMENT_SPECS.items():
        if not spec:
            lines.append(f"- {tool}()")
            continue
        parts = [
            f"{name}: {hints[kind]}" + ("" if required else " (optional)")
            for name, (required, kind) in spec.items()
        ]
        lines.append(f"- {tool}({', '.join(parts)})")
    return "\n".join(lines)


def _coerce_argument(tool, name, kind, value):
    if kind in (TEXT_ARGUMENT, DATE_TEXT_ARGUMENT):
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise ToolValidationError(f"Argument '{name}' of '{tool}' must be text.")
        return str(value).strip()

    if kind == ID_ARGUMENT:
        if isinstance(value, bool):
            raise ToolValidationError(
                f"Argument '{name}' of '{tool}' must be a whole number."
            )
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
        raise ToolValidationError(
            f"Argument '{name}' of '{tool}' must be a whole number."
        )

    if kind == PRIORITY_ARGUMENT:
        if not isinstance(value, str) or value.strip().lower() not in VALID_PRIORITIES:
            allowed = ", ".join(priority.capitalize() for priority in VALID_PRIORITIES)
            raise ToolValidationError(
                f"Argument '{name}' of '{tool}' must be {allowed}."
            )
        return value.strip().lower().capitalize()

    if kind == DATETIME_ARGUMENT:
        if not isinstance(value, str) or ("T" not in value and " " not in value):
            raise ToolValidationError(
                f"Argument '{name}' of '{tool}' must be an ISO datetime "
                "like 2026-09-01T10:00."
            )
        try:
            datetime.fromisoformat(value)
        except ValueError as error:
            raise ToolValidationError(
                f"Argument '{name}' of '{tool}' must be an ISO datetime "
                "like 2026-09-01T10:00."
            ) from error
        return value

    if kind == URL_ARGUMENT:
        if isinstance(value, bool) or not isinstance(value, str):
            raise ToolValidationError(
                f"Argument '{name}' of '{tool}' must be a URL string."
            )
        return _coerce_url(tool, name, value.strip())

    if kind == APP_ARGUMENT:
        if isinstance(value, bool) or not isinstance(value, str):
            raise ToolValidationError(
                f"Argument '{name}' of '{tool}' must be an application name."
            )
        identifier = value.strip().lower()
        if identifier not in SAFE_AUTOMATION_APPS:
            allowed = ", ".join(
                f"{info['display_name']} ({app_name})"
                for app_name, info in sorted(SAFE_AUTOMATION_APPS.items())
            )
            raise ToolValidationError(
                f"Argument '{name}' of '{tool}' must be one of the applications "
                f"SIRIUS can launch: {allowed}."
            )
        return identifier

    raise ToolValidationError(f"Argument '{name}' of '{tool}' has an unknown type.")


def _coerce_url(tool, name, url):
    """Accept only well-formed absolute http(s) URLs; reject everything else."""
    if not url:
        raise ToolValidationError(f"Argument '{name}' of '{tool}' must not be empty.")
    if any(character.isspace() for character in url):
        raise ToolValidationError(
            f"Argument '{name}' of '{tool}' must be a URL without whitespace."
        )
    try:
        parts = urlsplit(url)
    except ValueError as error:
        raise ToolValidationError(
            f"Argument '{name}' of '{tool}' must be a well-formed URL."
        ) from error
    if parts.scheme.lower() not in ALLOWED_URL_SCHEMES:
        allowed = " or ".join(f"{scheme}://" for scheme in ALLOWED_URL_SCHEMES)
        raise ToolValidationError(
            f"Argument '{name}' of '{tool}' must be an {allowed} URL; "
            "other URL schemes are not allowed."
        )
    if not parts.netloc:
        raise ToolValidationError(
            f"Argument '{name}' of '{tool}' must be an absolute URL that "
            "includes a host."
        )
    return url