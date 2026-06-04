"""
parser.py
---------
Natural language time string → datetime conversion.

Responsibilities
----------------
- Accept a human-readable time string and return a naive local datetime
- Support inputs like: "8:30 PM", "tomorrow 7am", "in 10 minutes", "in 2 hours"
- Return None when the input cannot be parsed (no exceptions raised)
- Zero out seconds and microseconds to enforce minute-level granularity

What this module must NOT do
-----------------------------
- Reject past times — that is the caller's (cli.py) responsibility
- Print error messages — return None and let the caller decide
- Touch the filesystem or alarm state

Library choice: dateparser
--------------------------
dateparser handles the full range of required input formats out of the box:
  - Absolute times:  "8:30 PM", "07:00"
  - Relative times:  "in 10 minutes", "in 2 hours"
  - Natural dates:   "tomorrow 7am", "next Monday 9am"

python-dateutil was considered but does not handle relative phrases like
"in 10 minutes" without custom parsing logic. Manual regex would be brittle
and hard to test exhaustively. dateparser is the pragmatic choice.

Platform note
-------------
dateparser relies on the system locale for some date formats. All settings
below are explicit to avoid locale-dependent behaviour across machines.
"""

from __future__ import annotations

from datetime import datetime

import dateparser


# ---------------------------------------------------------------------------
# dateparser settings
# ---------------------------------------------------------------------------

_DATEPARSER_SETTINGS: dict = {
    # If the parsed time is ambiguous (e.g. "8:30 PM" when it is 9:00 PM),
    # prefer a future occurrence rather than returning a past datetime.
    # The caller still validates and rejects past times — this setting just
    # minimises surprising default behaviour.
    "PREFER_DATES_FROM": "future",

    # Always return naive (timezone-unaware) datetimes.
    # We work with local system time throughout the application.
    # Mixing naive and aware datetimes causes TypeError in Python.
    "RETURN_AS_TIMEZONE_AWARE": False,

    # Resolve ambiguous date-only inputs (e.g. "7/8") using DMY order.
    # Removes locale-dependent guessing on the developer's machine.
    "DATE_ORDER": "DMY",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_time(text: str) -> datetime | None:
    """
    Parse a human-readable time string into a naive local datetime.

    Seconds and microseconds are zeroed to enforce minute-level
    uniqueness across all alarms (Design Decision 1).

    Parameters
    ----------
    text : str
        A time expression in any supported format, for example:

        - ``"8:30 PM"``          — absolute time today (or tomorrow if past)
        - ``"tomorrow 7am"``     — next-day absolute time
        - ``"in 10 minutes"``    — relative offset from now
        - ``"in 2 hours"``       — relative offset from now

    Returns
    -------
    datetime | None
        A naive local ``datetime`` with seconds and microseconds set to
        zero, or ``None`` if ``text`` cannot be parsed.

    Notes
    -----
    This function does **not** reject past times — that validation belongs
    in ``cli.cmd_add()``, which can produce a user-facing error message.

    Examples
    --------
    >>> from src.parser import parse_time
    >>> dt = parse_time("in 10 minutes")
    >>> dt.second
    0
    >>> parse_time("not a date") is None
    True
    """
    result: datetime | None = dateparser.parse(text, settings=_DATEPARSER_SETTINGS)

    if result is None:
        return None

    # Zero out sub-minute precision to enforce the one-alarm-per-minute rule.
    return result.replace(second=0, microsecond=0)
