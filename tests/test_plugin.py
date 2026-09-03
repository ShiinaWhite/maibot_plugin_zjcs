from __future__ import annotations

import asyncio
from datetime import date, datetime, time
import json
import logging
from types import SimpleNamespace

import pytest

import plugin
from plugin import ZjcsGuildNotifier, _choose_due_check_date


class FakeChat:
    def __init__(self, result: object, group_streams: object = None) -> None:
        self.result = result
        self.group_streams_result = [] if group_streams is None else group_streams
        self.calls: list[dict[str, str]] = []
        self.group_stream_calls: list[dict[str, str]] = []

    async def get_group_streams(self, **kwargs: str) -> object:
        self.group_stream_calls.append(kwargs)
        return self.group_streams_result

    async def open_session(self, **kwargs: str) -> object:
        self.calls.append(kwargs)
        return self.result


class FakeSend:
    def __init__(self, result: object) -> None:
        self.results = result if isinstance(result, list) else [result]
        self.result_index = 0
        self.calls: list[tuple[str, str, bool]] = []

    async def text(
        self, message: str, stream_id: str, return_details: bool = False
    ) -> object:
        self.calls.append((message, stream_id, return_details))
        result = self.results[min(self.result_index, len(self.results) - 1)]
        self.result_index += 1
        if isinstance(result, BaseException):
            raise result
        return result


