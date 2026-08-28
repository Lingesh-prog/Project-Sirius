"""Application startup for Sirius Focus."""

from app.cli import run
from app.storage.database import initialize_database
from app.tools.reminders.scheduler import ReminderScheduler


def main():
    """Initialize SIRIUS storage and start the command-line interface."""
    initialize_database()

    scheduler = ReminderScheduler()
    scheduler.start()
    try:
        run()
    finally:
        scheduler.stop()


if __name__ == "__main__":
    main()
