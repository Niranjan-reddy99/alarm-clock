"""
models.py
---------
Domain model for the alarm clock application.

This module defines the Alarm entity and the AlarmState enum.
All state transitions MUST go through Alarm.transition() — never assign
alarm.state directly from outside this module.

State machine
-------------
    pending  → ringing   (scheduler detects due time)
    pending  → missed    (startup recovery: alarm fired while app was off)
    ringing  → dismissed (user presses [D])
    ringing  → pending   (user presses [S]; snooze reschedules the alarm)
    ringing  → missed    (60-second timeout, no user input)
    dismissed → (terminal state — no further transitions)
    missed    → (terminal state — no further transitions)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from src.constants import DATE_DISPLAY_FORMAT, DATE_STORAGE_FORMAT


class AlarmState(str, Enum):
    """
    Lifecycle states for an alarm.

    Inherits from ``str`` so each value is its own JSON-serializable string —
    no ``.value`` calls required when writing to or reading from JSON.

    Example::

        AlarmState.PENDING == "pending"  # True
        json.dumps(AlarmState.PENDING)   # '"pending"'
    """

    PENDING = "pending"
    RINGING = "ringing"
    DISMISSED = "dismissed"
    MISSED = "missed"


# ---------------------------------------------------------------------------
# State machine definition
# ---------------------------------------------------------------------------

# Maps each state to the set of states it may legally transition into.
# frozenset prevents accidental mutation at runtime.
# This table is the single authoritative definition of the state machine.
VALID_TRANSITIONS: dict[AlarmState, frozenset[AlarmState]] = {
    AlarmState.PENDING: frozenset({
        AlarmState.RINGING,    # normal trigger
        AlarmState.MISSED,     # startup recovery
    }),
    AlarmState.RINGING: frozenset({
        AlarmState.DISMISSED,  # user pressed [D]
        AlarmState.PENDING,    # user pressed [S] — snooze reschedules
        AlarmState.MISSED,     # 60-second timeout
    }),
    AlarmState.DISMISSED: frozenset(),  # terminal — no outbound transitions
    AlarmState.MISSED: frozenset(),     # terminal — no outbound transitions
}


# ---------------------------------------------------------------------------
# Alarm entity
# ---------------------------------------------------------------------------

@dataclass
class Alarm:
    """
    Represents a single scheduled alarm.

    Attributes
    ----------
    id : int
        Unique integer identifier. Assigned by storage on creation (starts at 1).
    message : str
        Human-readable label displayed when the alarm rings.
    scheduled_time : datetime
        When the alarm should trigger. Naive local datetime, seconds zeroed
        to enforce minute-level uniqueness (see Design Decision 1).
    state : AlarmState
        Current lifecycle state. **Never assign directly** — always call
        ``transition()`` so the state machine rules are enforced.
    snooze_minutes : int | None
        Snooze duration in minutes. ``None`` means snooze is not enabled;
        the [S] option will not be shown when the alarm rings.
    created_at : datetime
        When the alarm record was created. Naive local datetime.
    """

    id: int
    message: str
    scheduled_time: datetime
    state: AlarmState
    snooze_minutes: int | None
    created_at: datetime

    # ------------------------------------------------------------------
    # State machine
    # ------------------------------------------------------------------

    def transition(self, new_state: AlarmState) -> None:
        """
        Apply a state transition, enforcing the valid transition table.

        This is the **only** method that may write to ``self.state``.
        All modules that change alarm state must go through here.

        Parameters
        ----------
        new_state : AlarmState
            The target state to transition into.

        Raises
        ------
        ValueError
            If transitioning from the current state to ``new_state`` is
            not permitted by ``VALID_TRANSITIONS``.

        Example::

            alarm.transition(AlarmState.RINGING)   # OK if pending
            alarm.transition(AlarmState.DISMISSED)  # OK if ringing
            alarm.transition(AlarmState.PENDING)    # ValueError if dismissed
        """
        allowed = VALID_TRANSITIONS[self.state]
        if new_state not in allowed:
            allowed_names = [s.value for s in allowed] if allowed else ["none (terminal state)"]
            raise ValueError(
                f"Invalid transition: {self.state.value!r} → {new_state.value!r}. "
                f"Allowed from {self.state.value!r}: {allowed_names}."
            )
        self.state = new_state

    # ------------------------------------------------------------------
    # Scheduling helpers
    # ------------------------------------------------------------------

    def is_due(self) -> bool:
        """
        Return ``True`` if this alarm should ring right now.

        An alarm is due when it is ``PENDING`` and its ``scheduled_time``
        is at or before the current local time (``<=``).

        Used by the scheduler's main poll loop to decide which alarm to ring.
        """
        return (
            self.state == AlarmState.PENDING
            and self.scheduled_time <= datetime.now()
        )

    def is_overdue(self) -> bool:
        """
        Return ``True`` if this alarm fired while the scheduler was not running.

        Uses strict less-than (``<``) rather than ``<=``. This prevents an alarm
        whose scheduled_time is *right now* from being immediately marked
        ``MISSED`` during startup recovery — the main poll loop should ring it.

        Used only in ``scheduler.handle_startup_missed()``.
        """
        return (
            self.state == AlarmState.PENDING
            and self.scheduled_time < datetime.now()
        )

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """
        Serialize this alarm to a JSON-compatible dictionary.

        Datetimes are formatted with ``DATE_STORAGE_FORMAT`` (ISO 8601,
        no timezone). ``snooze_minutes`` may be ``None``.

        Returns
        -------
        dict
            A flat dictionary ready for ``json.dumps``.
        """
        return {
            "id": self.id,
            "message": self.message,
            "scheduled_time": self.scheduled_time.strftime(DATE_STORAGE_FORMAT),
            "state": self.state.value,
            "snooze_minutes": self.snooze_minutes,
            "created_at": self.created_at.strftime(DATE_STORAGE_FORMAT),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Alarm":
        """
        Deserialize an alarm from a dictionary loaded from ``alarms.json``.

        Parameters
        ----------
        data : dict
            A dictionary with keys matching ``Alarm`` field names.

        Returns
        -------
        Alarm
            A fully populated ``Alarm`` instance.

        Raises
        ------
        KeyError
            If a required field is absent from ``data``.
        ValueError
            If a field contains an unrecognized value (e.g. unknown state string).
        """
        return cls(
            id=data["id"],
            message=data["message"],
            scheduled_time=datetime.strptime(data["scheduled_time"], DATE_STORAGE_FORMAT),
            state=AlarmState(data["state"]),
            snooze_minutes=data.get("snooze_minutes"),  # None if key absent or value is null
            created_at=datetime.strptime(data["created_at"], DATE_STORAGE_FORMAT),
        )

    # ------------------------------------------------------------------
    # Display helpers
    # ------------------------------------------------------------------

    def formatted_time(self) -> str:
        """Return ``scheduled_time`` formatted for terminal display.

        Example: ``'08:30 AM on Jun 04'``
        """
        return self.scheduled_time.strftime(DATE_DISPLAY_FORMAT)

    def __str__(self) -> str:
        snooze_part = f", snooze={self.snooze_minutes}m" if self.snooze_minutes else ""
        return (
            f"Alarm(id={self.id}, state={self.state.value!r}, "
            f"time={self.formatted_time()!r}, message={self.message!r}{snooze_part})"
        )
