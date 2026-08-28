"""Repository and service tests for the SIRIUS reminder tool."""

import tempfile
import unittest
import sqlite3
from datetime import datetime
from pathlib import Path

from app.storage.database import get_connection, initialize_database
from app.tools.reminders import repository, service


class ReminderServiceTests(unittest.TestCase):
    """Exercise reminder behavior through disposable SQLite databases."""

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "sirius-test.db"
        initialize_database(self.database_path)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def create_reminder(self, text="Test reminder", remind_at="2026-08-30T09:00:00"):
        """Create a reminder in this test's disposable database."""
        return service.create_reminder(text, remind_at, self.database_path)

    def test_create_reminder_preserves_values_and_sets_pending_status(self):
        reminder_id = self.create_reminder("Call dentist", "2026-09-01T10:30:00")

        reminder = service.list_reminders(self.database_path)[0]

        self.assertEqual(reminder[:4], (
            reminder_id,
            "Call dentist",
            "2026-09-01T10:30:00",
            "Pending",
        ))
        self.assertTrue(reminder[4])

    def test_create_reminder_rejects_empty_or_whitespace_text(self):
        for text in ("", "   "):
            with self.subTest(text=text):
                with self.assertRaisesRegex(ValueError, "Reminder text cannot be empty"):
                    self.create_reminder(text)

    def test_create_reminder_rejects_invalid_iso_datetime(self):
        for remind_at in ("tomorrow morning", "2026-09-01", None):
            with self.subTest(remind_at=remind_at):
                with self.assertRaisesRegex(ValueError, "remind_at must be a valid ISO datetime"):
                    self.create_reminder(remind_at=remind_at)

    def test_list_reminders_is_empty_for_new_database(self):
        self.assertEqual(service.list_reminders(self.database_path), [])

    def test_list_reminders_orders_by_remind_at(self):
        later_id = self.create_reminder("Later", "2026-09-02T09:00:00")
        earlier_id = self.create_reminder("Earlier", "2026-09-01T09:00:00")

        self.assertEqual(
            [reminder[0] for reminder in service.list_reminders(self.database_path)],
            [earlier_id, later_id],
        )

    def test_mark_reminder_completed_updates_existing_reminder(self):
        reminder_id = self.create_reminder()

        self.assertTrue(service.mark_reminder_completed(reminder_id, self.database_path))
        self.assertEqual(service.list_reminders(self.database_path)[0][3], "Completed")

    def test_mark_reminder_completed_returns_false_for_missing_reminder(self):
        self.assertFalse(service.mark_reminder_completed(9999, self.database_path))

    def test_delete_reminder_removes_existing_reminder(self):
        reminder_id = self.create_reminder()

        self.assertTrue(service.delete_reminder(reminder_id, self.database_path))
        self.assertEqual(service.list_reminders(self.database_path), [])

    def test_delete_reminder_returns_false_for_missing_reminder(self):
        self.assertFalse(service.delete_reminder(9999, self.database_path))


class ReminderRepositoryTests(unittest.TestCase):
    """Verify reminder persistence independently of service validation."""

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "sirius-test.db"
        initialize_database(self.database_path)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_repository_persists_reminder_after_connection_reopens(self):
        reminder_id = repository.insert_reminder(
            "Repository reminder",
            "2026-09-01T09:00:00",
            "Pending",
            "2026-08-28T12:00:00",
            self.database_path,
        )

        connection = get_connection(self.database_path)
        connection.close()

        self.assertEqual(repository.fetch_reminders(self.database_path)[0][0], reminder_id)

    def test_database_only_contains_allowed_reminder_statuses(self):
        with self.assertRaisesRegex(sqlite3.IntegrityError, "CHECK constraint failed"):
            repository.insert_reminder(
                "Invalid status",
                "2026-09-01T09:00:00",
                "Cancelled",
                "2026-08-28T12:00:00",
                self.database_path,
            )


class ReminderDueServiceTests(unittest.TestCase):
    """Verify due-reminder lookup and exactly-once completion claims."""

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "sirius-test.db"
        initialize_database(self.database_path)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_get_due_reminders_is_empty_for_new_database(self):
        self.assertEqual(service.get_due_reminders(database_path=self.database_path), [])

    def test_get_due_reminders_returns_only_pending_reminders_at_or_before_now(self):
        now = datetime(2026, 9, 1, 12, 0, 0)
        due_id = service.create_reminder("Due now", "2026-09-01T11:00:00", self.database_path)
        service.create_reminder("Future", "2026-09-01T13:00:00", self.database_path)
        completed_id = service.create_reminder("Done earlier", "2026-09-01T10:00:00", self.database_path)
        service.mark_reminder_completed(completed_id, self.database_path)

        due = service.get_due_reminders(now=now, database_path=self.database_path)

        self.assertEqual([reminder[0] for reminder in due], [due_id])

    def test_get_due_reminders_orders_multiple_due_reminders_by_time(self):
        now = datetime(2026, 9, 1, 12, 0, 0)
        later_id = service.create_reminder("Later", "2026-09-01T11:30:00", self.database_path)
        earlier_id = service.create_reminder("Earlier", "2026-09-01T09:00:00", self.database_path)

        due = service.get_due_reminders(now=now, database_path=self.database_path)

        self.assertEqual([reminder[0] for reminder in due], [earlier_id, later_id])

    def test_complete_pending_reminder_claims_a_reminder_exactly_once(self):
        reminder_id = service.create_reminder("Claim me", "2026-09-01T09:00:00", self.database_path)

        self.assertTrue(service.complete_pending_reminder(reminder_id, self.database_path))
        self.assertFalse(service.complete_pending_reminder(reminder_id, self.database_path))
        self.assertEqual(service.list_reminders(self.database_path)[0][3], "Completed")

    def test_complete_pending_reminder_rejects_missing_or_completed_reminders(self):
        completed_id = service.create_reminder("Already done", "2026-09-01T09:00:00", self.database_path)
        service.mark_reminder_completed(completed_id, self.database_path)

        self.assertFalse(service.complete_pending_reminder(completed_id, self.database_path))
        self.assertFalse(service.complete_pending_reminder(9999, self.database_path))
