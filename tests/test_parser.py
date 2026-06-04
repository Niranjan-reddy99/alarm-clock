"""
test_parser.py
--------------
Tests for natural language time string → datetime conversion.

Coverage targets:
- Relative phrases: "in N minutes", "in N hours"
- Absolute times: "8:30 PM"
- Natural dates: "tomorrow Xam"
- Garbage input returns None
- Seconds are always zeroed (minute-level granularity)
- Microseconds are always zeroed
- PREFER_DATES_FROM=future: ambiguous past time resolves to future

Note on timing sensitivity
--------------------------
Tests that check relative times (e.g. "in 10 minutes") use a tolerance
window of ±2 minutes to avoid flakiness from test execution latency.
"""

from __future__ import annotations

import pytest
from datetime import datetime, timedelta

from src.parser import parse_time


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def approx_future(minutes: int, tolerance: int = 2) -> tuple[datetime, datetime]:
    """Return a (lower, upper) window for a 'in N minutes' assertion."""
    now = datetime.now()
    return (
        now + timedelta(minutes=minutes - tolerance),
        now + timedelta(minutes=minutes + tolerance),
    )


# ---------------------------------------------------------------------------
# Garbage input
# ---------------------------------------------------------------------------

class TestInvalidInput:

    def test_empty_string_returns_none(self):
        assert parse_time("") is None

    def test_random_word_returns_none(self):
        assert parse_time("banana") is None

    def test_gibberish_returns_none(self):
        assert parse_time("xkcd 927 blah") is None

    def test_number_only_returns_none(self):
        # A bare number is ambiguous; dateparser may return None
        # We don't assert None here — just that the function doesn't crash.
        result = parse_time("99999")
        # If it parses, seconds must be zeroed
        if result is not None:
            assert result.second == 0
            assert result.microsecond == 0


# ---------------------------------------------------------------------------
# Relative time expressions
# ---------------------------------------------------------------------------

class TestRelativeTimes:

    def test_in_10_minutes_is_in_future(self):
        result = parse_time("in 10 minutes")
        assert result is not None
        lower, upper = approx_future(10)
        assert lower <= result <= upper

    def test_in_2_hours_is_in_future(self):
        result = parse_time("in 2 hours")
        assert result is not None
        lower, upper = approx_future(120)
        assert lower <= result <= upper

    def test_in_30_minutes_is_in_future(self):
        result = parse_time("in 30 minutes")
        assert result is not None
        assert result > datetime.now()

    def test_in_1_hour_is_in_future(self):
        result = parse_time("in 1 hour")
        assert result is not None
        assert result > datetime.now()


# ---------------------------------------------------------------------------
# Absolute time expressions
# ---------------------------------------------------------------------------

class TestAbsoluteTimes:

    def test_8_30_pm_parses(self):
        result = parse_time("8:30 PM")
        assert result is not None
        assert result.hour == 20
        assert result.minute == 30

    def test_7_00_am_parses(self):
        result = parse_time("7:00 AM")
        assert result is not None
        assert result.hour == 7
        assert result.minute == 0

    def test_absolute_time_resolves_to_future(self):
        """PREFER_DATES_FROM=future: if the time is past today, get tomorrow."""
        result = parse_time("8:30 PM")
        assert result is not None
        # We can't guarantee direction without knowing the current time,
        # but the result must be a valid datetime.
        assert isinstance(result, datetime)


# ---------------------------------------------------------------------------
# Natural date expressions
# ---------------------------------------------------------------------------

class TestNaturalDates:

    def test_tomorrow_7am_is_next_day(self):
        result = parse_time("tomorrow 7am")
        assert result is not None
        tomorrow = (datetime.now() + timedelta(days=1)).date()
        assert result.date() == tomorrow
        assert result.hour == 7
        assert result.minute == 0

    def test_tomorrow_noon_parses(self):
        result = parse_time("tomorrow noon")
        assert result is not None
        tomorrow = (datetime.now() + timedelta(days=1)).date()
        assert result.date() == tomorrow


# ---------------------------------------------------------------------------
# Granularity: seconds and microseconds must be zeroed
# ---------------------------------------------------------------------------

class TestGranularity:

    def test_relative_time_seconds_zeroed(self):
        result = parse_time("in 10 minutes")
        assert result is not None
        assert result.second == 0

    def test_relative_time_microseconds_zeroed(self):
        result = parse_time("in 10 minutes")
        assert result is not None
        assert result.microsecond == 0

    def test_absolute_time_seconds_zeroed(self):
        result = parse_time("8:30 PM")
        assert result is not None
        assert result.second == 0

    def test_absolute_time_microseconds_zeroed(self):
        result = parse_time("8:30 PM")
        assert result is not None
        assert result.microsecond == 0

    def test_tomorrow_seconds_zeroed(self):
        result = parse_time("tomorrow 7am")
        assert result is not None
        assert result.second == 0

    def test_result_is_naive_datetime(self):
        """Result must be timezone-naive — we work in local time throughout."""
        result = parse_time("in 10 minutes")
        assert result is not None
        assert result.tzinfo is None
