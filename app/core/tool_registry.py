"""Object-oriented Tool specification and Registry for SIRIUS.

Provides:
- SafetyTier (READ_ONLY, STATE_MODIFYING, DESTRUCTIVE)
- Tool specification containing metadata, argument schema, safety tier, and executor
- ToolRegistry for dynamic registration, validation, and execution of tools
- build_default_registry() pre-configured with all 13 standard SIRIUS tools
"""

from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from app.core.tools import (
    DESTRUCTIVE_TOOLS,
    TOOL_ARGUMENT_SPECS,
    TOOL_MEMORY_DELETE,
    TOOL_MEMORY_LIST,
    TOOL_MEMORY_SAVE,
    TOOL_MEMORY_SEARCH,
    TOOL_REMINDERS_ADD,
    TOOL_REMINDERS_COMPLETE,
    TOOL_REMINDERS_DELETE,
    TOOL_REMINDERS_LIST,
    TOOL_TASKS_ADD,
    TOOL_TASKS_COMPLETE,
    TOOL_TASKS_DELETE,
    TOOL_TASKS_LIST,
    TOOL_TASKS_UPDATE,
    ToolValidationError,
    validate_tool_request,
)
from app.tools.memory import service as memory_service
from app.tools.reminders import service as reminder_service
from app.tools.tasks import service as task_service


class SafetyTier(str, Enum):
    """Safety classification for tools."""

    READ_ONLY = "read_only"
    STATE_MODIFYING = "state_modifying"
    DESTRUCTIVE = "destructive"


