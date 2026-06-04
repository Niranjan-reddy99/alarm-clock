"""
test_models.py
--------------
Tests for AlarmState enum, VALID_TRANSITIONS, and Alarm domain model.

Coverage targets:
- All valid state transitions
- All invalid state transitions (terminal states + illegal paths)
- is_due() semantics (<=)
- is_overdue() semantics (<)
- to_dict() / from_dict() serialization round-trip
- AlarmState string values (str mixin)
"""

from __future__ import annotations

import pytest
from datetime import datetime, timedelta

from src.models import Alarm, AlarmState, VALID_TRANSITIONS


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def make_alarm(
    state: AlarmState = AlarmState.PENDING,
    minutes: int = 60,
    snooze: int | None = None,
) -> Alarm:
    """Create a test alarm with sensible defaults."""
    now = datetime.now().replace(second=0, microsecond=0)
    return Alarm(
        id=1,
        message="Test Alarm",
        scheduled_time=now + timedelta(minutes=minutes),
        state=state,
        snooze_minutes=snooze,
        created_at=now,
    )


# ---------------------------------------------------------------------------
# AlarmState enum
# ---------------------------------------------------------------------------

class TestAlarmState:
    """AlarmState is a str enum — values should be plain strings."""

    def test_pending_value(self):
        assert AlarmState.PENDING == "pending"

    def test_ringing_value(self):
        assert AlarmState.RINGING == "ringing"

    def test_dismissed_value(self):
        assert AlarmState.DISMISSED == "dismissed"

    def test_missed_value(self):
        assert AlarmState.MISSED == "missed"

    def test_str_mixin_equality(self):
        """Enum value equals its string — no .value needed."""
        assert AlarmState.PENDING == "pending"
        assert "pending" == AlarmState.PENDING

    def test_all_four_states_exist(self):
        states = {s.value for s in AlarmState}
        assert states == {"pending", "ringing", "dismissed", "missed"}


# ---------------------------------------------------------------------------
# State machine — valid transitions
# ---------------------------------------------------------------------------

class TestValidTransitions:
    """Every permitted transition should succeed without raising."""

    def test_pending_to_ringing(self):
        alarm = make_alarm(AlarmState.PENDING)
        alarm.transition(AlarmState.RINGING)
        assert alarm.state == AlarmState.RINGING

    def test_pending_to_missed(self):
        """Startup recovery path: PENDING → MISSED."""
        alarm = make_alarm(AlarmState.PENDING)
        alarm.transition(AlarmState.MISSED)
        assert alarm.state == AlarmState.MISSED

    def test_ringing_to_dismissed(self):
        alarm = make_alarm(AlarmState.RINGING)
        alarm.transition(AlarmState.DISMISSED)
        assert alarm.state == AlarmState.DISMISSED

    def test_ringing_to_missed(self):
        """60-second timeout path: RINGING → MISSED."""
        alarm = make_alarm(AlarmState.RINGING)
        alarm.transition(AlarmState.MISSED)
        assert alarm.state == AlarmState.MISSED

    def test_ringing_to_pending(self):
        """Snooze path: RINGING → PENDING (alarm is rescheduled)."""
        alarm = make_alarm(AlarmState.RINGING)
        alarm.transition(AlarmState.PENDING)
        assert alarm.state == AlarmState.PENDING


# ---------------------------------------------------------------------------
# State machine — invalid transitions
# ---------------------------------------------------------------------------

class TestInvalidTransitions:
    """Terminal states and illegal paths must raise ValueError."""

    def test_dismissed_to_ringing_raises(self):
        alarm = make_alarm(AlarmState.DISMISSED)
        with pytest.raises(ValueError, match="dismissed"):
            alarm.transition(AlarmState.RINGING)

    def test_dismissed_to_pending_raises(self):
        alarm = make_alarm(AlarmState.DISMISSED)
        with pytest.raises(ValueError, match="dismissed"):
            alarm.transition(AlarmState.PENDING)

    def test_dismissed_to_missed_raises(self):
        alarm = make_alarm(AlarmState.DISMISSED)
        with pytest.raises(ValueError, match="dismissed"):
            alarm.transition(AlarmState.MISSED)

    def test_missed_to_ringing_raises(self):
        alarm = make_alarm(AlarmState.MISSED)
        with pytest.raises(ValueError, match="missed"):
            alarm.transition(AlarmState.RINGING)

    def test_missed_to_pending_raises(self):
        alarm = make_alarm(AlarmState.MISSED)
        with pytest.raises(ValueError, match="missed"):
            alarm.transition(AlarmState.PENDING)

    def test_missed_to_dismissed_raises(self):
        alarm = make_alarm(AlarmState.MISSED)
        with pytest.raises(ValueError, match="missed"):
            alarm.transition(AlarmState.DISMISSED)

    def test_pending_to_dismissed_raises(self):
        """Direct PENDING → DISMISSED is not permitted (must go through RINGING)."""
        alarm = make_alarm(AlarmState.PENDING)
        with pytest.raises(ValueError, match="pending"):
            alarm.transition(AlarmState.DISMISSED)

    def test_error_message_names_both_states(self):
        """ValueError message should name the current and target states."""
        alarm = make_alarm(AlarmState.DISMISSED)
        with pytest.raises(ValueError) as exc_info:
            alarm.transition(AlarmState.PENDING)
        msg = str(exc_info.value)
        assert "dismissed" in msg
        assert "pending" in msg


