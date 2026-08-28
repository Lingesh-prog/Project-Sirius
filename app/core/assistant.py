"""Assistant that coordinates the Sirius Focus tools."""

from datetime import datetime

from app.ai import AIError
from app.ai.prompts import build_tool_system_prompt
from app.core.intents import (
    ADD_REMINDER,
    ADD_TASK,
    COMPLETE_REMINDER,
    COMPLETE_TASK,
    CONFIRM_DELETE_MEMORY,
    CONFIRM_DELETE_REMINDER,
    CONFIRM_DELETE_TASK,
    DELETE_REMINDER,
    DELETE_TASK,
    LIST_REMINDERS,
    LIST_TASKS,
    route_command,
)
from app.core.tools import (
    DESTRUCTIVE_TOOLS,
    TOOL_MEMORY_DELETE,
    TOOL_MEMORY_LIST,
    TOOL_MEMORY_SAVE,
    TOOL_REMINDERS_ADD,
    TOOL_REMINDERS_COMPLETE,
    TOOL_REMINDERS_DELETE,
    TOOL_REMINDERS_LIST,
    TOOL_TASKS_ADD,
    TOOL_TASKS_COMPLETE,
    TOOL_TASKS_DELETE,
    TOOL_TASKS_LIST,
    TOOL_TASKS_UPDATE,
    ToolResponseError,
    ToolValidationError,
    build_tool_catalog,
    parse_tool_response,
    validate_tool_request,
)
from app.tools.memory import service as memory_service
from app.tools.reminders import service as reminder_service
from app.tools.tasks import service


UNKNOWN_COMMAND_MESSAGE = (
    "Unknown command. Try: add task <title>, list tasks, "
    "complete task <id>, or delete task <id>, "
    "add reminder <text> at <YYYY-MM-DDTHH:MM>, list reminders, "
    "complete reminder <id>, or delete reminder <id>."
)


def format_tasks(tasks):
    """Format task rows returned by the existing task service for the terminal."""
    if not tasks:
        return "No tasks found."

    lines = ["========== YOUR TASKS =========="]
    for task_id, title, description, due_date, priority, status, _created_at in tasks:
        lines.extend((
            f"[{task_id}] {title}",
            f"    Priority : {priority}",
            f"    Status   : {status}",
            f"    Due      : {due_date or 'No deadline'}",
        ))
        if description:
            lines.append(f"    Details  : {description}")
    lines.append("================================")
    return "\n".join(lines)


def format_reminders(reminders):
    """Format reminder rows returned by the reminder service for the terminal."""
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


def format_memories(memories):
    """Format memory rows returned by the memory service for the terminal."""
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


def handle_command(command, database_path=None, ai_client=None, conversation=None):
    """Execute one command and record the exchange in the conversation context."""
    response = _resolve_command(
        command,
        database_path=database_path,
        ai_client=ai_client,
        conversation=conversation,
    )

    if conversation is not None:
        conversation.add_user_message(command)
        conversation.add_assistant_message(response)

    return response


def _resolve_command(command, database_path=None, ai_client=None, conversation=None):
    """Route and execute one command without touching conversation context."""
    intent = route_command(command)

    if intent.name == ADD_TASK:
        task_id = service.add_task(intent.title, database_path=database_path)
        return f"Task created successfully! ID: {task_id}"

    if intent.name == ADD_REMINDER:
        try:
            reminder_id = reminder_service.create_reminder(
                intent.text, intent.remind_at, database_path=database_path
            )
        except ValueError as error:
            return f"Reminder not created. {error}"
        return f"Reminder created successfully! ID: {reminder_id}"

    if intent.name == LIST_TASKS:
        return format_tasks(service.get_tasks(database_path=database_path))

    if intent.name == LIST_REMINDERS:
        return format_reminders(
            reminder_service.list_reminders(database_path=database_path)
        )

    if intent.name == COMPLETE_TASK:
        if service.complete_task(intent.task_id, database_path=database_path):
            return "Task completed!"
        return "Task not found."

    if intent.name == DELETE_TASK:
        if service.delete_task(intent.task_id, database_path=database_path):
            return "Task deleted."
        return "Task not found."

    if intent.name in (DELETE_TASK, CONFIRM_DELETE_TASK):
        if service.delete_task(intent.task_id, database_path=database_path):
            return "Task deleted."
        return "Task not found."

    if intent.name == COMPLETE_REMINDER:
        if reminder_service.mark_reminder_completed(
            intent.reminder_id, database_path=database_path
        ):
            return "Reminder completed!"
        return "Reminder not found."

    if intent.name in (DELETE_REMINDER, CONFIRM_DELETE_REMINDER):
        if reminder_service.delete_reminder(
            intent.reminder_id, database_path=database_path
        ):
            return "Reminder deleted."
        return "Reminder not found."

    if intent.name == CONFIRM_DELETE_MEMORY:
        if memory_service.delete_memory(
            intent.memory_id, database_path=database_path
        ):
            return "Memory deleted."
        return "Memory not found."

    return _handle_unrecognized(command, ai_client, database_path, conversation)


