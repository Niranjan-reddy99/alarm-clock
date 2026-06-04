"""
cli.py
------
Argument parsing and command routing for the alarm clock CLI.

Responsibilities
----------------
- Define the argparse interface (subcommands, arguments, help text)
- Validate user input and surface friendly error messages
- Route each subcommand to the appropriate core module
- Call sys.exit(1) on any validation or execution error

What this module must NOT do
-----------------------------
- Contain business logic (state transitions, scheduling decisions)
- Write to alarms.json directly — always delegate to storage.py
- Contain display logic beyond simple error prints — delegate to notifier.py

Validation order in cmd_add
----------------------------
1. Message is not empty                (cheap string check)
2. Time string can be parsed           (dateparser call)
3. Parsed time is not in the past      (datetime comparison)
4. No alarm exists at that timestamp   (disk read — most expensive, last)
5. Snooze duration is positive         (only if --snooze provided)
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime

from src.models import Alarm, AlarmState
from src.notifier import show_list
from src.parser import parse_time
from src.scheduler import run
from src.storage import add_alarm, delete_alarm, find_by_time, load_alarms


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def cmd_add(args: argparse.Namespace) -> None:
    """
    Handle the ``add`` subcommand.

    Validates the message, parses and validates the time, checks for
    duplicate timestamps, then creates and persists the alarm.

    Parameters
    ----------
    args : Parsed arguments with ``time`` (str), ``message`` (str),
           and optional ``snooze`` (int | None).
    """
    # --- 1. Validate message ---
    message = args.message.strip()
    if not message:
        print("Error: Message cannot be empty.", file=sys.stderr)
        sys.exit(1)

    # --- 2. Parse time ---
    scheduled_time = parse_time(args.time)
    if scheduled_time is None:
        print(
            f"Error: Could not parse time: {args.time!r}\n"
            "Try one of these formats:\n"
            '  "8:30 PM"         — absolute time\n'
            '  "tomorrow 7am"    — next-day time\n'
            '  "in 10 minutes"   — relative offset\n'
            '  "in 2 hours"      — relative offset',
            file=sys.stderr,
        )
        sys.exit(1)

    # --- 3. Reject past times ---
    if scheduled_time <= datetime.now().replace(second=0, microsecond=0):
        print(
            f"Error: Cannot schedule an alarm in the past.\n"
            f"  Parsed time: {scheduled_time.strftime('%I:%M %p on %b %d')}",
            file=sys.stderr,
        )
        sys.exit(1)

    # --- 4. Check for duplicate timestamp (minute-level) ---
    alarms = load_alarms()
    if find_by_time(scheduled_time, alarms) is not None:
        print(
            f"Error: An alarm is already scheduled for "
            f"{scheduled_time.strftime('%I:%M %p on %b %d')}.\n"
            "Use a different time or delete the existing alarm first.",
            file=sys.stderr,
        )
        sys.exit(1)

    # --- 5. Validate snooze duration ---
    snooze_minutes: int | None = args.snooze
    if snooze_minutes is not None and snooze_minutes <= 0:
        print(
            "Error: Snooze duration must be a positive integer (minutes).",
            file=sys.stderr,
        )
        sys.exit(1)

    # --- Create and persist ---
    alarm = Alarm(
        id=0,  # assigned by add_alarm()
        message=message,
        scheduled_time=scheduled_time,
        state=AlarmState.PENDING,
        snooze_minutes=snooze_minutes,
        created_at=datetime.now(),
    )
    saved = add_alarm(alarm)

    snooze_note = f"  (snooze: {saved.snooze_minutes}m)" if saved.snooze_minutes else ""
    print(
        f"✓  Alarm #{saved.id} set for "
        f"{scheduled_time.strftime('%I:%M %p on %b %d')} — {saved.message}"
        f"{snooze_note}"
    )


def cmd_list(args: argparse.Namespace) -> None:
    """
    Handle the ``list`` subcommand.

    Loads all alarms and delegates display to notifier.show_list().
    Shows all lifecycle states (pending, ringing, dismissed, missed)
    so the user can see the full history and decide what to delete.

    Parameters
    ----------
    args : Parsed arguments (no fields used by this command).
    """
    alarms = load_alarms()
    show_list(alarms)


def cmd_delete(args: argparse.Namespace) -> None:
    """
    Handle the ``delete`` subcommand.

    Removes the alarm with the given ID from the store.

    Parameters
    ----------
    args : Parsed arguments with ``id`` (int).
    """
    alarm_id: int = args.id
    success = delete_alarm(alarm_id)

    if success:
        print(f"✓  Alarm #{alarm_id} deleted.")
    else:
        print(f"Error: No alarm found with ID {alarm_id}.", file=sys.stderr)
        sys.exit(1)


def cmd_run(args: argparse.Namespace) -> None:
    """
    Handle the ``run`` subcommand.

    Delegates entirely to scheduler.run(). The scheduler handles startup
    recovery (missed alarms) and the main poll loop.

    Parameters
    ----------
    args : Parsed arguments (no fields used by this command).
    """
    run()


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    """
    Build and return the top-level ArgumentParser.

    Separated from main() so the parser can be reused in tests without
    triggering sys.exit.
    """
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="A minimal alarm clock for the terminal.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            '  python main.py add "8:30 PM" "Workout"\n'
            '  python main.py add "tomorrow 7am" "Morning Run" --snooze 5\n'
            '  python main.py add "in 10 minutes" "Meeting"\n'
            "  python main.py list\n"
            "  python main.py delete 1\n"
            "  python main.py run"
        ),
    )

    subparsers = parser.add_subparsers(dest="command", metavar="command")

    # --- add ---
    add_parser = subparsers.add_parser(
        "add",
        help="Add a new alarm",
        description="Add a new alarm at the specified time with an optional snooze.",
    )
    add_parser.add_argument(
        "time",
        type=str,
        help='Time expression e.g. "8:30 PM", "tomorrow 7am", "in 10 minutes"',
    )
    add_parser.add_argument(
        "message",
        type=str,
        help="Label shown when the alarm rings",
    )
    add_parser.add_argument(
        "--snooze",
        type=int,
        default=None,
        metavar="MINUTES",
        help="Enable snooze with the given duration in minutes (e.g. --snooze 5)",
    )
    add_parser.set_defaults(func=cmd_add)

    # --- list ---
    list_parser = subparsers.add_parser(
        "list",
        help="List all alarms",
        description="Display all alarms with their ID, time, message, and state.",
    )
    list_parser.set_defaults(func=cmd_list)

    # --- delete ---
    delete_parser = subparsers.add_parser(
        "delete",
        help="Delete an alarm by ID",
        description="Permanently remove an alarm from the store.",
    )
    delete_parser.add_argument(
        "id",
        type=int,
        help="The numeric ID of the alarm to delete (see: python main.py list)",
    )
    delete_parser.set_defaults(func=cmd_delete)

    # --- run ---
    run_parser = subparsers.add_parser(
        "run",
        help="Start the alarm scheduler",
        description=(
            "Start the scheduler loop. Checks for due alarms every second.\n"
            "Detects alarms missed while the scheduler was off.\n"
            "Press Ctrl+C to stop."
        ),
    )
    run_parser.set_defaults(func=cmd_run)

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """
    Parse arguments and dispatch to the appropriate command handler.

    Prints help and exits cleanly if no subcommand is provided.
    """
    parser = _build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    args.func(args)
