import json

import pytest

from state import NotificationState, StateFileError


def test_state_survives_reload_and_deduplicates(tmp_path) -> None:
    path = tmp_path / "notification_state.json"
    first = NotificationState(path).load()
    first.mark_sent("event:2026-01-03:2")
    first.mark_sent("event:2026-01-03:2")

    second = NotificationState(path).load()
    assert second.contains("event:2026-01-03:2")
    assert list(second.keys()) == ["event:2026-01-03:2"]


def test_invalid_state_fails_closed(tmp_path) -> None:
    path = tmp_path / "notification_state.json"
    path.write_text(json.dumps({"version": 1, "sent": "not-a-list"}), encoding="utf-8")

    with pytest.raises(StateFileError):
        NotificationState(path).load()


def test_mark_sent_many_persists_all_keys_with_one_write(tmp_path, monkeypatch) -> None:
    state = NotificationState(tmp_path / "notification_state.json").load()
    writes = 0
    original_write = state._write

    def count_write(sent: set[str]) -> None:
        nonlocal writes
        writes += 1
        original_write(sent)

    monkeypatch.setattr(state, "_write", count_write)

    state.mark_sent_many(["first", "second", "first"])

    assert writes == 1
    assert state.keys() == frozenset({"first", "second"})
    payload = json.loads(state.path.read_text(encoding="utf-8"))
    assert payload == {"version": 1, "sent": ["first", "second"]}


def test_mark_sent_many_write_failure_does_not_update_memory(
    tmp_path, monkeypatch
) -> None:
    state = NotificationState(tmp_path / "notification_state.json").load()

    def fail_write(_sent: set[str]) -> None:
        raise StateFileError("write failed")

    monkeypatch.setattr(state, "_write", fail_write)

    with pytest.raises(StateFileError):
        state.mark_sent_many(["first", "second"])

    assert state.keys() == frozenset()
