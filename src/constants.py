"""
constants.py
------------
Central configuration for the alarm clock application.

All magic values live here. No logic, no imports from project modules.
Changing a value here propagates everywhere — nothing is hardcoded elsewhere.
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

# Path to the JSON alarm store.
# Resolved relative to the project root (parent of src/).
STORAGE_FILE: Path = Path(__file__).parent.parent / "alarms.json"

# Temporary file used during atomic writes.
# Written first; renamed to STORAGE_FILE on success.
STORAGE_TMP_FILE: Path = STORAGE_FILE.with_suffix(".json.tmp")

# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

# How often the scheduler checks for due alarms (seconds).
POLL_INTERVAL_SECONDS: int = 1

# How long an alarm stays in RINGING state before auto-transitioning to MISSED.
# Uses select.select() — no threads, no asyncio (macOS/Linux only).
ALARM_TIMEOUT_SECONDS: int = 60

# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

# Human-readable format used in terminal output.
# Example: "08:30 AM on Jun 04"
DATE_DISPLAY_FORMAT: str = "%I:%M %p on %b %d"

# ISO 8601 format used for JSON serialization (no timezone).
# Example: "2024-06-04T08:30:00"
DATE_STORAGE_FORMAT: str = "%Y-%m-%dT%H:%M:%S"

# Width of the alarm banner divider line.
BANNER_WIDTH: int = 48
