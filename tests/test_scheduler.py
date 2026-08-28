"""Tests for the background reminder scheduler."""

import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from app.storage.database import initialize_database
from app.tools.reminders import service
from app.tools.reminders.scheduler import ReminderScheduler


def wait_until(condition, timeout=2.0):
    """Poll *condition* until it is truthy or *timeout* seconds pass."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return condition()


class ReminderSchedulerTests(unittest.TestCase):
    """Exercise scheduler passes and thread lifecycle on disposable databases."""

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "scheduler-test.db"
        initialize_database(self.database_path)
        self.now = datetime(2026, 9, 1, 12, 0, 0)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def create_reminder(self, text, remind_at):
        """Create a reminder in this test's disposable database."""
        return service.create_reminder(text, remind_at, self.database_path)

    def status_of(self, reminder_id):
        """Return the status of one reminder in this test's database."""
        for reminder in service.list_reminders(self.database_path):
            if reminder[0] == reminder_id:
                return reminder[3]
        raise AssertionError(f"Reminder {reminder_id} not found")

    def make_scheduler(self, triggered):
        """Build a scheduler that records triggered reminder ids."""
        return ReminderScheduler(
            interval_seconds=0.01,
            database_path=self.database_path,
            on_trigger=lambda reminder: triggered.append(reminder[0]),
        )

    def test_due_reminders_are_triggered_once_and_marked_completed(self):
        due_id = self.create_reminder("Due", (self.now - timedelta(hours=1)).isoformat())
        triggered = []
        scheduler = self.make_scheduler(triggered)

        result = scheduler.run_once(now=self.now)

        self.assertEqual([reminder[0] for reminder in result], [due_id])
        self.assertEqual(triggered, [due_id])
        self.assertEqual(self.status_of(due_id), "Completed")

    def test_future_reminders_are_left_pending(self):
        future_id = self.create_reminder("Future", (self.now + timedelta(hours=1)).isoformat())
        triggered = []
        scheduler = self.make_scheduler(triggered)

        self.assertEqual(scheduler.run_once(now=self.now), [])

        self.assertEqual(triggered, [])
        self.assertEqual(self.status_of(future_id), "Pending")

    def test_completed_reminders_are_never_triggered(self):
        completed_id = self.create_reminder("Old", (self.now - timedelta(days=1)).isoformat())
        service.mark_reminder_completed(completed_id, self.database_path)
        triggered = []
        scheduler = self.make_scheduler(triggered)

        self.assertEqual(scheduler.run_once(now=self.now), [])

        self.assertEqual(triggered, [])
        self.assertEqual(self.status_of(completed_id), "Completed")

    def test_repeated_passes_trigger_each_reminder_exactly_once(self):
        first_id = self.create_reminder("First", (self.now - timedelta(hours=2)).isoformat())
        second_id = self.create_reminder("Second", (self.now - timedelta(hours=1)).isoformat())
        third_id = self.create_reminder("Third", (self.now + timedelta(hours=1)).isoformat())
        triggered = []
        scheduler = self.make_scheduler(triggered)

        self.assertEqual(
            [reminder[0] for reminder in scheduler.run_once(now=self.now)],
            [first_id, second_id],
        )
        self.assertEqual(scheduler.run_once(now=self.now), [])

        later = self.now + timedelta(hours=2)
        self.assertEqual(
            [reminder[0] for reminder in scheduler.run_once(now=later)],
            [third_id],
        )
        self.assertEqual(scheduler.run_once(now=later), [])

        self.assertEqual(triggered, [first_id, second_id, third_id])
        for reminder_id in (first_id, second_id, third_id):
            self.assertEqual(self.status_of(reminder_id), "Completed")

    def test_background_thread_triggers_due_reminders_without_blocking_start(self):
        due_id = self.create_reminder(
            "Thread due", (datetime.now() - timedelta(seconds=1)).isoformat(timespec="seconds")
        )
        triggered = []
        scheduler = self.make_scheduler(triggered)

        started_at = time.perf_counter()
        scheduler.start()
        start_duration = time.perf_counter() - started_at

        self.assertLess(start_duration, 0.5)
        self.assertTrue(wait_until(lambda: triggered == [due_id]))

        scheduler.stop(timeout=2.0)

        self.assertFalse(scheduler.is_running)
        self.assertEqual(triggered, [due_id])
        self.assertEqual(self.status_of(due_id), "Completed")

    def test_scheduler_supports_clean_start_and_stop_cycles(self):
        triggered = []
        scheduler = self.make_scheduler(triggered)

        scheduler.start()
        self.assertTrue(scheduler.is_running)
        scheduler.stop(timeout=2.0)
        self.assertFalse(scheduler.is_running)

        due_id = self.create_reminder(
            "Cycle", (datetime.now() - timedelta(hours=1)).isoformat(timespec="seconds")
        )

        scheduler.start()
        self.assertTrue(scheduler.is_running)
        self.assertTrue(wait_until(lambda: triggered == [due_id]))
        scheduler.stop(timeout=2.0)

        self.assertFalse(scheduler.is_running)
        self.assertEqual(triggered, [due_id])

    def test_stop_without_start_is_safe(self):
        scheduler = ReminderScheduler(database_path=self.database_path)

        scheduler.stop()

        self.assertFalse(scheduler.is_running)