def make_context(
    tmp_path,
    *,
    send_result: object = {"sent": True},
    group_streams: object = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        paths=SimpleNamespace(data_dir=tmp_path),
        chat=FakeChat(
            {"success": True, "stream": {"stream_id": "stream-123"}},
            group_streams=group_streams,
        ),
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


def write_two_reminder_timeline(tmp_path) -> None:
    (tmp_path / "timeline.json").write_text(
        json.dumps(
            {
                "dungeons": [
                    {
                        "id": "first_dungeon",
                        "name": "第一个副本",
                        "server_day": 3,
                        "region": "测试区",
                        "requirements": {"普通": 10_000},
                        "status": "confirmed",
                    },
                    {
                        "id": "second_dungeon",
                        "name": "第二个副本",
                        "server_day": 3,
                        "region": "测试区",
                        "requirements": {"普通": 20_000},
                        "status": "confirmed",
                    },
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
    monkeypatch.setattr(plugin, "SEND_RETRY_DELAYS_SECONDS", (0.0, 0.0, 0.0))
    instance = ZjcsGuildNotifier()
    instance._ctx = make_context(tmp_path, send_result={"sent": False})
    instance.set_plugin_config(make_config())

    await instance._run_daily_check(today=date(2026, 1, 1))

    assert len(instance.ctx.send.calls) == 4
    assert not (tmp_path / "notification_state.json").exists()


@pytest.mark.asyncio
async def test_retry_success_marks_once_and_skips_on_next_check(
    tmp_path, monkeypatch
) -> None:
    write_timeline(tmp_path)
    monkeypatch.setattr(plugin, "TIMELINE_PATH", tmp_path / "timeline.json")
    monkeypatch.setattr(plugin, "SEND_RETRY_DELAYS_SECONDS", (0.0, 0.0, 0.0))
    instance = ZjcsGuildNotifier()
    instance._ctx = make_context(
        tmp_path,
        send_result=[{"sent": False}, {"sent": True}],
    )
    instance.set_plugin_config(make_config())

    await instance._run_daily_check(today=date(2026, 1, 1))
    await instance._run_daily_check(today=date(2026, 1, 1))

    assert len(instance.ctx.send.calls) == 2
    state = json.loads(
        (tmp_path / "notification_state.json").read_text(encoding="utf-8")
    )
    assert state["sent"] == ["test_dungeon:2026-01-03:2"]


@pytest.mark.asyncio
async def test_failed_first_reminder_does_not_block_next_reminder(
    tmp_path, monkeypatch
) -> None:
    write_two_reminder_timeline(tmp_path)
    monkeypatch.setattr(plugin, "TIMELINE_PATH", tmp_path / "timeline.json")
    monkeypatch.setattr(plugin, "SEND_RETRY_DELAYS_SECONDS", (0.0, 0.0, 0.0))
    instance = ZjcsGuildNotifier()
    instance._ctx = make_context(
        tmp_path,
        send_result=[
            {"sent": False},
            {"sent": False},
            {"sent": False},
            {"sent": False},
            {"sent": True},
        ],
    )
    instance.set_plugin_config(make_config())

    await instance._run_daily_check(today=date(2026, 1, 1))

    assert len(instance.ctx.send.calls) == 5
    first_message = instance.ctx.send.calls[0][0]
    second_message = instance.ctx.send.calls[4][0]
    assert [call[0] for call in instance.ctx.send.calls[:4]] == [first_message] * 4
    assert second_message != first_message
    assert [call[1] for call in instance.ctx.send.calls] == ["stream-123"] * 5
    state = json.loads(
        (tmp_path / "notification_state.json").read_text(encoding="utf-8")
    )
    assert state["sent"] == ["second_dungeon:2026-01-03:2"]


@pytest.mark.asyncio
async def test_state_write_failure_stops_remaining_without_resending(
    tmp_path, monkeypatch
) -> None:
    write_two_reminder_timeline(tmp_path)
    monkeypatch.setattr(plugin, "TIMELINE_PATH", tmp_path / "timeline.json")

    def fail_mark_sent(_state, _key: str) -> None:
        raise plugin.StateFileError("state write failed")

    monkeypatch.setattr(plugin.NotificationState, "mark_sent", fail_mark_sent)
    instance = ZjcsGuildNotifier()
    instance._ctx = make_context(tmp_path)
    instance.set_plugin_config(make_config())

    await instance._run_daily_check(today=date(2026, 1, 1))

    assert len(instance.ctx.send.calls) == 1
    assert not (tmp_path / "notification_state.json").exists()


@pytest.mark.asyncio
async def test_missing_open_date_logs_config_error_and_skips_round(
    tmp_path, monkeypatch, caplog
) -> None:
    write_timeline(tmp_path)
    monkeypatch.setattr(plugin, "TIMELINE_PATH", tmp_path / "timeline.json")
    instance = ZjcsGuildNotifier()
    instance._ctx = make_context(tmp_path)
    config = make_config()
    config["server"]["open_date"] = ""
    instance.set_plugin_config(config)

    with caplog.at_level(logging.ERROR, logger=plugin.PLUGIN_ID):
        await instance._run_daily_check(today=date(2026, 1, 1))

    assert "server.open_date" in caplog.text
    assert not instance.ctx.chat.calls
    assert not instance.ctx.send.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("remind_days", [[], [0], [-1], [2, 0]])
async def test_invalid_remind_days_log_config_error_and_skip_round(
    tmp_path, monkeypatch, caplog, remind_days
) -> None:
    write_timeline(tmp_path)
    monkeypatch.setattr(plugin, "TIMELINE_PATH", tmp_path / "timeline.json")
    instance = ZjcsGuildNotifier()
    instance._ctx = make_context(tmp_path)
    config = make_config()
    config["schedule"]["remind_days_before"] = remind_days
    instance.set_plugin_config(config)

    with caplog.at_level(logging.ERROR, logger=plugin.PLUGIN_ID):
        await instance._run_daily_check(today=date(2026, 1, 1))

    assert "remind_days_before" in caplog.text
    assert not instance.ctx.chat.calls
    assert not instance.ctx.send.calls


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


@pytest.mark.asyncio
async def test_unload_cancels_retry_sleep(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(plugin, "SEND_RETRY_DELAYS_SECONDS", (60.0,))
    instance = ZjcsGuildNotifier()
    instance._ctx = make_context(tmp_path, send_result={"sent": False})
    task = asyncio.create_task(
        instance._send_reminder_with_retry("测试通知", "stream-123")
    )
    instance._daily_task = task

    await asyncio.sleep(0)
    await instance.on_unload()

    assert task.cancelled()
    assert len(instance.ctx.send.calls) == 1


@pytest.mark.asyncio
async def test_resolve_group_stream_reuses_single_matching_stream(tmp_path) -> None:
    instance = ZjcsGuildNotifier()
    instance._ctx = make_context(
        tmp_path,
        group_streams=[
            {
                "stream_id": "target-stream",
                "group_id": "123456",
                "account_id": "1194036427",
                "scope": None,
            }
        ],
    )

    assert await instance._resolve_group_stream("123456") == "target-stream"
    assert instance.ctx.chat.calls == []
    assert instance.ctx.chat.group_stream_calls == [{"platform": "qq"}]


@pytest.mark.asyncio
async def test_resolve_group_stream_prefers_route_metadata_priority(tmp_path) -> None:
    instance = ZjcsGuildNotifier()
    instance._ctx = make_context(
        tmp_path,
        group_streams=[
            {
                "stream_id": "empty-route",
                "group_id": "123456",
                "account_id": None,
                "scope": None,
            },
            {
                "stream_id": "account-only",
                "group_id": "123456",
                "account_id": "1194036427",
                "scope": None,
            },
            {
                "stream_id": "scope-only",
                "group_id": "123456",
                "account_id": None,
                "scope": "connection-a",
            },
            {
                "stream_id": "account-and-scope",
                "group_id": "123456",
                "account_id": "1194036427",
                "scope": "connection-a",
            },
        ],
    )

    assert await instance._resolve_group_stream("123456") == "account-and-scope"
    assert instance.ctx.chat.calls == []


@pytest.mark.asyncio
async def test_resolve_group_stream_prefers_account_over_empty_duplicate(
    tmp_path,
) -> None:
    instance = ZjcsGuildNotifier()
    instance._ctx = make_context(
        tmp_path,
        group_streams=[
            {
                "stream_id": "empty-route",
                "group_id": "123456",
                "account_id": None,
                "scope": None,
            },
            {
                "stream_id": "account-route",
                "group_id": "123456",
                "account_id": "1194036427",
                "scope": None,
            },
        ],
    )

    assert await instance._resolve_group_stream("123456") == "account-route"


@pytest.mark.asyncio
async def test_resolve_group_stream_ignores_other_groups_and_falls_back(
    tmp_path,
) -> None:
    instance = ZjcsGuildNotifier()
    instance._ctx = make_context(
        tmp_path,
        group_streams=[
            {
                "stream_id": "other-group",
                "group_id": "654321",
                "account_id": "1194036427",
                "scope": None,
            }
        ],
    )

    assert await instance._resolve_group_stream("123456") == "stream-123"
    assert instance.ctx.chat.calls == [
        {
            "platform": "qq",
            "chat_type": "group",
            "group_id": "123456",
        }
    ]


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
