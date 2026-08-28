"""Lightweight background scheduler that triggers due SIRIUS reminders."""

import threading
from datetime import datetime

from app.tools.reminders import service


DEFAULT_INTERVAL_SECONDS = 1.0
MIN_INTERVAL_SECONDS = 0.01


def _print_reminder(reminder):
    """Default trigger action: announce the reminder on standard output."""
    print(f"\n[REMINDER] {reminder[1]} (scheduled for {reminder[2]})")


class ReminderScheduler:
    """Poll pending reminders and trigger each due reminder exactly once."""

    def __init__(
        self,
        interval_seconds=DEFAULT_INTERVAL_SECONDS,
        database_path=None,
        on_trigger=None,
    ):
        """Configure polling; *on_trigger* replaces the default print action."""
        self._interval = max(float(interval_seconds), MIN_INTERVAL_SECONDS)
        self._database_path = database_path
        self._on_trigger = on_trigger if on_trigger is not None else _print_reminder
        self._stop_event = threading.Event()
        self._thread = None

    @property
    def is_running(self):
        """Report whether the background polling thread is alive."""
        thread = self._thread
        return thread is not None and thread.is_alive()

    def start(self):
        """Start background polling; repeated calls while running are ignored."""
        if self.is_running:
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, name="reminder-scheduler", daemon=True
        )
        self._thread.start()

    def stop(self, timeout=2.0):
        """Ask the background thread to stop and wait for it to finish."""
        self._stop_event.set()

        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout)

    def run_once(self, now=None):
        """Run one scheduling pass and return the reminders that triggered.

        Each due reminder is claimed atomically before it is triggered, so
        a reminder is triggered exactly once no matter how often this runs.
        """
        triggered = []

        for reminder in service.get_due_reminders(
            now=now, database_path=self._database_path
        ):
            if service.complete_pending_reminder(
                reminder[0], database_path=self._database_path
            ):
                self._on_trigger(reminder)
                triggered.append(reminder)

        return triggered

    def _run(self):
        """Poll until stopped; a failing pass must not end the polling loop."""
        while not self._stop_event.wait(self._interval):
            try:
                self.run_once()
            except Exception:
                continue