class Tool:
    """Specification and executor for a single SIRIUS tool."""

    def __init__(
        self,
        name: str,
        description: str,
        argument_spec: Dict[str, Any],
        safety_tier: SafetyTier,
        executor: Optional[Callable[[Dict[str, Any], Optional[str]], Any]] = None,
    ):
        self.name = name
        self.description = description
        self.argument_spec = argument_spec
        self.safety_tier = safety_tier
        self.executor = executor

    def validate(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and normalize arguments for this tool."""
        return validate_tool_request(self.name, arguments)

    def execute(
        self, arguments: Dict[str, Any], database_path: Optional[str] = None
    ) -> Any:
        """Validate arguments and invoke the executor."""
        validated_args = self.validate(arguments)
        if self.executor is None:
            raise RuntimeError(f"Tool '{self.name}' has no executor configured.")
        return self.executor(validated_args, database_path=database_path)

    def __repr__(self) -> str:
        return f"Tool(name={self.name!r}, safety_tier={self.safety_tier.value!r})"


class ToolRegistry:
    """Registry for managing and looking up available SIRIUS tools."""

    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a new tool or overwrite an existing tool."""
        if not isinstance(tool, Tool):
            raise TypeError("tool must be an instance of Tool")
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> Optional[Tool]:
        """Remove a tool by name and return it, or None if not found."""
        return self._tools.pop(name, None)

    def get(self, name: str) -> Optional[Tool]:
        """Retrieve a tool by name, or None if not found."""
        return self._tools.get(name)

    def has(self, name: str) -> bool:
        """Check if a tool with the given name is registered."""
        return name in self._tools

    def list_tools(self) -> List[Tool]:
        """Return a list of all registered tools."""
        return list(self._tools.values())

    def get_tool_names(self) -> List[str]:
        """Return a list of all registered tool names."""
        return list(self._tools.keys())

    def validate_tool_call(
        self, name: str, arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Validate arguments against the registered tool schema."""
        tool = self.get(name)
        if tool is None:
            raise ToolValidationError(f"Unknown tool '{name}'.")
        return tool.validate(arguments)

    def execute(
        self,
        name: str,
        arguments: Dict[str, Any],
        database_path: Optional[str] = None,
    ) -> Any:
        """Execute a registered tool by name with arguments."""
        tool = self.get(name)
        if tool is None:
            raise ToolValidationError(f"Unknown tool '{name}'.")
        return tool.execute(arguments, database_path=database_path)


# Default Formatting Helpers (mirrors assistant formatting exactly)
def _format_tasks(tasks):
    if not tasks:
        return "No tasks found."
    lines = ["========== YOUR TASKS =========="]
    for task_id, title, description, due_date, priority, status, _created_at in tasks:
        lines.append(f"[{task_id}] {title}")
        if description:
            lines.append(f"    Description: {description}")
        if due_date:
            lines.append(f"    Due date   : {due_date}")
        lines.append(f"    Priority   : {priority}")
        lines.append(f"    Status     : {status}")
    lines.append("================================")
    return "\n".join(lines)


def _format_reminders(reminders):
    if not reminders:
        return "No reminders found."
    lines = ["========== YOUR REMINDERS =========="]
    for reminder_id, text, remind_at, status, _created_at in reminders:
        lines.extend((
            f"[{reminder_id}] {text}",
            f"    Remind at: {remind_at}",
            f"    Status   : {status}",
        ))
    lines.append("====================================")
    return "\n".join(lines)


def _format_memories(memories):
    if not memories:
        return "No memories found."
    lines = ["========== YOUR MEMORIES =========="]
    for memory_id, key, value, _created_at, _updated_at in memories:
        lines.extend((
            f"[{memory_id}] {key}",
            f"    Value    : {value}",
        ))
    lines.append("===================================")
    return "\n".join(lines)


def build_default_registry() -> ToolRegistry:
    """Construct a ToolRegistry containing all 13 standard SIRIUS tools."""
    registry = ToolRegistry()

    # Tasks tools
    registry.register(
        Tool(
            name=TOOL_TASKS_ADD,
            description="Add a new task with title, optional description, due date, and priority.",
            argument_spec=TOOL_ARGUMENT_SPECS[TOOL_TASKS_ADD],
            safety_tier=SafetyTier.STATE_MODIFYING,
            executor=lambda args, database_path=None: (
                f"Task created successfully! ID: {task_service.add_task(args['title'], description=args.get('description', ''), due_date=args.get('due_date'), priority=args.get('priority', 'Medium'), database_path=database_path)}"
            ),
        )
    )

    registry.register(
        Tool(
            name=TOOL_TASKS_LIST,
            description="List all existing tasks sorted by priority.",
            argument_spec=TOOL_ARGUMENT_SPECS[TOOL_TASKS_LIST],
            safety_tier=SafetyTier.READ_ONLY,
            executor=lambda args, database_path=None: (
                _format_tasks(task_service.get_tasks(database_path=database_path))
            ),
        )
    )

    registry.register(
        Tool(
            name=TOOL_TASKS_COMPLETE,
            description="Mark an existing task as completed by its ID.",
            argument_spec=TOOL_ARGUMENT_SPECS[TOOL_TASKS_COMPLETE],
            safety_tier=SafetyTier.STATE_MODIFYING,
            executor=lambda args, database_path=None: (
                "Task completed!"
                if task_service.complete_task(
                    args["task_id"], database_path=database_path
                )
                else "Task not found."
            ),
        )
    )

    def _exec_task_update(args, database_path=None):
        kwargs = dict(args)
        task_id = kwargs.pop("task_id")
        try:
            if task_service.update_task(
                task_id, database_path=database_path, **kwargs
            ):
                return "Task updated."
            return "Task not found."
        except ValueError as error:
            return f"Task not updated. {error}"

    registry.register(
        Tool(
            name=TOOL_TASKS_UPDATE,
            description="Update title, description, due date, or priority of an existing task.",
            argument_spec=TOOL_ARGUMENT_SPECS[TOOL_TASKS_UPDATE],
            safety_tier=SafetyTier.STATE_MODIFYING,
            executor=_exec_task_update,
        )
    )

    registry.register(
        Tool(
            name=TOOL_TASKS_DELETE,
            description="Permanently delete a task by its ID (destructive).",
            argument_spec=TOOL_ARGUMENT_SPECS[TOOL_TASKS_DELETE],
            safety_tier=SafetyTier.DESTRUCTIVE,
            executor=lambda args, database_path=None: (
                "Task deleted."
                if task_service.delete_task(
                    args["task_id"], database_path=database_path
                )
                else "Task not found."
            ),
        )
    )

    # Reminders tools
    def _exec_reminder_add(args, database_path=None):
        try:
            reminder_id = reminder_service.create_reminder(
                args["text"], args["remind_at"], database_path=database_path
            )
            return f"Reminder created successfully! ID: {reminder_id}"
        except ValueError as error:
            return f"Reminder not created. {error}"

    registry.register(
        Tool(
            name=TOOL_REMINDERS_ADD,
            description="Create a timed reminder with text and ISO datetime.",
            argument_spec=TOOL_ARGUMENT_SPECS[TOOL_REMINDERS_ADD],
            safety_tier=SafetyTier.STATE_MODIFYING,
            executor=_exec_reminder_add,
        )
    )

    registry.register(
        Tool(
            name=TOOL_REMINDERS_LIST,
            description="List all active reminders.",
            argument_spec=TOOL_ARGUMENT_SPECS[TOOL_REMINDERS_LIST],
            safety_tier=SafetyTier.READ_ONLY,
            executor=lambda args, database_path=None: (
                _format_reminders(
                    reminder_service.list_reminders(database_path=database_path)
                )
            ),
        )
    )

    registry.register(
        Tool(
            name=TOOL_REMINDERS_COMPLETE,
            description="Mark a reminder as completed by its ID.",
            argument_spec=TOOL_ARGUMENT_SPECS[TOOL_REMINDERS_COMPLETE],
            safety_tier=SafetyTier.STATE_MODIFYING,
            executor=lambda args, database_path=None: (
                "Reminder completed!"
                if reminder_service.mark_reminder_completed(
                    args["reminder_id"], database_path=database_path
                )
                else "Reminder not found."
            ),
        )
    )

    registry.register(
        Tool(
            name=TOOL_REMINDERS_DELETE,
            description="Permanently delete a reminder by its ID (destructive).",
            argument_spec=TOOL_ARGUMENT_SPECS[TOOL_REMINDERS_DELETE],
            safety_tier=SafetyTier.DESTRUCTIVE,
            executor=lambda args, database_path=None: (
                "Reminder deleted."
                if reminder_service.delete_reminder(
                    args["reminder_id"], database_path=database_path
                )
                else "Reminder not found."
            ),
        )
    )

    # Memory tools
    def _exec_memory_save(args, database_path=None):
        try:
            memory_id = memory_service.save_memory(
                args["key"], args["value"], database_path=database_path
            )
            return f"Memory saved with ID: {memory_id}."
        except ValueError as error:
            return f"Memory not saved. {error}"

    registry.register(
        Tool(
            name=TOOL_MEMORY_SAVE,
            description="Save a key-value fact into persistent memory.",
            argument_spec=TOOL_ARGUMENT_SPECS[TOOL_MEMORY_SAVE],
            safety_tier=SafetyTier.STATE_MODIFYING,
            executor=_exec_memory_save,
        )
    )

    registry.register(
        Tool(
            name=TOOL_MEMORY_LIST,
            description="List all stored key-value memories.",
            argument_spec=TOOL_ARGUMENT_SPECS[TOOL_MEMORY_LIST],
            safety_tier=SafetyTier.READ_ONLY,
            executor=lambda args, database_path=None: (
                _format_memories(
                    memory_service.list_memories(database_path=database_path)
                )
            ),
        )
    )

    def _exec_memory_search(args, database_path=None):
        try:
            memories = memory_service.search_memories(
                args["query"], database_path=database_path
            )
        except ValueError as error:
            return f"Memory search failed. {error}"
        if not memories:
            return "No matching memories found."
        return _format_memories(memories)

    registry.register(
        Tool(
            name=TOOL_MEMORY_SEARCH,
            description="Search persistent memories matching a substring query.",
            argument_spec=TOOL_ARGUMENT_SPECS[TOOL_MEMORY_SEARCH],
            safety_tier=SafetyTier.READ_ONLY,
            executor=_exec_memory_search,
        )
    )

    registry.register(
        Tool(
            name=TOOL_MEMORY_DELETE,
            description="Permanently delete a memory fact by ID (destructive).",
            argument_spec=TOOL_ARGUMENT_SPECS[TOOL_MEMORY_DELETE],
            safety_tier=SafetyTier.DESTRUCTIVE,
            executor=lambda args, database_path=None: (
                "Memory deleted."
                if memory_service.delete_memory(
                    args["memory_id"], database_path=database_path
                )
                else "Memory not found."
            ),
        )
    )

    return registry
