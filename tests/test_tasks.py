"""Public-behavior tests for the Sirius Focus task service."""

import tempfile
import unittest
from pathlib import Path

from app.storage.database import get_connection, initialize_database
from app.tools.tasks import service


class TaskServiceTests(unittest.TestCase):
    """Exercise task behavior through the public service API only."""

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "sirius-test.db"
        initialize_database(self.database_path)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def add_task(self, title="Test task", **kwargs):
        """Create a task in this test's disposable database."""
        return service.add_task(title, database_path=self.database_path, **kwargs)

    def get_tasks(self):
        """List tasks from this test's disposable database."""
        return service.get_tasks(database_path=self.database_path)

    def test_create_valid_task_preserves_supplied_values(self):
        task_id = self.add_task(
            "Submit assignment",
            description="Upload the final PDF",
            due_date="2026-08-30",
            priority="High",
        )

        task = self.get_tasks()[0]

        self.assertEqual(task[0], task_id)
        self.assertEqual(task[1:6], (
            "Submit assignment",
            "Upload the final PDF",
            "2026-08-30",
            "High",
            "Pending",
        ))
        self.assertTrue(task[6])

    def test_create_task_uses_default_medium_priority_and_pending_status(self):
        task_id = self.add_task("Default task")

        task = self.get_tasks()[0]

        self.assertEqual(task[0], task_id)
        self.assertEqual(task[4], "Medium")
        self.assertEqual(task[5], "Pending")

    def test_create_task_accepts_each_valid_priority(self):
        for priority in ("Low", "Medium", "High"):
            with self.subTest(priority=priority):
                self.add_task(f"{priority} task", priority=priority)

        priorities = {task[1]: task[4] for task in self.get_tasks()}

        self.assertEqual(priorities, {
            "Low task": "Low",
            "Medium task": "Medium",
            "High task": "High",
        })

    def test_create_task_rejects_empty_title(self):
        with self.assertRaises(ValueError):
            self.add_task("")

    def test_create_task_rejects_whitespace_only_title(self):
        with self.assertRaises(ValueError):
            self.add_task("   ")

    def test_create_task_rejects_invalid_priority(self):
        with self.assertRaisesRegex(ValueError, "Priority must be Low, Medium, or High"):
            self.add_task("Task", priority="Urgent")

    def test_list_tasks_returns_empty_list_for_new_database(self):
        self.assertEqual(self.get_tasks(), [])

    def test_list_tasks_orders_multiple_tasks_by_priority(self):
        low_id = self.add_task("Low task", priority="Low")
        medium_id = self.add_task("Medium task", priority="Medium")
        high_id = self.add_task("High task", priority="High")

        self.assertEqual([task[0] for task in self.get_tasks()], [high_id, medium_id, low_id])

    def test_list_tasks_orders_same_priority_by_newest_id_first(self):
        older_id = self.add_task("Older high task", priority="High")
        newer_id = self.add_task("Newer high task", priority="High")

        self.assertEqual([task[0] for task in self.get_tasks()], [newer_id, older_id])

    def test_complete_existing_pending_task(self):
        task_id = self.add_task("Complete me")

        completed = service.complete_task(task_id, database_path=self.database_path)

        self.assertTrue(completed)
        self.assertEqual(self.get_tasks()[0][5], "Completed")

    def test_complete_missing_task_returns_false(self):
        self.assertFalse(service.complete_task(9999, database_path=self.database_path))

    def test_complete_already_completed_task_preserves_current_behavior(self):
        task_id = self.add_task("Already complete")
        service.complete_task(task_id, database_path=self.database_path)

        completed_again = service.complete_task(task_id, database_path=self.database_path)

        self.assertTrue(completed_again)
        self.assertEqual(self.get_tasks()[0][5], "Completed")

    def test_delete_existing_task_returns_true(self):
        task_id = self.add_task("Delete me")

        self.assertTrue(service.delete_task(task_id, database_path=self.database_path))

    def test_delete_missing_task_returns_false(self):
        self.assertFalse(service.delete_task(9999, database_path=self.database_path))

    def test_deleted_task_no_longer_appears_in_list(self):
        deleted_task_id = self.add_task("Remove this")
        retained_task_id = self.add_task("Keep this")

        service.delete_task(deleted_task_id, database_path=self.database_path)

        self.assertEqual([task[0] for task in self.get_tasks()], [retained_task_id])

    def test_task_persists_after_connection_is_reopened(self):
        task_id = self.add_task("Persistent task")

        connection = get_connection(self.database_path)
        connection.close()

        tasks_after_reopening = self.get_tasks()

        self.assertEqual([task[0] for task in tasks_after_reopening], [task_id])

    def test_service_supports_full_task_lifecycle_through_repository(self):
        task_id = self.add_task("Lifecycle task")

        self.assertEqual([task[0] for task in self.get_tasks()], [task_id])
        self.assertTrue(service.complete_task(task_id, database_path=self.database_path))
        self.assertTrue(service.delete_task(task_id, database_path=self.database_path))
        self.assertEqual(self.get_tasks(), [])


