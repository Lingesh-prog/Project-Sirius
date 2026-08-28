"""Terminal interface for the Sirius Focus task tool."""

from app.ai import AIConfigurationError, create_ai_client
from app.core.assistant import format_tasks, handle_command
from app.tools.tasks.service import add_task, complete_task, delete_task, get_tasks


def _create_optional_ai_client():
    """Return an AI client when configured, or None when AI stays disabled."""
    try:
        return create_ai_client()
    except AIConfigurationError:
        return None


def display_tasks():
    print(f"\n{format_tasks(get_tasks())}")


def create_task():
    print("\n========== NEW TASK ==========")

    title = input("Task title: ").strip()

    if not title:
        print("Task title cannot be empty.")
        return

    description = input("Description (optional): ").strip()
    due_date = input("Due date (YYYY-MM-DD, optional): ").strip()

    print("\nPriority:")
    print("1. Low")
    print("2. Medium")
    print("3. High")

    priority_choice = input("Choose priority: ").strip()

    priorities = {
        "1": "Low",
        "2": "Medium",
        "3": "High",
    }

    priority = priorities.get(priority_choice, "Medium")

    task_id = add_task(
        title=title,
        description=description,
        due_date=due_date or None,
        priority=priority,
    )

    print(f"\nTask created successfully! ID: {task_id}")


def complete_existing_task():
    display_tasks()

    try:
        task_id = int(input("\nEnter task ID to complete: "))
    except ValueError:
        print("Please enter a valid task ID.")
        return
        return

    if complete_task(task_id):
        print("Task completed!")
    else:
        print("Task not found.")


def delete_existing_task():
    display_tasks()

    try:
        task_id = int(input("\nEnter task ID to delete: "))
    except ValueError:
        print("Please enter a valid task ID.")

    if delete_task(task_id):
        print("Task deleted.")
    else:
        print("Task not found.")


def show_menu():
    print("""
+--------------------------------+
|         PROJECT SIRIUS         |
|          SIRIUS FOCUS          |
+--------------------------------+

1. Add Task
2. View Tasks
3. Complete Task
4. Delete Task
5. Exit
""")


def run():
    """Run the Sirius Focus terminal menu."""
    print("\nSirius Focus v0.1 initialized.")
    print("Your personal task assistant is ready.")

    ai_client = _create_optional_ai_client()
    if ai_client is None:
        print("Natural-language AI mode is off (missing AI configuration).")
    else:
        print("Natural-language AI mode is on.")

    while True:
        show_menu()

        choice = input("Choose an option or enter a task command: ").strip()

        if choice == "1":
            create_task()
        elif choice == "2":
            display_tasks()
        elif choice == "3":
            complete_existing_task()
        elif choice == "4":
            delete_existing_task()
        elif choice == "5":
            print("\nSirius shutting down...")
            print("Goodbye.")
            break
        else:
            print(f"\n{handle_command(choice, ai_client=ai_client)}")
