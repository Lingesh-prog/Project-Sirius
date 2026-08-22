from database import initialize_database
from task_manager import add_task, get_tasks, complete_task, delete_task


def display_tasks():
    tasks = get_tasks()

    if not tasks:
        print("\nNo tasks found.")
        return

    print("\n========== YOUR TASKS ==========")

    for task in tasks:
        task_id, title, description, due_date, priority, status, created_at = task

        print(f"\n[{task_id}] {title}")
        print(f"    Priority : {priority}")
        print(f"    Status   : {status}")
        print(f"    Due      : {due_date or 'No deadline'}")

        if description:
            print(f"    Details  : {description}")

    print("\n================================")


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
        "3": "High"
    }

    priority = priorities.get(priority_choice, "Medium")

    task_id = add_task(
        title=title,
        description=description,
        due_date=due_date or None,
        priority=priority
    )

    print(f"\n✅ Task created successfully! ID: {task_id}")


def complete_existing_task():
    display_tasks()

    try:
        task_id = int(input("\nEnter task ID to complete: "))
    except ValueError:
        print("Please enter a valid task ID.")
        return

    if complete_task(task_id):
        print("✅ Task completed!")
    else:
        print("❌ Task not found.")


def delete_existing_task():
    display_tasks()

    try:
        task_id = int(input("\nEnter task ID to delete: "))
    except ValueError:
        print("Please enter a valid task ID.")
        return

    if delete_task(task_id):
        print("🗑️ Task deleted.")
    else:
        print("❌ Task not found.")


def show_menu():
    print("""
╔══════════════════════════════════╗
║         PROJECT SIRIUS           ║
║          SIRIUS FOCUS            ║
╚══════════════════════════════════╝

1. Add Task
2. View Tasks
3. Complete Task
4. Delete Task
5. Exit
""")


def main():
    initialize_database()

    print("\nSirius Focus v0.1 initialized.")
    print("Your personal task assistant is ready.")

    while True:
        show_menu()

        choice = input("Choose an option: ").strip()

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
            print("Goodbye. 👋")
            break

        else:
            print("\n❌ Invalid option. Please choose 1-5.")


if __name__ == "__main__":
    main()