# ---------------------------------------------------------------------------
# is_due()
# ---------------------------------------------------------------------------

class TestIsDue:
    """is_due() uses <= : fires at or after scheduled_time."""

    def test_past_due_pending_alarm_is_due(self):
        alarm = make_alarm(AlarmState.PENDING, minutes=-10)
        assert alarm.is_due() is True

    def test_future_pending_alarm_is_not_due(self):
        alarm = make_alarm(AlarmState.PENDING, minutes=30)
        assert alarm.is_due() is False

    def test_dismissed_alarm_is_not_due(self):
        """Non-PENDING alarms are never due regardless of time."""
        alarm = make_alarm(AlarmState.DISMISSED, minutes=-10)
        assert alarm.is_due() is False

    def test_missed_alarm_is_not_due(self):
        alarm = make_alarm(AlarmState.MISSED, minutes=-10)
        assert alarm.is_due() is False

    def test_ringing_alarm_is_not_due(self):
        alarm = make_alarm(AlarmState.RINGING, minutes=-1)
        assert alarm.is_due() is False


# ---------------------------------------------------------------------------
# is_overdue()
# ---------------------------------------------------------------------------

class TestIsOverdue:
    """is_overdue() uses < : strictly past, not equal-to-now."""

    def test_clearly_past_pending_alarm_is_overdue(self):
        alarm = make_alarm(AlarmState.PENDING, minutes=-30)
        assert alarm.is_overdue() is True

    def test_future_pending_alarm_is_not_overdue(self):
        alarm = make_alarm(AlarmState.PENDING, minutes=30)
        assert alarm.is_overdue() is False

    def test_dismissed_alarm_is_not_overdue(self):
        alarm = make_alarm(AlarmState.DISMISSED, minutes=-10)
        assert alarm.is_overdue() is False

    def test_missed_alarm_is_not_overdue(self):
        """Already-missed alarm should not be double-counted."""
        alarm = make_alarm(AlarmState.MISSED, minutes=-10)
        assert alarm.is_overdue() is False


# ---------------------------------------------------------------------------
# Serialization round-trip
# ---------------------------------------------------------------------------

class TestSerialization:
    """to_dict() → from_dict() must preserve all fields exactly."""

    def test_round_trip_with_snooze(self):
        original = make_alarm(AlarmState.PENDING, minutes=60, snooze=5)
        restored = Alarm.from_dict(original.to_dict())
        assert restored.id == original.id
        assert restored.message == original.message
        assert restored.scheduled_time == original.scheduled_time
        assert restored.state == original.state
        assert restored.snooze_minutes == original.snooze_minutes
        assert restored.created_at == original.created_at

    def test_round_trip_without_snooze(self):
        original = make_alarm(AlarmState.DISMISSED, snooze=None)
        restored = Alarm.from_dict(original.to_dict())
        assert restored.snooze_minutes is None

    def test_to_dict_state_is_string(self):
        """State must serialize as a plain string, not an enum repr."""
        alarm = make_alarm(AlarmState.PENDING)
        d = alarm.to_dict()
        assert d["state"] == "pending"
        assert isinstance(d["state"], str)

    def test_to_dict_snooze_none_is_preserved(self):
        alarm = make_alarm(snooze=None)
        d = alarm.to_dict()
        assert d["snooze_minutes"] is None

    def test_from_dict_missing_snooze_key_defaults_to_none(self):
        """Alarms saved before snooze was added should load cleanly."""
        alarm = make_alarm()
        d = alarm.to_dict()
        del d["snooze_minutes"]
        restored = Alarm.from_dict(d)
        assert restored.snooze_minutes is None

    def test_from_dict_invalid_state_raises(self):
        alarm = make_alarm()
        d = alarm.to_dict()
        d["state"] = "flying"
        with pytest.raises(ValueError):
            Alarm.from_dict(d)
