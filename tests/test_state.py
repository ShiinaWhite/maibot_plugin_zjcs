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
