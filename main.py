"""
main.py
-------
Entry point for the alarm clock CLI.

Usage
-----
    python main.py add "8:30 PM" "Workout"
    python main.py add "tomorrow 7am" "Morning Run" --snooze 5
    python main.py add "in 10 minutes" "Meeting"
    python main.py list
    python main.py delete 1
    python main.py run

This file contains no logic. All behaviour is in src/cli.py.
Keeping main.py minimal ensures src/cli.py is importable in tests
without triggering argument parsing or sys.exit.
"""

from src.cli import main

if __name__ == "__main__":
    main()
