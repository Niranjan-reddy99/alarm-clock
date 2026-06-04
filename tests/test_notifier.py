"""
test_notifier.py
----------------
Tests for terminal display functions: show_banner, show_list, Action enum.

prompt_user() is NOT tested here — it requires interactive stdin via
select.select() and belongs in an integration test. These tests cover
the display output using pytest's capsys fixture to capture stdout.

Coverage targets:
- Action enum values
- show_banner (triggered): contains message, scheduled time, current time
- show_banner (missed): contains MISSED header, no current time row
- show_banner emits terminal bell character
- show_list (empty): shows helpful hint
- show_list: shows all alarms sorted by scheduled_time
- show_list: shows state icons correctly
- show_list: shows snooze column
- show_list: truncates long messages
"""

from __future__ import annotations

import pytest
from datetime import datetime, timedelta

from src.models import Alarm, AlarmState
from src.notifier import Action, show_banner, show_list


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_alarm(
    id: int = 1,
    msg: str = "Test Alarm",
    minutes: int = 60,
    state: AlarmState = AlarmState.PENDING,
    snooze: int | None = None,
) -> Alarm:
    now = datetime.now().replace(second=0, microsecond=0)
    return Alarm(
        id=id,
        message=msg,
        scheduled_time=now + timedelta(minutes=minutes),
        state=state,
        snooze_minutes=snooze,
        created_at=now,
    )


# ---------------------------------------------------------------------------
# Action enum
# ---------------------------------------------------------------------------

class TestAction:

    def test_dismiss_value(self):
        assert Action.DISMISS.value == "dismiss"

    def test_snooze_value(self):
        assert Action.SNOOZE.value == "snooze"

    def test_timeout_value(self):
        assert Action.TIMEOUT.value == "timeout"

    def test_three_actions_exist(self):
        assert len(list(Action)) == 3


# ---------------------------------------------------------------------------
# show_banner — triggered alarm
# ---------------------------------------------------------------------------

class TestShowBannerTriggered:

    def test_banner_contains_alarm_triggered_header(self, capsys):
        show_banner(make_alarm(), is_missed=False)
        out = capsys.readouterr().out
        assert "ALARM TRIGGERED" in out

    def test_banner_contains_message(self, capsys):
        alarm = make_alarm(msg="Morning Run")
        show_banner(alarm, is_missed=False)
        out = capsys.readouterr().out
        assert "Morning Run" in out

    def test_banner_contains_scheduled_time(self, capsys):
        alarm = make_alarm()
        show_banner(alarm, is_missed=False)
        out = capsys.readouterr().out
        # Scheduled time is shown as formatted string, e.g. "08:30 AM"
        assert alarm.formatted_time() in out

    def test_banner_contains_current_time_label(self, capsys):
        show_banner(make_alarm(), is_missed=False)
        out = capsys.readouterr().out
        assert "Now" in out

    def test_banner_emits_bell_character(self, capsys):
        show_banner(make_alarm(), is_missed=False)
        out = capsys.readouterr().out
        assert "\a" in out

    def test_banner_does_not_show_missed_header(self, capsys):
        show_banner(make_alarm(), is_missed=False)
        out = capsys.readouterr().out
        assert "MISSED" not in out


# ---------------------------------------------------------------------------
# show_banner — missed alarm
# ---------------------------------------------------------------------------

class TestShowBannerMissed:

    def test_missed_banner_contains_missed_header(self, capsys):
        show_banner(make_alarm(), is_missed=True)
        out = capsys.readouterr().out
        assert "MISSED" in out

    def test_missed_banner_contains_message(self, capsys):
        alarm = make_alarm(msg="Workout")
        show_banner(alarm, is_missed=True)
        out = capsys.readouterr().out
        assert "Workout" in out

    def test_missed_banner_does_not_show_current_time(self, capsys):
        """Missed alarms should NOT show 'Now' — it's irrelevant."""
        show_banner(make_alarm(), is_missed=True)
        out = capsys.readouterr().out
        assert "Now" not in out

    def test_missed_banner_does_not_show_triggered_header(self, capsys):
        show_banner(make_alarm(), is_missed=True)
        out = capsys.readouterr().out
        assert "ALARM TRIGGERED" not in out


# ---------------------------------------------------------------------------
# show_list
# ---------------------------------------------------------------------------

class TestShowList:

    def test_empty_list_shows_helpful_hint(self, capsys):
        show_list([])
        out = capsys.readouterr().out
        assert "No alarms found" in out

    def test_shows_alarm_message(self, capsys):
        show_list([make_alarm(msg="Workout")])
        out = capsys.readouterr().out
        assert "Workout" in out

    def test_shows_alarm_id(self, capsys):
        show_list([make_alarm(id=7)])
        out = capsys.readouterr().out
        assert "7" in out

    def test_shows_pending_state_icon(self, capsys):
        show_list([make_alarm(state=AlarmState.PENDING)])
        out = capsys.readouterr().out
        assert "⏳" in out

    def test_shows_dismissed_state_icon(self, capsys):
        show_list([make_alarm(state=AlarmState.DISMISSED)])
        out = capsys.readouterr().out
        assert "✅" in out

    def test_shows_missed_state_icon(self, capsys):
        show_list([make_alarm(state=AlarmState.MISSED)])
        out = capsys.readouterr().out
        assert "❌" in out

    def test_shows_snooze_duration_when_set(self, capsys):
        show_list([make_alarm(snooze=5)])
        out = capsys.readouterr().out
        assert "5m" in out

    def test_shows_dash_when_snooze_not_set(self, capsys):
        show_list([make_alarm(snooze=None)])
        out = capsys.readouterr().out
        assert "—" in out

    def test_alarms_sorted_by_scheduled_time(self, capsys):
        """Earlier alarm should appear before later alarm in output."""
        early = make_alarm(id=2, msg="Early",  minutes=30)
        late  = make_alarm(id=1, msg="Late",   minutes=90)
        show_list([late, early])  # pass in reverse order
        out = capsys.readouterr().out
        assert out.index("Early") < out.index("Late")

    def test_long_message_is_truncated(self, capsys):
        long_msg = "A" * 50
        show_list([make_alarm(msg=long_msg)])
        out = capsys.readouterr().out
        # The full 50-char message should not appear — it's truncated to col width
        assert long_msg not in out

    def test_multiple_alarms_all_shown(self, capsys):
        alarms = [
            make_alarm(id=1, msg="First",  minutes=30),
            make_alarm(id=2, msg="Second", minutes=60),
            make_alarm(id=3, msg="Third",  minutes=90),
        ]
        show_list(alarms)
        out = capsys.readouterr().out
        assert "First"  in out
        assert "Second" in out
        assert "Third"  in out
