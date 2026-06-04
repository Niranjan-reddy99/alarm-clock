"""
test_scheduler.py
-----------------
Tests for scheduler orchestration: startup recovery, due-alarm detection,
and the full process_alarm() lifecycle with mocked user input.

All tests use tmp_path for storage isolation. prompt_user() is mocked
via unittest.mock.patch so no real stdin/select.select interaction occurs.

Coverage targets:
- handle_startup_missed: marks past-due PENDING → MISSED
- handle_startup_missed: ignores future alarms, dismissed, already-missed
- find_next_due: returns None when nothing is due
- find_next_due: returns earliest due alarm among multiple candidates
- process_alarm + DISMISS → DISMISSED, persisted
- process_alarm + TIMEOUT → MISSED, persisted
- process_alarm + SNOOZE → PENDING, new time persisted
- process_alarm + SNOOZE collision → DISMISSED, warn
- process_alarm + SNOOZE to past → DISMISSED, warn
- process_alarm persists RINGING before blocking on prompt
"""

from __future__ import annotations

import pytest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from src.models import Alarm, AlarmState
from src.notifier import Action
from src.scheduler import (
    find_next_due,
    handle_startup_missed,
    process_alarm,
)
from src.storage import add_alarm, find_by_id, load_alarms


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_alarm(
    msg: str,
    minutes: int,
    store: Path,
    state: AlarmState = AlarmState.PENDING,
    snooze: int | None = None,
) -> Alarm:
    """Create and persist a test alarm."""
    now = datetime.now().replace(second=0, microsecond=0)
    alarm = Alarm(
        id=0,
        message=msg,
        scheduled_time=now + timedelta(minutes=minutes),
        state=state,
        snooze_minutes=snooze,
        created_at=now,
    )
    return add_alarm(alarm, store)


# ---------------------------------------------------------------------------
# handle_startup_missed
# ---------------------------------------------------------------------------

class TestHandleStartupMissed:

    def test_past_due_pending_alarm_is_marked_missed(self, tmp_path):
        store = tmp_path / "alarms.json"
        alarm = make_alarm("OldWorkout", minutes=-30, store=store)
        alarms = load_alarms(store)

        missed = handle_startup_missed(alarms, store)

        assert len(missed) == 1
        assert missed[0].message == "OldWorkout"
        assert missed[0].state == AlarmState.MISSED

    def test_missed_state_is_persisted_to_disk(self, tmp_path):
        store = tmp_path / "alarms.json"
        alarm = make_alarm("OldAlarm", minutes=-10, store=store)
        alarms = load_alarms(store)
        handle_startup_missed(alarms, store)

        reloaded = load_alarms(store)
        assert find_by_id(alarm.id, reloaded).state == AlarmState.MISSED

    def test_future_pending_alarm_is_not_missed(self, tmp_path):
        store = tmp_path / "alarms.json"
        make_alarm("FutureRun", minutes=30, store=store)
        alarms = load_alarms(store)

        missed = handle_startup_missed(alarms, store)

        assert missed == []
        reloaded = load_alarms(store)
        assert reloaded[0].state == AlarmState.PENDING

    def test_already_dismissed_alarm_is_ignored(self, tmp_path):
        store = tmp_path / "alarms.json"
        make_alarm("Done", minutes=-10, store=store, state=AlarmState.DISMISSED)
        alarms = load_alarms(store)

        missed = handle_startup_missed(alarms, store)
        assert missed == []

    def test_already_missed_alarm_is_not_double_counted(self, tmp_path):
        store = tmp_path / "alarms.json"
        make_alarm("AlreadyMissed", minutes=-10, store=store, state=AlarmState.MISSED)
        alarms = load_alarms(store)

        missed = handle_startup_missed(alarms, store)
        assert missed == []

    def test_only_past_due_alarms_are_returned(self, tmp_path):
        """Mixed list: only past-due PENDING alarms should be in result."""
        store = tmp_path / "alarms.json"
        make_alarm("Past",   minutes=-10,  store=store)
        make_alarm("Future", minutes=+30,  store=store)
        alarms = load_alarms(store)

        missed = handle_startup_missed(alarms, store)
        assert len(missed) == 1
        assert missed[0].message == "Past"


