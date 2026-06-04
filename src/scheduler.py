"""
scheduler.py
------------
Runtime orchestration for the alarm clock.

Responsibilities
----------------
- Detect alarms that were missed while the scheduler was not running
- Poll every second for alarms that are now due
- Process one ringing alarm at a time (sequential — no concurrency)
- Coordinate state transitions across models, storage, and notifier

What this module must NOT do
-----------------------------
- Print output directly — delegate to notifier.py
- Parse time strings — delegate to parser.py
- Assign alarm IDs — delegate to storage.py

Sequential processing (Design Decision 5)
-----------------------------------------
The scheduler processes one alarm at a time. While prompt_user() is
blocking (up to 60 seconds), the poll loop is paused. A second alarm
due during that window will be processed immediately after the first
resolves. This is intentional — simpler than concurrency and appropriate
for a single-user CLI tool.

Startup recovery (Design Decision 3)
--------------------------------------
Any alarm with state=PENDING and scheduled_time < now was missed while
the app was closed. These are transitioned to MISSED and displayed before
the main loop starts. The user sees them on restart and can decide to
delete them.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from pathlib import Path

from src.constants import ALARM_TIMEOUT_SECONDS, POLL_INTERVAL_SECONDS, STORAGE_FILE
from src.models import Alarm, AlarmState
from src.notifier import Action, prompt_user, show_banner, show_list
from src.storage import (
    find_by_time,
    load_alarms,
    update_alarm,
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run(storage_path: Path = STORAGE_FILE) -> None:
    """
    Start the alarm scheduler.

    Phase 1 — Startup recovery:
        Load all alarms. Any alarm that is PENDING with a scheduled_time
        strictly in the past is transitioned to MISSED and displayed.

    Phase 2 — Main poll loop:
        Every POLL_INTERVAL_SECONDS (1 second), reload alarms, find the
        earliest due alarm, and process it. Repeats until KeyboardInterrupt.

    Parameters
    ----------
    storage_path : Path to alarms.json. Defaults to STORAGE_FILE.
                   Overridable for testing.

    Raises
    ------
    StorageError
        Propagated from storage.load_alarms() if alarms.json is corrupted.
    """
    print("⏰  Alarm scheduler started.")
    print("    Press Ctrl+C to stop.\n")

    # --- Phase 1: startup recovery ---
    alarms = load_alarms(storage_path)
    missed = handle_startup_missed(alarms, storage_path)

    if missed:
        print(f"⚠   {len(missed)} alarm(s) were missed while the scheduler was off:\n")
        for alarm in missed:
            show_banner(alarm, is_missed=True)
    else:
        # Show current alarm state so the user knows what's loaded
        pending = [a for a in alarms if a.state == AlarmState.PENDING]
        if pending:
            print(f"    {len(pending)} alarm(s) loaded and waiting.\n")
            show_list(pending)
        else:
            print("    No pending alarms. Add one with: python main.py add \"in 10 minutes\" \"Label\"\n")

    # --- Phase 2: main poll loop ---
    try:
        while True:
            alarms = load_alarms(storage_path)
            due = find_next_due(alarms)
            if due:
                process_alarm(due, storage_path)
            time.sleep(POLL_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        print("\n\n    Scheduler stopped. Goodbye.")


def handle_startup_missed(
    alarms: list[Alarm],
    path: Path = STORAGE_FILE,
) -> list[Alarm]:
    """
    Detect and mark alarms that were missed while the scheduler was off.

    An alarm is considered missed on startup when:
    - state == PENDING  (not yet triggered)
    - scheduled_time < datetime.now()  (strictly in the past)

    Uses strict less-than so an alarm due *right now* is not pre-empted —
    the main loop will ring it instead.

    Parameters
    ----------
    alarms : The full alarm list, freshly loaded from disk.
    path   : Storage path for persisting state changes.

    Returns
    -------
    list[Alarm]
        The alarms that were transitioned to MISSED (may be empty).
    """
    missed: list[Alarm] = []

    for alarm in alarms:
        if alarm.is_overdue():
            alarm.transition(AlarmState.MISSED)
            update_alarm(alarm, path)
            missed.append(alarm)

    return missed


def find_next_due(alarms: list[Alarm]) -> Alarm | None:
    """
    Return the earliest alarm that is due right now, or None.

    An alarm is due when state == PENDING and scheduled_time <= now.
    If multiple alarms are simultaneously due, the one with the earliest
    scheduled_time is returned (sequential processing, Design Decision 5).

    Parameters
    ----------
    alarms : The current alarm list (freshly loaded from disk).

    Returns
    -------
    Alarm | None
        The earliest due alarm, or None if nothing is due.
    """
    due = [a for a in alarms if a.is_due()]
    if not due:
        return None
    return min(due, key=lambda a: a.scheduled_time)


def process_alarm(alarm: Alarm, path: Path = STORAGE_FILE) -> None:
    """
    Run the full ringing lifecycle for a single due alarm.

    Steps
    -----
    1. Transition alarm to RINGING and persist immediately.
       (If the process dies during the prompt, the alarm is on disk as
       RINGING. On restart, it's past-due → handle_startup_missed() marks
       it MISSED. No silent data loss.)
    2. Display the alarm banner.
    3. Prompt the user (blocks up to ALARM_TIMEOUT_SECONDS).
    4. Apply the resulting Action:
       - DISMISS  → transition to DISMISSED
       - TIMEOUT  → transition to MISSED
       - SNOOZE   → delegate to _handle_snooze()

    Parameters
    ----------
    alarm : The alarm to process. Must be in PENDING state.
    path  : Storage path for persisting state changes.
    """
    # Step 1: transition to RINGING and persist before blocking on input
    alarm.transition(AlarmState.RINGING)
    update_alarm(alarm, path)

    # Step 2: display banner
    show_banner(alarm, is_missed=False)

    # Step 3: prompt (blocks up to 60s via select.select)
    action = prompt_user(alarm)

    # Step 4: apply action
    if action == Action.DISMISS:
        alarm.transition(AlarmState.DISMISSED)
        update_alarm(alarm, path)
        print("\n  ✓  Alarm dismissed.\n")

    elif action == Action.TIMEOUT:
        alarm.transition(AlarmState.MISSED)
        update_alarm(alarm, path)
        print("\n  ✗  No response — alarm marked as missed.\n")

    elif action == Action.SNOOZE:
        _handle_snooze(alarm, path)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _handle_snooze(alarm: Alarm, path: Path) -> None:
    """
    Apply snooze logic: reschedule the alarm or dismiss if rescheduling fails.

    The alarm is rescheduled to ``now + snooze_minutes``, with seconds
    zeroed to maintain minute-level uniqueness.

    Two guards are checked before committing the snooze:

    Guard 1 — Past time:
        If ``new_time <= now`` (e.g. snooze_minutes=1 but processing
        took more than 1 minute), the snoozed time is already past.
        Dismiss the alarm and warn.

    Guard 2 — Timestamp collision:
        If another alarm already occupies the target minute, dismiss
        and warn rather than silently overwriting (Design Decision 1).

    Parameters
    ----------
    alarm : The alarm to snooze. Must be in RINGING state.
    path  : Storage path for collision checking and persistence.
    """
    assert alarm.snooze_minutes is not None, (
        "_handle_snooze called on alarm with no snooze_minutes set"
    )

    new_time = datetime.now() + timedelta(minutes=alarm.snooze_minutes)
    new_time = new_time.replace(second=0, microsecond=0)

    # Guard 1: snoozed time is already in the past
    if new_time <= datetime.now().replace(second=0, microsecond=0):
        alarm.transition(AlarmState.DISMISSED)
        update_alarm(alarm, path)
        print("\n  ⚠  Snoozed time is already in the past. Alarm dismissed.\n")
        return

    # Guard 2: timestamp collision with an existing alarm
    all_alarms = load_alarms(path)
    collision = find_by_time(new_time, all_alarms)

    if collision is not None:
        alarm.transition(AlarmState.DISMISSED)
        update_alarm(alarm, path)
        print(
            f"\n  ⚠  Snoozed time conflicts with alarm #{collision.id} "
            f"({collision.message}). Alarm dismissed.\n"
        )
        return

    # Safe to snooze — update time and return to PENDING
    alarm.scheduled_time = new_time
    alarm.transition(AlarmState.PENDING)
    update_alarm(alarm, path)
    print(f"\n  ⏸  Snoozed to {new_time.strftime('%I:%M %p')}.\n")
