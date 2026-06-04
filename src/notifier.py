"""
notifier.py
-----------
Terminal output and interactive user prompts for alarm events.

Responsibilities
----------------
- Display alarm banners (triggered and missed)
- Display the alarm list as a formatted table
- Prompt the user to dismiss or snooze with a 60-second timeout

What this module must NOT do
-----------------------------
- Modify alarm state — it only reads alarm data
- Write to the JSON store — that is storage.py's job
- Make scheduling decisions — that is scheduler.py's job

Timeout implementation
----------------------
prompt_user() uses select.select() on sys.stdin to implement a
non-blocking read with a 60-second deadline. This requires no threads
and no asyncio, but is only supported on macOS and Linux (POSIX).
Windows is not supported — documented in README.
"""

from __future__ import annotations

import select
import sys
from datetime import datetime
from enum import Enum

from src.constants import ALARM_TIMEOUT_SECONDS, BANNER_WIDTH, DATE_DISPLAY_FORMAT
from src.models import Alarm, AlarmState


# ---------------------------------------------------------------------------
# Action enum
# ---------------------------------------------------------------------------

class Action(Enum):
    """
    Represents the user's response to a ringing alarm.

    DISMISS : User pressed [D] — alarm should transition to DISMISSED.
    SNOOZE  : User pressed [S] — alarm should be rescheduled and stay PENDING.
    TIMEOUT : No response within ALARM_TIMEOUT_SECONDS — alarm goes to MISSED.
    """

    DISMISS = "dismiss"
    SNOOZE = "snooze"
    TIMEOUT = "timeout"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_STATE_ICONS: dict[AlarmState, str] = {
    AlarmState.PENDING:   "⏳",
    AlarmState.RINGING:   "🔔",
    AlarmState.DISMISSED: "✅",
    AlarmState.MISSED:    "❌",
}

_DIVIDER = "═" * BANNER_WIDTH


def _fmt_time(dt: datetime) -> str:
    """Format a datetime for display (e.g. '08:30 AM on Jun 04')."""
    return dt.strftime(DATE_DISPLAY_FORMAT)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def show_banner(alarm: Alarm, is_missed: bool = False) -> None:
    """
    Print the alarm event banner to stdout.

    For a triggered alarm, prints a two-section banner: header with the
    alarm type, and a body with message, scheduled time, and current time.

    For a missed alarm (``is_missed=True``), omits the current time row
    and uses a MISSED ALARM header instead.

    A terminal bell character (``\\a``) is emitted before the banner so
    the terminal beeps on alarm trigger.

    Parameters
    ----------
    alarm     : The alarm to display.
    is_missed : If True, render the missed-alarm variant of the banner.
    """
    print("\a", end="", flush=True)  # terminal bell
    print()
    print(_DIVIDER)

    if is_missed:
        print("  ⚠   MISSED ALARM")
    else:
        print("  ⏰  ALARM TRIGGERED")

    print(_DIVIDER)
    print(f"  Message    :  {alarm.message}")
    print(f"  Scheduled  :  {_fmt_time(alarm.scheduled_time)}")

    if not is_missed:
        print(f"  Now        :  {_fmt_time(datetime.now())}")

    print(_DIVIDER)


def prompt_user(alarm: Alarm) -> Action:
    """
    Display response options and wait up to 60 seconds for user input.

    Uses ``select.select()`` on ``sys.stdin`` to implement a non-blocking
    read with a deadline. No threads or asyncio required.

    - If ``alarm.snooze_minutes`` is set, the [S] Snooze option is shown.
    - If no response is received within ``ALARM_TIMEOUT_SECONDS``, returns
      ``Action.TIMEOUT``.
    - Any unrecognised input defaults to ``Action.DISMISS``.

    Parameters
    ----------
    alarm : The ringing alarm. Read-only — this function does not mutate it.

    Returns
    -------
    Action
        One of ``Action.DISMISS``, ``Action.SNOOZE``, or ``Action.TIMEOUT``.

    Platform note
    -------------
    ``select.select()`` on ``sys.stdin`` is a POSIX feature.
    This function works on macOS and Linux. It is **not** supported on Windows.
    """
    print()

    if alarm.snooze_minutes is not None:
        print(f"  [S]  Snooze for {alarm.snooze_minutes} minute(s)")

    print("  [D]  Dismiss")
    print(f"  (Auto-dismisses in {ALARM_TIMEOUT_SECONDS}s if no response)")
    print()
    print("  > ", end="", flush=True)

    # --- Non-blocking stdin read with deadline ---
    # select.select() returns as soon as stdin has data, or after the timeout.
    # Returns ([sys.stdin], [], []) if input is ready; ([], [], []) on timeout.
    ready, _, _ = select.select([sys.stdin], [], [], ALARM_TIMEOUT_SECONDS)

    if not ready:
        print("\n  No response received. Marking as missed.")
        return Action.TIMEOUT

    response = sys.stdin.readline().strip().upper()

    if response == "S" and alarm.snooze_minutes is not None:
        return Action.SNOOZE

    if response == "D":
        return Action.DISMISS

    # Unrecognised input — dismiss rather than loop (keeps the timeout contract)
    print("  Unrecognised input. Dismissing.")
    return Action.DISMISS


def show_list(alarms: list[Alarm]) -> None:
    """
    Print all alarms as a formatted table to stdout.

    Alarms are sorted by ``scheduled_time`` ascending so the next alarm
    to ring appears at the top. All lifecycle states are shown — dismissed
    and missed alarms are included so the user can see the full history
    and decide what to delete.

    Parameters
    ----------
    alarms : The list of alarms to display (may be empty).
    """
    if not alarms:
        print("  No alarms found. Add one with:  python main.py add \"in 10 minutes\" \"Label\"")
        return

    # Column widths
    col_id      = 4
    col_time    = 22
    col_message = 20
    col_state   = 16
    col_snooze  = 8

    header = (
        f"  {'ID':<{col_id}}"
        f"  {'Scheduled':<{col_time}}"
        f"  {'Message':<{col_message}}"
        f"  {'State':<{col_state}}"
        f"  {'Snooze':<{col_snooze}}"
    )
    separator = "  " + "─" * (col_id + col_time + col_message + col_state + col_snooze + 8)

    print()
    print(header)
    print(separator)

    for alarm in sorted(alarms, key=lambda a: a.scheduled_time):
        icon        = _STATE_ICONS.get(alarm.state, "?")
        state_label = f"{icon} {alarm.state.value}"
        snooze_label = f"{alarm.snooze_minutes}m" if alarm.snooze_minutes else "—"

        # Truncate long messages so columns stay aligned
        message = alarm.message[:col_message - 1] if len(alarm.message) > col_message else alarm.message

        row = (
            f"  {alarm.id:<{col_id}}"
            f"  {_fmt_time(alarm.scheduled_time):<{col_time}}"
            f"  {message:<{col_message}}"
            f"  {state_label:<{col_state}}"
            f"  {snooze_label:<{col_snooze}}"
        )
        print(row)

    print()
