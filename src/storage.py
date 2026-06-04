"""
storage.py
----------
JSON persistence layer for the alarm clock application.

Responsibilities
----------------
- Load and save the alarm list to/from alarms.json
- Provide CRUD operations: add, update, delete, find
- Guarantee atomic writes (no partial/corrupt JSON on crash)
- Assign auto-incrementing IDs on creation

What this module must NOT do
-----------------------------
- Validate state transitions (that is models.py's job)
- Parse time strings (that is parser.py's job)
- Print output (that is notifier.py's job)

Atomic write strategy
---------------------
All saves go through _atomic_write(), which writes to a .tmp file and
then calls os.replace() to rename it. os.replace() is atomic on POSIX
systems (macOS / Linux) — the file is never left in a partial state if
the process is interrupted mid-write.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from src.constants import DATE_STORAGE_FORMAT, STORAGE_FILE, STORAGE_TMP_FILE
from src.models import Alarm


class StorageError(Exception):
    """
    Raised when alarms.json cannot be read, parsed, or written.

    Distinct from a generic Exception so callers can catch persistence
    failures specifically without accidentally swallowing logic errors.
    """


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _atomic_write(data: list[dict], path: Path, tmp_path: Path) -> None:
    """
    Write *data* to *path* using an atomic rename via *tmp_path*.

    Writes JSON to *tmp_path* first, then calls ``os.replace()`` to
    rename it to *path*. Because ``os.replace()`` is atomic on POSIX
    systems, *path* is never left in a partially-written state.

    Parameters
    ----------
    data     : List of alarm dictionaries to serialise.
    path     : Final destination file (e.g. alarms.json).
    tmp_path : Temporary staging file (e.g. alarms.json.tmp).

    Raises
    ------
    StorageError
        If the file cannot be written.
    """
    try:
        tmp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp_path, path)
    except OSError as exc:
        raise StorageError(f"Failed to write alarm data: {exc}") from exc


def _next_id(alarms: list[Alarm]) -> int:
    """
    Return the next available alarm ID.

    IDs are positive integers starting at 1.  The next ID is always
    ``max(existing ids) + 1`` so deleted IDs are never reused.

    Parameters
    ----------
    alarms : The current list of alarms (may be empty).

    Returns
    -------
    int
        The next available ID.
    """
    if not alarms:
        return 1
    return max(a.id for a in alarms) + 1


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_alarms(path: Path = STORAGE_FILE) -> list[Alarm]:
    """
    Load all alarms from the JSON store.

    Returns an empty list if the file does not exist yet (first run).
    Raises ``StorageError`` if the file exists but cannot be parsed —
    a missing file is expected; a corrupted file is not.

    Parameters
    ----------
    path : Path to the JSON store. Defaults to ``STORAGE_FILE``.

    Returns
    -------
    list[Alarm]
        All persisted alarms, in storage order.

    Raises
    ------
    StorageError
        If the file exists but contains invalid JSON.
    """
    if not path.exists():
        return []

    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise StorageError(
            f"alarms.json is corrupted and cannot be parsed: {exc}"
        ) from exc
    except OSError as exc:
        raise StorageError(f"Cannot read alarms.json: {exc}") from exc

    return [Alarm.from_dict(d) for d in data]


def save_alarms(alarms: list[Alarm], path: Path = STORAGE_FILE) -> None:
    """
    Persist the full alarm list to the JSON store.

    Uses an atomic write (tmp file + os.replace) so the store is never
    left in a partial state on crash.

    Parameters
    ----------
    alarms : The complete list of alarms to persist.
    path   : Destination file. Defaults to ``STORAGE_FILE``.

    Raises
    ------
    StorageError
        If the file cannot be written.
    """
    data = [alarm.to_dict() for alarm in alarms]
    _atomic_write(data, path, STORAGE_TMP_FILE)


def add_alarm(alarm: Alarm, path: Path = STORAGE_FILE) -> Alarm:
    """
    Assign an ID to *alarm*, append it to the store, and persist.

    The alarm's ``id`` field is overwritten with the next available ID.
    The caller should treat the *returned* alarm as authoritative.

    Parameters
    ----------
    alarm : An ``Alarm`` instance with ``id=0`` (ID not yet assigned).
    path  : Destination file. Defaults to ``STORAGE_FILE``.

    Returns
    -------
    Alarm
        The same alarm object with its ``id`` field populated.

    Raises
    ------
    StorageError
        If the store cannot be read or written.
    """
    alarms = load_alarms(path)
    alarm.id = _next_id(alarms)
    alarms.append(alarm)
    save_alarms(alarms, path)
    return alarm


def update_alarm(alarm: Alarm, path: Path = STORAGE_FILE) -> None:
    """
    Replace the stored alarm that matches *alarm.id* and persist.

    Reloads the alarm list from disk before writing to avoid overwriting
    changes made between the last load and this call.

    Parameters
    ----------
    alarm : The updated ``Alarm`` instance. Must have a valid ``id``.
    path  : Destination file. Defaults to ``STORAGE_FILE``.

    Raises
    ------
    StorageError
        If ``alarm.id`` is not found, or the store cannot be read/written.
    """
    alarms = load_alarms(path)
    for i, existing in enumerate(alarms):
        if existing.id == alarm.id:
            alarms[i] = alarm
            save_alarms(alarms, path)
            return
    raise StorageError(
        f"Cannot update: alarm with id={alarm.id} not found in store."
    )


def delete_alarm(alarm_id: int, path: Path = STORAGE_FILE) -> bool:
    """
    Remove the alarm with the given ID from the store and persist.

    Parameters
    ----------
    alarm_id : The ID of the alarm to remove.
    path     : Destination file. Defaults to ``STORAGE_FILE``.

    Returns
    -------
    bool
        ``True`` if an alarm was found and deleted; ``False`` if no alarm
        with that ID existed (caller decides how to surface this).

    Raises
    ------
    StorageError
        If the store cannot be read or written.
    """
    alarms = load_alarms(path)
    filtered = [a for a in alarms if a.id != alarm_id]

    if len(filtered) == len(alarms):
        return False  # nothing removed

    save_alarms(filtered, path)
    return True


def find_by_id(alarm_id: int, alarms: list[Alarm]) -> Alarm | None:
    """
    Return the alarm with the given ID from an in-memory list.

    Operates on a pre-loaded list — does not touch the filesystem.

    Parameters
    ----------
    alarm_id : The ID to look up.
    alarms   : An already-loaded list of alarms.

    Returns
    -------
    Alarm | None
        The matching alarm, or ``None`` if not found.
    """
    for alarm in alarms:
        if alarm.id == alarm_id:
            return alarm
    return None


def find_by_time(scheduled_time: datetime, alarms: list[Alarm]) -> Alarm | None:
    """
    Return the alarm scheduled at the given time (minute-level match).

    Seconds and microseconds are stripped from both sides before
    comparing, enforcing the one-alarm-per-minute uniqueness rule
    (Design Decision 1).

    Operates on a pre-loaded list — does not touch the filesystem.

    Parameters
    ----------
    scheduled_time : The datetime to search for (seconds ignored).
    alarms         : An already-loaded list of alarms.

    Returns
    -------
    Alarm | None
        The matching alarm, or ``None`` if no alarm occupies that minute.
    """
    target = scheduled_time.replace(second=0, microsecond=0)
    for alarm in alarms:
        candidate = alarm.scheduled_time.replace(second=0, microsecond=0)
        if candidate == target:
            return alarm
    return None
