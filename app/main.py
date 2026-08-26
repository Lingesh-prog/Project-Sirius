"""Application startup for Sirius Focus."""

from app.cli import run
from app.storage.database import initialize_database


def main():
    """Initialize SIRIUS storage and start the command-line interface."""
    initialize_database()
    run()


if __name__ == "__main__":
    main()