class TaskUpdateTests(unittest.TestCase):
    """Exercise task updates through the public service API only."""

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "sirius-test.db"
        initialize_database(self.database_path)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def add_task(self, title="Test task", **kwargs):
        """Create a task in this test's disposable database."""
        return service.add_task(title, database_path=self.database_path, **kwargs)

    def get_tasks(self):
        """List tasks from this test's disposable database."""
        return service.get_tasks(database_path=self.database_path)

    def test_update_title_changes_only_the_title(self):
        task_id = self.add_task("Old title", description="Keep me", priority="High")

        self.assertTrue(
            service.update_task(
                task_id, title="Finish DSD assignment", database_path=self.database_path
            )
        )

        task = self.get_tasks()[0]
        self.assertEqual(task[1], "Finish DSD assignment")
        self.assertEqual(task[2], "Keep me")
        self.assertEqual(task[4], "High")
        self.assertEqual(task[5], "Pending")

    def test_update_description_changes_only_the_description(self):
        task_id = self.add_task("Study", description="Old text")

        self.assertTrue(
            service.update_task(
                task_id,
                description="complete the database section",
                database_path=self.database_path,
            )
        )

        self.assertEqual(self.get_tasks()[0][2], "complete the database section")

    def test_update_due_date_changes_only_the_due_date(self):
        task_id = self.add_task("Deadline task", due_date="2026-08-30")

        self.assertTrue(
            service.update_task(
                task_id, due_date="2026-09-04", database_path=self.database_path
            )
        )

        self.assertEqual(self.get_tasks()[0][3], "2026-09-04")

    def test_update_priority_changes_only_the_priority(self):
        task_id = self.add_task("Priority task")

        self.assertTrue(
            service.update_task(
                task_id, priority="High", database_path=self.database_path
            )
        )

        self.assertEqual(self.get_tasks()[0][4], "High")

    def test_update_supports_multiple_fields_at_once(self):
        task_id = self.add_task("Multi task")

        self.assertTrue(
            service.update_task(
                task_id,
                title="Renamed task",
                description="New description",
                due_date="2026-09-10",
                priority="Low",
                database_path=self.database_path,
            )
        )

        task = self.get_tasks()[0]
        self.assertEqual(
            task[1:5], ("Renamed task", "New description", "2026-09-10", "Low")
        )

    def test_update_preserves_status_created_at_and_id(self):
        task_id = self.add_task("Protected task")
        original = self.get_tasks()[0]

        service.update_task(task_id, title="Renamed", database_path=self.database_path)

        task = self.get_tasks()[0]
        self.assertEqual(task[0], original[0])
        self.assertEqual(task[5], original[5])
        self.assertEqual(task[6], original[6])

    def test_update_missing_task_returns_false(self):
        self.assertFalse(
            service.update_task(9999, title="Ghost", database_path=self.database_path)
        )

    def test_update_without_fields_is_rejected(self):
        task_id = self.add_task("Untouched task")

        with self.assertRaisesRegex(ValueError, "At least one field"):
            service.update_task(task_id, database_path=self.database_path)

    def test_update_rejects_protected_fields(self):
        task_id = self.add_task("Protected task")

        for field in ("status", "created_at", "id"):
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, "cannot be updated"):
                    service.update_task(
                        task_id,
                        **{field: "hacked"},
                        database_path=self.database_path,
                    )

    def test_update_rejects_unknown_fields(self):
        task_id = self.add_task("Unknown field task")

        with self.assertRaisesRegex(ValueError, "Unknown task field"):
            service.update_task(task_id, color="red", database_path=self.database_path)

    def test_update_rejects_empty_title(self):
        task_id = self.add_task("Title task")

        with self.assertRaisesRegex(ValueError, "Task title cannot be empty"):
            service.update_task(task_id, title="   ", database_path=self.database_path)

    def test_update_rejects_invalid_priority(self):
        task_id = self.add_task("Priority task")

        with self.assertRaisesRegex(ValueError, "Priority must be Low, Medium, or High"):
            service.update_task(
                task_id, priority="Urgent", database_path=self.database_path
            )