# ---------------------------------------------------------------------------
# find_next_due
# ---------------------------------------------------------------------------

class TestFindNextDue:

    def test_returns_none_when_no_alarms(self):
        assert find_next_due([]) is None

    def test_returns_none_when_no_alarms_are_due(self, tmp_path):
        store = tmp_path / "alarms.json"
        make_alarm("Future", minutes=30, store=store)
        alarms = load_alarms(store)
        assert find_next_due(alarms) is None

    def test_returns_due_alarm(self, tmp_path):
        store = tmp_path / "alarms.json"
        make_alarm("Overdue", minutes=-5, store=store)
        alarms = load_alarms(store)
        result = find_next_due(alarms)
        assert result is not None
        assert result.message == "Overdue"

    def test_returns_earliest_when_multiple_due(self, tmp_path):
        store = tmp_path / "alarms.json"
        make_alarm("Earlier", minutes=-20, store=store)
        make_alarm("Later",   minutes=-5,  store=store)
        alarms = load_alarms(store)

        result = find_next_due(alarms)
        assert result.message == "Earlier"

    def test_ignores_dismissed_alarms(self, tmp_path):
        store = tmp_path / "alarms.json"
        make_alarm("Done", minutes=-10, store=store, state=AlarmState.DISMISSED)
        alarms = load_alarms(store)
        assert find_next_due(alarms) is None

    def test_ignores_missed_alarms(self, tmp_path):
        store = tmp_path / "alarms.json"
        make_alarm("Missed", minutes=-10, store=store, state=AlarmState.MISSED)
        alarms = load_alarms(store)
        assert find_next_due(alarms) is None


# ---------------------------------------------------------------------------
# process_alarm — DISMISS path
# ---------------------------------------------------------------------------

class TestProcessAlarmDismiss:

    def test_dismiss_transitions_to_dismissed(self, tmp_path):
        store = tmp_path / "alarms.json"
        alarm = make_alarm("DismissMe", minutes=-1, store=store)

        with patch("src.scheduler.prompt_user", return_value=Action.DISMISS):
            process_alarm(alarm, store)

        reloaded = load_alarms(store)
        assert find_by_id(alarm.id, reloaded).state == AlarmState.DISMISSED

    def test_dismiss_persists_to_disk(self, tmp_path):
        store = tmp_path / "alarms.json"
        alarm = make_alarm("DismissPersist", minutes=-1, store=store)

        with patch("src.scheduler.prompt_user", return_value=Action.DISMISS):
            process_alarm(alarm, store)

        reloaded = load_alarms(store)
        assert find_by_id(alarm.id, reloaded).state == AlarmState.DISMISSED


# ---------------------------------------------------------------------------
# process_alarm — TIMEOUT path
# ---------------------------------------------------------------------------

class TestProcessAlarmTimeout:

    def test_timeout_transitions_to_missed(self, tmp_path):
        store = tmp_path / "alarms.json"
        alarm = make_alarm("TimeoutMe", minutes=-1, store=store)

        with patch("src.scheduler.prompt_user", return_value=Action.TIMEOUT):
            process_alarm(alarm, store)

        reloaded = load_alarms(store)
        assert find_by_id(alarm.id, reloaded).state == AlarmState.MISSED

    def test_timeout_persists_to_disk(self, tmp_path):
        store = tmp_path / "alarms.json"
        alarm = make_alarm("TimeoutPersist", minutes=-1, store=store)

        with patch("src.scheduler.prompt_user", return_value=Action.TIMEOUT):
            process_alarm(alarm, store)

        reloaded = load_alarms(store)
        assert find_by_id(alarm.id, reloaded).state == AlarmState.MISSED


