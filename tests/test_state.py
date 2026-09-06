import json

import pytest

from state import NotificationState, StateFileError


def test_state_survives_reload_and_deduplicates_per_group(tmp_path) -> None:
    path = tmp_path / "notification_state.json"
    first = NotificationState(path).load()
    first.mark_sent("111000111", "event:2026-01-03:2")
    first.mark_sent("111000111", "event:2026-01-03:2")

    second = NotificationState(path).load()
    assert second.contains("111000111", "event:2026-01-03:2")
    assert second.keys("111000111") == frozenset({"event:2026-01-03:2"})
    assert second.keys("222000222") == frozenset()
    assert not second.contains("222000222", "event:2026-01-03:2")


def test_group_states_are_isolated(tmp_path) -> None:
    state = NotificationState(tmp_path / "notification_state.json").load()
    state.mark_sent_many("111000111", ["k1", "k2"])
    state.mark_sent_many("222000222", ["k1"])

    reloaded = NotificationState(tmp_path / "notification_state.json").load()
    assert reloaded.contains("111000111", "k1")
    assert reloaded.contains("111000111", "k2")
    assert reloaded.contains("222000222", "k1")
    assert not reloaded.contains("222000222", "k2")
    assert not reloaded.contains("333000333", "k1")


def test_invalid_state_fails_closed(tmp_path) -> None:
    path = tmp_path / "notification_state.json"
    path.write_text(
        json.dumps({"version": 2, "groups": "not-a-dict"}), encoding="utf-8"
    )

    with pytest.raises(StateFileError):
        NotificationState(path).load()


def test_invalid_group_entry_fails_closed(tmp_path) -> None:
    path = tmp_path / "notification_state.json"
    path.write_text(
        json.dumps({"version": 2, "groups": {"111000111": ["k1", 42]}}),
        encoding="utf-8",
    )

    with pytest.raises(StateFileError):
        NotificationState(path).load()


def test_v1_state_fails_closed_until_migrated(tmp_path) -> None:
    path = tmp_path / "notification_state.json"
    path.write_text(json.dumps({"version": 1, "sent": ["k1"]}), encoding="utf-8")

    with pytest.raises(StateFileError):
        NotificationState(path).load()

    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 1


def test_mark_sent_many_persists_all_keys_with_one_write(tmp_path, monkeypatch) -> None:
    state = NotificationState(tmp_path / "notification_state.json").load()
    writes = 0
    original_write = state._write

    def count_write(group_id: str, sent: set[str]) -> None:
        nonlocal writes
        writes += 1
        original_write(group_id, sent)

    monkeypatch.setattr(state, "_write", count_write)

    state.mark_sent_many("111000111", ["first", "second", "first"])

    assert writes == 1
    assert state.keys("111000111") == frozenset({"first", "second"})
    payload = json.loads(state.path.read_text(encoding="utf-8"))
    assert payload == {"version": 2, "groups": {"111000111": ["first", "second"]}}


def test_mark_sent_many_write_failure_does_not_update_memory(
    tmp_path, monkeypatch
) -> None:
    state = NotificationState(tmp_path / "notification_state.json").load()

    def fail_write(_group_id: str, _sent: set[str]) -> None:
        raise StateFileError("write failed")

    monkeypatch.setattr(state, "_write", fail_write)

    with pytest.raises(StateFileError):
        state.mark_sent_many("111000111", ["first", "second"])

    assert state.keys("111000111") == frozenset()


def test_mark_sent_rejects_invalid_arguments(tmp_path) -> None:
    state = NotificationState(tmp_path / "notification_state.json").load()

    with pytest.raises(ValueError):
        state.mark_sent("", "k1")
    with pytest.raises(ValueError):
        state.mark_sent_many("111000111", [""])
    with pytest.raises(ValueError):
        state.mark_sent_many("111000111", [])


def test_migrate_v1_state_assigns_keys_only_to_legacy_group(tmp_path) -> None:
    path = tmp_path / "notification_state.json"
    path.write_text(json.dumps({"version": 1, "sent": ["k2", "k1"]}), encoding="utf-8")

    assert NotificationState.migrate_v1_file(path, "611817038") is True

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload == {"version": 2, "groups": {"611817038": ["k1", "k2"]}}

    reloaded = NotificationState(path).load()
    assert reloaded.contains("611817038", "k1")
    assert reloaded.contains("611817038", "k2")
    assert not reloaded.contains("999999999", "k1")
    assert reloaded.keys("999999999") == frozenset()


def test_migrate_v1_state_is_noop_for_v2_or_missing_file(tmp_path) -> None:
    path = tmp_path / "notification_state.json"

    assert NotificationState.migrate_v1_file(path, "111000111") is False

    path.write_text(
        json.dumps({"version": 2, "groups": {"111000111": ["k1"]}}), encoding="utf-8"
    )
    assert NotificationState.migrate_v1_file(path, "222000222") is False
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["groups"] == {"111000111": ["k1"]}


def test_migrate_v1_state_without_legacy_group_fails_and_keeps_file(tmp_path) -> None:
    path = tmp_path / "notification_state.json"
    path.write_text(json.dumps({"version": 1, "sent": ["k1"]}), encoding="utf-8")

    with pytest.raises(StateFileError):
        NotificationState.migrate_v1_file(path, None)
    with pytest.raises(StateFileError):
        NotificationState.migrate_v1_file(path, "  ")

    assert json.loads(path.read_text(encoding="utf-8")) == {
        "version": 1,
        "sent": ["k1"],
    }


def test_migrate_v1_state_rejects_invalid_sent_list(tmp_path) -> None:
    path = tmp_path / "notification_state.json"
    path.write_text(json.dumps({"version": 1, "sent": "not-a-list"}), encoding="utf-8")

    with pytest.raises(StateFileError):
        NotificationState.migrate_v1_file(path, "111000111")

    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 1
