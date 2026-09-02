from __future__ import annotations

import asyncio
from datetime import date, datetime, time
import json
from types import SimpleNamespace

import pytest

import plugin
from plugin import ZjcsGuildNotifier, _choose_due_check_date


class FakeChat:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls: list[dict[str, str]] = []

    async def open_session(self, **kwargs: str) -> object:
        self.calls.append(kwargs)
        return self.result


class FakeSend:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls: list[tuple[str, str, bool]] = []

    async def text(
        self, message: str, stream_id: str, return_details: bool = False
    ) -> object:
        self.calls.append((message, stream_id, return_details))
        return self.result


def make_context(tmp_path, *, send_result: object = {"sent": True}) -> SimpleNamespace:
    return SimpleNamespace(
        paths=SimpleNamespace(data_dir=tmp_path),
        chat=FakeChat({"success": True, "stream": {"stream_id": "stream-123"}}),
        send=FakeSend(send_result),
    )


def make_config() -> dict[str, object]:
    return {
        "plugin": {"enabled": True, "config_version": "1.0.0"},
        "target": {"group_id": "123456"},
        "server": {"open_date": "2026-01-01", "season_anchor_dates": {}},
        "schedule": {
            "daily_check_time": "09:00",
            "timezone": "Asia/Shanghai",
            "remind_days_before": [2],
        },
    }


def write_timeline(tmp_path) -> None:
    (tmp_path / "timeline.json").write_text(
        json.dumps(
            {
                "dungeons": [
                    {
                        "id": "test_dungeon",
                        "name": "测试副本",
                        "server_day": 3,
                        "region": "测试区",
                        "requirements": {"普通": 10_000},
                        "status": "confirmed",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_daily_check_resolves_group_and_marks_only_success(
    tmp_path, monkeypatch
) -> None:
    write_timeline(tmp_path)
    monkeypatch.setattr(plugin, "TIMELINE_PATH", tmp_path / "timeline.json")
    instance = ZjcsGuildNotifier()
    instance._ctx = make_context(tmp_path)
    instance.set_plugin_config(make_config())

    await instance._run_daily_check(today=date(2026, 1, 1))
    await instance._run_daily_check(today=date(2026, 1, 1))

    assert len(instance.ctx.chat.calls) == 1
    assert instance.ctx.chat.calls[0] == {
        "platform": "qq",
        "chat_type": "group",
        "group_id": "123456",
    }
    assert len(instance.ctx.send.calls) == 1
    assert instance.ctx.send.calls[0][1:] == ("stream-123", True)
    state = json.loads(
        (tmp_path / "notification_state.json").read_text(encoding="utf-8")
    )
    assert state["sent"] == ["test_dungeon:2026-01-03:2"]


@pytest.mark.asyncio
async def test_failed_send_is_not_marked(tmp_path, monkeypatch) -> None:
    write_timeline(tmp_path)
    monkeypatch.setattr(plugin, "TIMELINE_PATH", tmp_path / "timeline.json")
    instance = ZjcsGuildNotifier()
    instance._ctx = make_context(tmp_path, send_result={"sent": False})
    instance.set_plugin_config(make_config())

    await instance._run_daily_check(today=date(2026, 1, 1))

    assert len(instance.ctx.send.calls) == 1
    assert not (tmp_path / "notification_state.json").exists()


@pytest.mark.asyncio
async def test_lifecycle_stops_and_restarts_daily_task(tmp_path) -> None:
    instance = ZjcsGuildNotifier()
    instance._ctx = make_context(tmp_path)
    instance.set_plugin_config(make_config())
    blocker = asyncio.Event()

    async def idle_loop() -> None:
        await blocker.wait()

    instance._daily_schedule_loop = idle_loop
    await instance.on_load()
    await asyncio.sleep(0)
    first_task = instance._daily_task
    assert first_task is not None

    await instance.on_config_update("self", {}, "1.0.0")
    await asyncio.sleep(0)
    second_task = instance._daily_task
    assert second_task is not None
    assert second_task is not first_task
    assert first_task.cancelled()

    await instance.on_unload()
    assert instance._daily_task is None
    assert second_task.cancelled()


def test_startup_catch_up_runs_today_only() -> None:
    before_check = datetime(2026, 1, 1, 8, 59)
    after_check = datetime(2026, 1, 1, 9, 1)
    delayed_next_day = datetime(2026, 1, 2, 9, 1)

    assert _choose_due_check_date(before_check, time(9, 0), None) is None
    assert _choose_due_check_date(after_check, time(9, 0), None) == date(2026, 1, 1)
    assert _choose_due_check_date(
        delayed_next_day,
        time(9, 0),
        datetime(2026, 1, 1, 9, 0),
    ) == date(2026, 1, 2)