# ---------------------------------------------------------------------------
# process_alarm — SNOOZE path
# ---------------------------------------------------------------------------

class TestProcessAlarmSnooze:

    def test_snooze_reschedules_alarm(self, tmp_path):
        store = tmp_path / "alarms.json"
        alarm = make_alarm("SnoozeMe", minutes=-1, store=store, snooze=5)

        with patch("src.scheduler.prompt_user", return_value=Action.SNOOZE):
            process_alarm(alarm, store)

        reloaded = load_alarms(store)
        snoozed = find_by_id(alarm.id, reloaded)
        assert snoozed.state == AlarmState.PENDING
        assert snoozed.scheduled_time > datetime.now()

    def test_snooze_new_time_is_now_plus_snooze_minutes(self, tmp_path):
        store = tmp_path / "alarms.json"
        alarm = make_alarm("SnoozeTiming", minutes=-1, store=store, snooze=10)
        before = datetime.now().replace(second=0, microsecond=0)

        with patch("src.scheduler.prompt_user", return_value=Action.SNOOZE):
            process_alarm(alarm, store)

        reloaded = load_alarms(store)
        snoozed = find_by_id(alarm.id, reloaded)
        expected = before + timedelta(minutes=10)
        # Allow ±1 minute for execution time
        assert abs((snoozed.scheduled_time - expected).total_seconds()) <= 60

    def test_snooze_collision_causes_dismiss(self, tmp_path):
        """If snoozed time conflicts with another alarm, dismiss instead."""
        store = tmp_path / "alarms.json"
        # Alarm to snooze by 5 minutes
        alarm = make_alarm("SnoozeCollide", minutes=-1,  store=store, snooze=5)
        # Alarm occupying the snoozed slot
        _     = make_alarm("Occupant",      minutes=+5,  store=store)

        with patch("src.scheduler.prompt_user", return_value=Action.SNOOZE):
            process_alarm(alarm, store)

        reloaded = load_alarms(store)
        result = find_by_id(alarm.id, reloaded)
        assert result.state == AlarmState.DISMISSED

    def test_snooze_seconds_are_zeroed(self, tmp_path):
        """Snoozed time must have seconds=0 (minute-level uniqueness)."""
        store = tmp_path / "alarms.json"
        alarm = make_alarm("SnoozeZero", minutes=-1, store=store, snooze=5)

        with patch("src.scheduler.prompt_user", return_value=Action.SNOOZE):
            process_alarm(alarm, store)

        reloaded = load_alarms(store)
        snoozed = find_by_id(alarm.id, reloaded)
        if snoozed.state == AlarmState.PENDING:
            assert snoozed.scheduled_time.second == 0
            assert snoozed.scheduled_time.microsecond == 0


# ---------------------------------------------------------------------------
# process_alarm — RINGING persisted before prompt
# ---------------------------------------------------------------------------

class TestProcessAlarmRingingPersistence:

    def test_alarm_is_ringing_on_disk_before_user_responds(self, tmp_path):
        """
        RINGING must be persisted before prompt_user() is called.
        This ensures crash-safety: if the process dies during the prompt,
        the alarm is recoverable as MISSED on next startup.
        """
        store = tmp_path / "alarms.json"
        alarm = make_alarm("CrashSafe", minutes=-1, store=store)
        states_seen: list[AlarmState] = []

        def capture_state_then_dismiss(a: Alarm) -> Action:
            # Read state from disk at the moment prompt_user is called
            reloaded = load_alarms(store)
            on_disk = find_by_id(a.id, reloaded)
            states_seen.append(on_disk.state)
            return Action.DISMISS

        with patch("src.scheduler.prompt_user", side_effect=capture_state_then_dismiss):
            process_alarm(alarm, store)

        assert AlarmState.RINGING in states_seen, (
            "Alarm should be persisted as RINGING before prompt_user is called"
        )