def _handle_unrecognized(command, ai_client, database_path, conversation=None):
    """Route unrecognized input to the AI tool path when AI is configured."""
    if ai_client is None:
        return UNKNOWN_COMMAND_MESSAGE

    return _handle_ai_request(command, ai_client, database_path, conversation)


def _handle_ai_request(command, ai_client, database_path, conversation=None):
    """Turn natural language into a validated tool request and run it safely."""
    system_prompt = build_tool_system_prompt(
        build_tool_catalog(), today=datetime.now().strftime("%Y-%m-%d (%A)")
    )
    conversation_history = (
        conversation.render_transcript() if conversation is not None else None
    )

    try:
        reply = ai_client.generate_text(
            command,
            system_prompt=system_prompt,
            conversation_history=conversation_history,
        )
    except AIError as error:
        return f"AI assistant is unavailable right now: {error}"

    try:
        tool, arguments = parse_tool_response(reply)
    except ToolResponseError as error:
        return f"I could not process that request. {error}"

    if tool is None:
        return "I can only help with tasks and reminders right now."

    try:
        arguments = validate_tool_request(tool, arguments)
    except ToolValidationError as error:
        return f"That request is not supported: {error}"

    if tool in DESTRUCTIVE_TOOLS:
        return _build_destructive_confirmation(tool, arguments, database_path)

    return _execute_tool(tool, arguments, database_path)


def _execute_tool(tool, arguments, database_path):
    """Run a validated, non-destructive tool through the existing services."""
    if tool == TOOL_TASKS_ADD:
        task_id = service.add_task(
            arguments["title"],
            description=arguments.get("description", ""),
            due_date=arguments.get("due_date"),
            priority=arguments.get("priority", "Medium"),
            database_path=database_path,
        )
        return f"Task created successfully! ID: {task_id}"

    if tool == TOOL_TASKS_LIST:
        return format_tasks(service.get_tasks(database_path=database_path))

    if tool == TOOL_TASKS_COMPLETE:
        if service.complete_task(arguments["task_id"], database_path=database_path):
            return "Task completed!"
        return "Task not found."

    if tool == TOOL_TASKS_UPDATE:
        task_id = arguments.pop("task_id")
        try:
            if service.update_task(task_id, database_path=database_path, **arguments):
                return "Task updated."
            return "Task not found."
        except ValueError as error:
            return f"Task not updated. {error}"

    if tool == TOOL_REMINDERS_ADD:
        try:
            reminder_id = reminder_service.create_reminder(
                arguments["text"], arguments["remind_at"], database_path=database_path
            )
        except ValueError as error:
            return f"Reminder not created. {error}"
        return f"Reminder created successfully! ID: {reminder_id}"

    if tool == TOOL_REMINDERS_LIST:
        return format_reminders(
            reminder_service.list_reminders(database_path=database_path)
        )

    if tool == TOOL_REMINDERS_COMPLETE:
        if reminder_service.mark_reminder_completed(
            arguments["reminder_id"], database_path=database_path
        ):
            return "Reminder completed!"
        return "Reminder not found."

    if tool == TOOL_MEMORY_SAVE:
        try:
            memory_id = memory_service.save_memory(
                arguments["key"], arguments["value"], database_path=database_path
            )
        except ValueError as error:
            return f"Memory not saved. {error}"
        return f"Memory saved with ID: {memory_id}."

    if tool == TOOL_MEMORY_LIST:
        return format_memories(
            memory_service.list_memories(database_path=database_path)
        )

    # Destructive tools never reach the executor; they always stop at the
    # confirmation layer above. This line is defense in depth.
    return UNKNOWN_COMMAND_MESSAGE


def _build_destructive_confirmation(tool, arguments, database_path):
    """Ask the user to confirm a destructive AI request explicitly.

    The AI path never executes destructive tools; deletion happens only
    after the user replies with the exact deterministic confirm command.
    """
    if tool == TOOL_TASKS_DELETE:
        task_id = arguments["task_id"]
        target = _describe_task(task_id, database_path)
        confirm_command = f"confirm delete task {task_id}"
    elif tool == TOOL_REMINDERS_DELETE:
        reminder_id = arguments["reminder_id"]
        target = _describe_reminder(reminder_id, database_path)
        confirm_command = f"confirm delete reminder {reminder_id}"
    else:
        memory_id = arguments["memory_id"]
        target = _describe_memory(memory_id, database_path)
        confirm_command = f"confirm delete memory {memory_id}"

    return (
        f"You asked me to delete {target}. This cannot be undone.\n"
        f"To confirm, reply exactly: {confirm_command}\n"
        "Any other reply cancels the deletion."
    )


def _describe_task(task_id, database_path):
    for task in service.get_tasks(database_path=database_path):
        if task[0] == task_id:
            return f"task {task_id} ('{task[1]}')"
    return f"task {task_id}"


def _describe_reminder(reminder_id, database_path):
    for reminder in reminder_service.list_reminders(database_path=database_path):
        if reminder[0] == reminder_id:
            return f"reminder {reminder_id} ('{reminder[1]}')"
    return f"reminder {reminder_id}"


def _describe_memory(memory_id, database_path):
    for memory in memory_service.list_memories(database_path=database_path):
        if memory[0] == memory_id:
            return f"memory {memory_id} ('{memory[1]}')"
    return f"memory {memory_id}"
