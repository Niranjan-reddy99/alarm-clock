"""
test_storage.py
---------------
Tests for JSON persistence: load, save, add, update, delete, find.

All tests use pytest's tmp_path fixture so they operate on isolated
temporary files — alarms.json on disk is never touched by the test suite.

Coverage targets:
- load_alarms: missing file, corrupted file, valid file
- add_alarm: ID assignment, incrementing, persistence
- update_alarm: state change persisted, unknown ID raises
- delete_alarm: removes correct alarm, returns False for unknown ID
- find_by_id: found and not-found cases
- find_by_time: minute-level match, seconds ignored, not-found case
- atomic write: tmp file cleaned up after successful write
"""

from __future__ import annotations

import json
import pytest
from datetime import datetime, timedelta
from pathlib import Path

from src.models import Alarm, AlarmState
from src.storage import (
    StorageError,
    add_alarm,
    delete_alarm,
    find_by_id,
    find_by_time,
    load_alarms,
    save_alarms,
    update_alarm,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_alarm(
    msg: str = "Test",
    minutes: int = 60,
    state: AlarmState = AlarmState.PENDING,
    snooze: int | None = None,
) -> Alarm:
    """Build an unsaved Alarm with id=0."""
    now = datetime.now().replace(second=0, microsecond=0)
    return Alarm(
        id=0,
        message=msg,
        scheduled_time=now + timedelta(minutes=minutes),
        state=state,
        snooze_minutes=snooze,
        created_at=now,
    )


def storage_paths(tmp_path: Path) -> tuple[Path, Path]:
    """Return (store, tmp) paths inside pytest's tmp_path."""
    store = tmp_path / "alarms.json"
    tmp   = tmp_path / "alarms.json.tmp"
    return store, tmp


# ---------------------------------------------------------------------------
# load_alarms
# ---------------------------------------------------------------------------

class TestLoadAlarms:

    def test_missing_file_returns_empty_list(self, tmp_path):
        store, _ = storage_paths(tmp_path)
        result = load_alarms(store)
        assert result == []

    def test_empty_json_array_returns_empty_list(self, tmp_path):
        store, _ = storage_paths(tmp_path)
        store.write_text("[]", encoding="utf-8")
        result = load_alarms(store)
        assert result == []

    def test_corrupted_json_raises_storage_error(self, tmp_path):
        store, _ = storage_paths(tmp_path)
        store.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(StorageError, match="corrupted"):
            load_alarms(store)

    def test_loads_all_alarms(self, tmp_path):
        store, tmp = storage_paths(tmp_path)
        a1 = add_alarm(make_alarm("Workout"), store)
        a2 = add_alarm(make_alarm("Meeting"), store)
        loaded = load_alarms(store)
        assert len(loaded) == 2
        assert {a.id for a in loaded} == {a1.id, a2.id}

    def test_all_fields_preserved_after_load(self, tmp_path):
        store, _ = storage_paths(tmp_path)
        original = make_alarm("Workout", snooze=5)
        saved = add_alarm(original, store)
        loaded = load_alarms(store)[0]

        assert loaded.id            == saved.id
        assert loaded.message       == saved.message
        assert loaded.state         == saved.state
        assert loaded.snooze_minutes == saved.snooze_minutes
        assert loaded.scheduled_time == saved.scheduled_time


# ---------------------------------------------------------------------------
# add_alarm
# ---------------------------------------------------------------------------

class TestAddAlarm:

    def test_first_alarm_gets_id_1(self, tmp_path):
        store, _ = storage_paths(tmp_path)
        saved = add_alarm(make_alarm("First"), store)
        assert saved.id == 1

    def test_second_alarm_gets_id_2(self, tmp_path):
        store, _ = storage_paths(tmp_path)
        add_alarm(make_alarm("First"), store)
        saved = add_alarm(make_alarm("Second", minutes=120), store)
        assert saved.id == 2

    def test_ids_never_reused_after_delete(self, tmp_path):
        """Deleting alarm #1 should not cause the next alarm to reuse id=1."""
        store, _ = storage_paths(tmp_path)
        a1 = add_alarm(make_alarm("First"),          store)
        _  = add_alarm(make_alarm("Second", minutes=120), store)
        delete_alarm(a1.id, store)
        a3 = add_alarm(make_alarm("Third",  minutes=180), store)
        assert a3.id == 3  # not 1

    def test_add_alarm_returns_alarm_with_id(self, tmp_path):
        store, _ = storage_paths(tmp_path)
        unsaved = make_alarm("Test")
        assert unsaved.id == 0
        saved = add_alarm(unsaved, store)
        assert saved.id != 0

    def test_added_alarm_persisted_to_disk(self, tmp_path):
        store, _ = storage_paths(tmp_path)
        add_alarm(make_alarm("Persist Me"), store)
        raw = json.loads(store.read_text())
        assert len(raw) == 1
        assert raw[0]["message"] == "Persist Me"


# ---------------------------------------------------------------------------
# update_alarm
# ---------------------------------------------------------------------------

class TestUpdateAlarm:

    def test_state_change_is_persisted(self, tmp_path):
        store, _ = storage_paths(tmp_path)
        alarm = add_alarm(make_alarm("Workout"), store)

        alarm.transition(AlarmState.RINGING)
        update_alarm(alarm, store)

        reloaded = load_alarms(store)
        assert find_by_id(alarm.id, reloaded).state == AlarmState.RINGING

    def test_scheduled_time_change_is_persisted(self, tmp_path):
        """Snooze rescheduling should survive a reload."""
        store, _ = storage_paths(tmp_path)
        alarm = add_alarm(make_alarm("Snooze Me", snooze=5), store)
        new_time = datetime.now().replace(second=0, microsecond=0) + timedelta(minutes=5)
        alarm.scheduled_time = new_time
        update_alarm(alarm, store)

        reloaded = load_alarms(store)
        assert find_by_id(alarm.id, reloaded).scheduled_time == new_time

    def test_unknown_id_raises_storage_error(self, tmp_path):
        store, _ = storage_paths(tmp_path)
        ghost = make_alarm("Ghost")
        ghost.id = 999
        with pytest.raises(StorageError, match="not found"):
            update_alarm(ghost, store)


# ---------------------------------------------------------------------------
# delete_alarm
# ---------------------------------------------------------------------------

class TestDeleteAlarm:

    def test_delete_removes_alarm(self, tmp_path):
        store, _ = storage_paths(tmp_path)
        a = add_alarm(make_alarm("Gone"), store)
        result = delete_alarm(a.id, store)
        assert result is True
        assert load_alarms(store) == []

    def test_delete_removes_correct_alarm(self, tmp_path):
        store, _ = storage_paths(tmp_path)
        a1 = add_alarm(make_alarm("Keep",   minutes=60),  store)
        a2 = add_alarm(make_alarm("Delete", minutes=120), store)
        delete_alarm(a2.id, store)
        remaining = load_alarms(store)
        assert len(remaining) == 1
        assert remaining[0].id == a1.id

    def test_delete_unknown_id_returns_false(self, tmp_path):
        store, _ = storage_paths(tmp_path)
        result = delete_alarm(999, store)
        assert result is False

    def test_delete_does_not_affect_other_alarms(self, tmp_path):
        store, _ = storage_paths(tmp_path)
        a1 = add_alarm(make_alarm("Stay",   minutes=60),  store)
        a2 = add_alarm(make_alarm("Go",     minutes=120), store)
        delete_alarm(a2.id, store)
        reloaded = load_alarms(store)
        assert find_by_id(a1.id, reloaded) is not None


# ---------------------------------------------------------------------------
# find_by_id
# ---------------------------------------------------------------------------

class TestFindById:

    def test_returns_alarm_when_found(self, tmp_path):
        store, _ = storage_paths(tmp_path)
        saved = add_alarm(make_alarm("Target"), store)
        alarms = load_alarms(store)
        result = find_by_id(saved.id, alarms)
        assert result is not None
        assert result.message == "Target"

    def test_returns_none_when_not_found(self, tmp_path):
        store, _ = storage_paths(tmp_path)
        alarms = load_alarms(store)
        assert find_by_id(999, alarms) is None


# ---------------------------------------------------------------------------
# find_by_time
# ---------------------------------------------------------------------------

class TestFindByTime:

    def test_exact_minute_match(self, tmp_path):
        store, _ = storage_paths(tmp_path)
        saved = add_alarm(make_alarm("Match"), store)
        alarms = load_alarms(store)
        result = find_by_time(saved.scheduled_time, alarms)
        assert result is not None
        assert result.id == saved.id

    def test_matches_ignoring_seconds(self, tmp_path):
        """find_by_time must match at the minute level — seconds are irrelevant."""
        store, _ = storage_paths(tmp_path)
        saved = add_alarm(make_alarm("SecondTest"), store)
        alarms = load_alarms(store)

        # Query with a different seconds value in the same minute
        query = saved.scheduled_time.replace(second=45)
        result = find_by_time(query, alarms)
        assert result is not None
        assert result.id == saved.id

    def test_returns_none_for_unoccupied_slot(self, tmp_path):
        store, _ = storage_paths(tmp_path)
        add_alarm(make_alarm("Occupied", minutes=60), store)
        alarms = load_alarms(store)

        unoccupied = datetime.now().replace(second=0, microsecond=0) + timedelta(minutes=99)
        assert find_by_time(unoccupied, alarms) is None

    def test_does_not_match_different_minute(self, tmp_path):
        store, _ = storage_paths(tmp_path)
        saved = add_alarm(make_alarm("Minute"), store)
        alarms = load_alarms(store)

        different_minute = saved.scheduled_time + timedelta(minutes=1)
        assert find_by_time(different_minute, alarms) is None


# ---------------------------------------------------------------------------
# Atomic write
# ---------------------------------------------------------------------------

class TestAtomicWrite:

    def test_tmp_file_removed_after_save(self, tmp_path):
        """The .tmp staging file should not exist after a successful write."""
        store = tmp_path / "alarms.json"
        tmp   = tmp_path / "alarms.json.tmp"
        save_alarms([make_alarm("Test")], store)
        assert not tmp.exists()

    def test_store_file_created_by_save(self, tmp_path):
        store, _ = storage_paths(tmp_path)
        assert not store.exists()
        save_alarms([], store)
        assert store.exists()
