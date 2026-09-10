from __future__ import annotations

import asyncio
from datetime import date, datetime, time
import json
import logging
import re
from types import SimpleNamespace

from maibot_sdk.config import generate_plugin_config_schema, rebuild_plugin_config_data
from pydantic import ValidationError
import pytest

import plugin
from plugin import ZjcsGuildNotifier, _choose_due_check_date
from state import NotificationState
from timeline import Reminder


class FakeChat:
    def __init__(
        self,
        result: object,
        group_streams: object = None,
        group_stream_results: list[object] | None = None,
    ) -> None:
        self.result = result
        self.group_streams_result = [] if group_streams is None else group_streams
        self.group_stream_results = group_stream_results
        self.group_stream_index = 0
        self.calls: list[dict[str, str]] = []
        self.group_stream_calls: list[dict[str, str]] = []

    async def get_group_streams(self, **kwargs: str) -> object:
        self.group_stream_calls.append(kwargs)
        if self.group_stream_results is None:
            return self.group_streams_result
        result = self.group_stream_results[
            min(self.group_stream_index, len(self.group_stream_results) - 1)
        ]
        self.group_stream_index += 1
        return result

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
    group_stream_results: list[object] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        paths=SimpleNamespace(data_dir=tmp_path),
        chat=FakeChat(
            {"success": True, "stream": {"stream_id": "stream-123"}},
            group_streams=group_streams,
            group_stream_results=group_stream_results,
        ),
        send=FakeSend(send_result),
    )


def make_config() -> dict[str, object]:
    return {
        "plugin": {"enabled": True, "config_version": "1.4.0"},
        "target": {"group_ids": ["123456"]},
        "server": {"open_date": "2026-01-01"},
        "season_dates": {
            "s4_start_date": "",
            "s5_start_date": "",
            "s6_start_date": "",
        },
        "schedule": {
            "daily_check_time": "09:00",
            "timezone": "Asia/Shanghai",
        },
        "reminders": {
            "dungeon_remind_day": 1,
            "secret_treasure_remind_day": 1,
            "bingo_remind_day": 1,
            "scratch_remind_day": 1,
            "fenek_remind_day": 1,
            "event_remind_day": 1,
        },
        "command": {"admin_qqs": []},
    }


def write_v1_config(
    path,
    *,
    s4_start_date: str = "",
    remind_days: tuple[int, ...] = (2, 1),
) -> None:
    anchor = (
        f'season_anchor_dates = {{ S4 = "{s4_start_date}" }}'
        if s4_start_date
        else "season_anchor_dates = {}"
    )
    remind_values = ", ".join(str(value) for value in remind_days)
    path.write_text(
        f"""[plugin]
enabled = true
config_version = "1.0.0"

[target]
group_id = "611817038"

[server]
open_date = "2026-06-19"
{anchor}

[schedule]
daily_check_time = "09:00"
timezone = "Asia/Shanghai"
remind_days_before = [{remind_values}]
""",
        encoding="utf-8",
    )


def write_v1_1_config(path, *, group_id: str = "611817038") -> None:
    path.write_text(
        f"""[plugin]
enabled = true
config_version = "1.1.0"

[target]
group_id = "{group_id}"

[server]
open_date = "2026-06-19"

[season_dates]
s4_start_date = ""
s5_start_date = ""
s6_start_date = ""

[schedule]
daily_check_time = "09:00"
timezone = "Asia/Shanghai"

[reminders]
dungeon_remind_days = [1]
secret_treasure_remind_days = [2, 1]
bingo_remind_days = [4]
scratch_remind_days = [2, 1]
fenek_remind_days = [2, 1]
event_remind_days = [2, 1]
""",
        encoding="utf-8",
    )


def write_three_reminder_timeline(tmp_path) -> None:
    (tmp_path / "timeline.json").write_text(
        json.dumps(
            {
                "dungeons": [
                    {
                        "id": "test_dungeon",
                        "name": "测试副本",
                        "server_day": 2,
                        "region": "测试区",
                        "requirements": {"普通": 10_000},
                        "status": "confirmed",
                    }
                ],
                "events": [
                    {
                        "id": "test_event",
                        "name": "测试事件",
                        "server_day": 2,
                        "status": "confirmed",
                    }
                ],
                "activity_rules": {
                    "weekly_side_activity_rotation": {
                        "first_server_day": 2,
                        "period_days": 7,
                        "rotation": ["宾果抽抽乐"],
                    }
                },
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
                        "id": "test_dungeon",
                        "name": "测试副本",
                        "server_day": 2,
                        "region": "测试区",
                        "requirements": {"普通": 10_000},
                        "status": "confirmed",
                    }
                ],
                "events": [
                    {
                        "id": "test_event",
                        "name": "测试事件",
                        "server_day": 2,
                        "status": "confirmed",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def read_state_groups(tmp_path) -> dict[str, list[str]]:
    payload = json.loads(
        (tmp_path / "notification_state.json").read_text(encoding="utf-8")
    )
    assert payload["version"] == 2
    return payload["groups"]


THREE_REMINDER_KEYS = [
    "test_dungeon:2026-01-02:1",
    "test_event:2026-01-02:1",
    "weekly_side_activity_2:2026-01-02:1",
]


@pytest.mark.asyncio
async def test_daily_check_merges_three_categories_and_marks_all_keys(
    tmp_path, monkeypatch, caplog
) -> None:
    write_three_reminder_timeline(tmp_path)
    monkeypatch.setattr(plugin, "TIMELINE_PATH", tmp_path / "timeline.json")
    instance = ZjcsGuildNotifier()
    instance._ctx = make_context(tmp_path)
    instance.set_plugin_config(make_config())

    with caplog.at_level(logging.INFO, logger=plugin.PLUGIN_ID):
        await instance._run_daily_check(today=date(2026, 1, 1))

    assert len(instance.ctx.send.calls) == 1
    message, stream_id, return_details = instance.ctx.send.calls[0]
    assert stream_id == "stream-123"
    assert return_details is True
    assert message.count("【杖剑传说 · 近期提醒】") == 1
    assert "每日提醒" not in message
    assert "【副本】测试区 · 测试副本" in message
    assert "【活动】宾果抽抽乐" in message
    assert "【事件】测试事件" in message
    assert "准备建议：今天开始攒副本次数。" in message
    assert "准备建议：现在开始攒果子，活动开始前至少留20个。" in message
    assert read_state_groups(tmp_path) == {"123456": sorted(THREE_REMINDER_KEYS)}
    assert "reminders=3" in caplog.text
    assert "pending=3" in caplog.text
    assert "merged_groups=1" in caplog.text
    assert "notification_keys=3" in caplog.text


@pytest.mark.asyncio
async def test_failed_merged_send_marks_no_keys(tmp_path, monkeypatch) -> None:
    write_three_reminder_timeline(tmp_path)
    monkeypatch.setattr(plugin, "TIMELINE_PATH", tmp_path / "timeline.json")
    monkeypatch.setattr(plugin, "SEND_RETRY_DELAYS_SECONDS", (0.0, 0.0, 0.0))
    instance = ZjcsGuildNotifier()
    instance._ctx = make_context(tmp_path, send_result={"sent": False})
    instance.set_plugin_config(make_config())

    await instance._run_daily_check(today=date(2026, 1, 1))

    assert len(instance.ctx.send.calls) == 4
    assert len({call[0] for call in instance.ctx.send.calls}) == 1
    assert not (tmp_path / "notification_state.json").exists()


@pytest.mark.asyncio
async def test_merged_retry_success_stops_and_deduplicates_next_check(
    tmp_path, monkeypatch
) -> None:
    write_three_reminder_timeline(tmp_path)
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
    assert instance.ctx.send.calls[0][0] == instance.ctx.send.calls[1][0]
    assert len(read_state_groups(tmp_path)["123456"]) == 3


@pytest.mark.asyncio
async def test_partial_dedupe_merges_only_pending_items(tmp_path, monkeypatch) -> None:
    write_three_reminder_timeline(tmp_path)
    monkeypatch.setattr(plugin, "TIMELINE_PATH", tmp_path / "timeline.json")
    NotificationState(tmp_path / "notification_state.json").load().mark_sent(
        "123456", "test_dungeon:2026-01-02:1"
    )
    instance = ZjcsGuildNotifier()
    instance._ctx = make_context(tmp_path)
    instance.set_plugin_config(make_config())

    await instance._run_daily_check(today=date(2026, 1, 1))

    assert len(instance.ctx.send.calls) == 1
    message = instance.ctx.send.calls[0][0]
    assert "测试副本" not in message
    assert "宾果抽抽乐" in message
    assert "测试事件" in message
    assert len(read_state_groups(tmp_path)["123456"]) == 3


@pytest.mark.asyncio
async def test_multi_group_send_records_success_per_group(
    tmp_path, monkeypatch
) -> None:
    write_three_reminder_timeline(tmp_path)
    monkeypatch.setattr(plugin, "TIMELINE_PATH", tmp_path / "timeline.json")
    monkeypatch.setattr(plugin, "SEND_RETRY_DELAYS_SECONDS", (0.0, 0.0, 0.0))
    instance = ZjcsGuildNotifier()
    # A 成功；B 四次尝试全部失败；C 成功。
    instance._ctx = make_context(
        tmp_path,
        send_result=[
            {"sent": True},
            {"sent": False},
            {"sent": False},
            {"sent": False},
            {"sent": False},
            {"sent": True},
        ],
    )
    config = make_config()
    config["target"]["group_ids"] = ["111000111", "222000222", "333000333"]
    instance.set_plugin_config(config)

    await instance._run_daily_check(today=date(2026, 1, 1))

    assert len(instance.ctx.send.calls) == 6
    assert len({call[0] for call in instance.ctx.send.calls}) == 1
    assert [call["group_id"] for call in instance.ctx.chat.calls] == [
        "111000111",
        "222000222",
        "222000222",
        "222000222",
        "222000222",
        "333000333",
    ]
    groups = read_state_groups(tmp_path)
    assert groups["111000111"] == sorted(THREE_REMINDER_KEYS)
    assert groups["333000333"] == sorted(THREE_REMINDER_KEYS)
    assert "222000222" not in groups


@pytest.mark.asyncio
async def test_multi_group_retry_round_skips_notified_groups(
    tmp_path, monkeypatch
) -> None:
    write_three_reminder_timeline(tmp_path)
    monkeypatch.setattr(plugin, "TIMELINE_PATH", tmp_path / "timeline.json")
    monkeypatch.setattr(plugin, "SEND_RETRY_DELAYS_SECONDS", (0.0, 0.0, 0.0))
    instance = ZjcsGuildNotifier()
    instance._ctx = make_context(
        tmp_path,
        send_result=[
            {"sent": True},
            {"sent": False},
            {"sent": False},
            {"sent": False},
            {"sent": False},
            {"sent": True},
        ],
    )
    config = make_config()
    config["target"]["group_ids"] = ["111000111", "222000222", "333000333"]
    instance.set_plugin_config(config)
    await instance._run_daily_check(today=date(2026, 1, 1))

    # 第二轮：A、C 已拥有全部键被跳过，仅 B 重试。
    instance._ctx = make_context(tmp_path, send_result=[{"sent": True}])
    await instance._run_daily_check(today=date(2026, 1, 1))

    assert len(instance.ctx.send.calls) == 1
    assert instance.ctx.chat.calls[0]["group_id"] == "222000222"
    groups = read_state_groups(tmp_path)
    assert groups["111000111"] == sorted(THREE_REMINDER_KEYS)
    assert groups["222000222"] == sorted(THREE_REMINDER_KEYS)
    assert groups["333000333"] == sorted(THREE_REMINDER_KEYS)


@pytest.mark.asyncio
async def test_previously_notified_group_is_skipped_per_group(
    tmp_path, monkeypatch
) -> None:
    write_three_reminder_timeline(tmp_path)
    monkeypatch.setattr(plugin, "TIMELINE_PATH", tmp_path / "timeline.json")
    NotificationState(tmp_path / "notification_state.json").load().mark_sent_many(
        "111000111", THREE_REMINDER_KEYS
    )
    instance = ZjcsGuildNotifier()
    instance._ctx = make_context(tmp_path)
    config = make_config()
    config["target"]["group_ids"] = ["111000111", "222000222"]
    instance.set_plugin_config(config)

    await instance._run_daily_check(today=date(2026, 1, 1))

    assert len(instance.ctx.send.calls) == 1
    assert instance.ctx.chat.calls[0]["group_id"] == "222000222"
    groups = read_state_groups(tmp_path)
    assert groups["111000111"] == sorted(THREE_REMINDER_KEYS)
    assert groups["222000222"] == sorted(THREE_REMINDER_KEYS)


@pytest.mark.asyncio
async def test_multi_group_partial_overlap_gets_group_specific_messages(
    tmp_path, monkeypatch
) -> None:
    write_two_reminder_timeline(tmp_path)
    monkeypatch.setattr(plugin, "TIMELINE_PATH", tmp_path / "timeline.json")
    instance = ZjcsGuildNotifier()
    instance._ctx = make_context(tmp_path, send_result=[{"sent": True}, {"sent": True}])
    config = make_config()
    config["target"]["group_ids"] = ["111000111", "222000222"]
    instance.set_plugin_config(config)
    NotificationState(tmp_path / "notification_state.json").load().mark_sent(
        "111000111", "test_dungeon:2026-01-02:1"
    )
    NotificationState(tmp_path / "notification_state.json").load().mark_sent(
        "222000222", "test_event:2026-01-02:1"
    )

    await instance._run_daily_check(today=date(2026, 1, 1))

    # 每群恰好一次成功发送，且按 chat 解析顺序对应 A、B。
    assert len(instance.ctx.send.calls) == 2
    assert [call["group_id"] for call in instance.ctx.chat.calls] == [
        "111000111",
        "222000222",
    ]
    message_a = instance.ctx.send.calls[0][0]
    message_b = instance.ctx.send.calls[1][0]
    # A 只缺 R2（测试事件），正文不得再包含 A 已收到的 R1（测试副本）。
    assert "测试事件" in message_a
    assert "测试副本" not in message_a
    # B 只缺 R1（测试副本），正文不得再包含 B 已收到的 R2（测试事件）。
    assert "测试副本" in message_b
    assert "测试事件" not in message_b
    assert message_a.count("【杖剑传说 · 近期提醒】") == 1
    assert message_b.count("【杖剑传说 · 近期提醒】") == 1
    # A 只缺事件提醒，正文不得出现任何准备建议；B 的副本块带攒次数建议。
    assert "准备建议" not in message_a
    assert "准备建议：今天开始攒副本次数。" in message_b
    both_keys = sorted(["test_dungeon:2026-01-02:1", "test_event:2026-01-02:1"])
    groups = read_state_groups(tmp_path)
    assert groups["111000111"] == both_keys
    assert groups["222000222"] == both_keys


@pytest.mark.asyncio
async def test_multi_group_state_write_failure_keeps_other_groups(
    tmp_path, monkeypatch
) -> None:
    write_three_reminder_timeline(tmp_path)
    monkeypatch.setattr(plugin, "TIMELINE_PATH", tmp_path / "timeline.json")
    original_mark_sent_many = plugin.NotificationState.mark_sent_many
    failed_groups: list[str] = []

    def flaky_mark_sent_many(self, group_id: str, keys: list[str]) -> None:
        if group_id == "222000222":
            failed_groups.append(group_id)
            raise plugin.StateFileError("state write failed")
        original_mark_sent_many(self, group_id, keys)

    monkeypatch.setattr(
        plugin.NotificationState, "mark_sent_many", flaky_mark_sent_many
    )
    instance = ZjcsGuildNotifier()
    instance._ctx = make_context(tmp_path)
    config = make_config()
    config["target"]["group_ids"] = ["111000111", "222000222", "333000333"]
    instance.set_plugin_config(config)

    await instance._run_daily_check(today=date(2026, 1, 1))

    assert len(instance.ctx.send.calls) == 3
    groups = read_state_groups(tmp_path)
    assert groups["111000111"] == sorted(THREE_REMINDER_KEYS)
    assert groups["333000333"] == sorted(THREE_REMINDER_KEYS)
    assert "222000222" not in groups


@pytest.mark.asyncio
async def test_state_batch_write_failure_does_not_repeat_send(
    tmp_path, monkeypatch
) -> None:
    write_three_reminder_timeline(tmp_path)
    monkeypatch.setattr(plugin, "TIMELINE_PATH", tmp_path / "timeline.json")

    def fail_mark_sent_many(_state, _group_id: str, _keys: list[str]) -> None:
        raise plugin.StateFileError("state write failed")

    monkeypatch.setattr(plugin.NotificationState, "mark_sent_many", fail_mark_sent_many)
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
    write_three_reminder_timeline(tmp_path)
    monkeypatch.setattr(plugin, "TIMELINE_PATH", tmp_path / "timeline.json")
    instance = ZjcsGuildNotifier()
    instance._ctx = make_context(tmp_path)
    config = make_config()
    config["server"]["open_date"] = ""
    instance.set_plugin_config(config)

    with caplog.at_level(logging.ERROR, logger=plugin.PLUGIN_ID):
        await instance._run_daily_check(today=date(2026, 1, 1))

    assert "开服日期" in caplog.text
    assert not instance.ctx.chat.calls
    assert not instance.ctx.send.calls


@pytest.mark.asyncio
async def test_negative_policy_fails_config_injection_and_daily_check_skips(
    tmp_path, monkeypatch, caplog
) -> None:
    write_three_reminder_timeline(tmp_path)
    monkeypatch.setattr(plugin, "TIMELINE_PATH", tmp_path / "timeline.json")
    instance = ZjcsGuildNotifier()
    instance._ctx = make_context(tmp_path)
    config = make_config()
    config["reminders"]["dungeon_remind_day"] = -1

    with pytest.raises(ValidationError):
        instance.set_plugin_config(config)
    with pytest.raises(RuntimeError):
        _ = instance.config

    with caplog.at_level(logging.ERROR, logger=plugin.PLUGIN_ID):
        await instance._run_daily_check(today=date(2026, 1, 1))

    assert "每日时间线检查失败" in caplog.text
    assert not instance.ctx.chat.calls
    assert not instance.ctx.send.calls


@pytest.mark.asyncio
async def test_daily_check_fails_closed_on_unmigrated_v1_state(
    tmp_path, monkeypatch, caplog
) -> None:
    write_three_reminder_timeline(tmp_path)
    monkeypatch.setattr(plugin, "TIMELINE_PATH", tmp_path / "timeline.json")
    (tmp_path / "notification_state.json").write_text(
        json.dumps({"version": 1, "sent": ["k1"]}), encoding="utf-8"
    )
    instance = ZjcsGuildNotifier()
    instance._ctx = make_context(tmp_path)
    instance.set_plugin_config(make_config())

    with caplog.at_level(logging.ERROR, logger=plugin.PLUGIN_ID):
        await instance._run_daily_check(today=date(2026, 1, 1))

    assert "V1" in caplog.text
    assert not instance.ctx.chat.calls
    assert not instance.ctx.send.calls
    assert (
        json.loads((tmp_path / "notification_state.json").read_text(encoding="utf-8"))[
            "version"
        ]
        == 1
    )


@pytest.mark.asyncio
async def test_on_load_migrates_v1_state_to_legacy_target_group(
    tmp_path, monkeypatch
) -> None:
    state_path = tmp_path / "notification_state.json"
    state_path.write_text(
        json.dumps({"version": 1, "sent": ["k2", "k1"]}), encoding="utf-8"
    )
    monkeypatch.setattr(plugin, "CONFIG_PATH", tmp_path / "missing-config.toml")
    instance = ZjcsGuildNotifier()
    instance._ctx = make_context(tmp_path)
    config = make_config()
    config["plugin"]["enabled"] = False
    config["plugin"]["config_version"] = "1.1.0"
    config["target"] = {"group_id": "611817038"}
    config["reminders"] = {
        "dungeon_remind_days": [1],
        "secret_treasure_remind_days": [2, 1],
        "bingo_remind_days": [4],
        "scratch_remind_days": [2, 1],
        "fenek_remind_days": [2, 1],
        "event_remind_days": [2, 1],
    }
    instance.set_plugin_config(config)

    await instance.on_load()

    assert read_state_groups(tmp_path) == {"611817038": ["k1", "k2"]}


@pytest.mark.asyncio
async def test_on_load_keeps_v2_state_untouched(tmp_path) -> None:
    state_path = tmp_path / "notification_state.json"
    NotificationState(state_path).load().mark_sent("111", "k1")
    instance = ZjcsGuildNotifier()
    instance._ctx = make_context(tmp_path)
    config = make_config()
    config["plugin"]["enabled"] = False
    instance.set_plugin_config(config)

    await instance.on_load()

    assert read_state_groups(tmp_path) == {"111": ["k1"]}


@pytest.mark.asyncio
async def test_on_load_recovers_v1_state_with_sole_configured_group(
    tmp_path, monkeypatch
) -> None:
    state_path = tmp_path / "notification_state.json"
    state_path.write_text(
        json.dumps({"version": 1, "sent": ["k1", "k2"]}), encoding="utf-8"
    )
    monkeypatch.setattr(plugin, "CONFIG_PATH", tmp_path / "missing-config.toml")
    instance = ZjcsGuildNotifier()
    instance._ctx = make_context(tmp_path)
    config = make_config()
    config["plugin"]["enabled"] = False
    config["target"] = {"group_ids": ["611817038"]}
    instance.set_plugin_config(config)
    assert instance._legacy_state_group_id is None

    await instance.on_load()

    assert read_state_groups(tmp_path) == {"611817038": ["k1", "k2"]}


@pytest.mark.asyncio
async def test_on_load_refuses_v1_state_with_multiple_configured_groups(
    tmp_path, monkeypatch, caplog
) -> None:
    state_path = tmp_path / "notification_state.json"
    state_path.write_text(json.dumps({"version": 1, "sent": ["k1"]}), encoding="utf-8")
    monkeypatch.setattr(plugin, "CONFIG_PATH", tmp_path / "missing-config.toml")
    instance = ZjcsGuildNotifier()
    instance._ctx = make_context(tmp_path)
    config = make_config()
    config["plugin"]["enabled"] = False
    config["target"] = {"group_ids": ["111000111", "222000222"]}
    instance.set_plugin_config(config)
    assert instance._legacy_state_group_id is None

    with caplog.at_level(logging.ERROR, logger=plugin.PLUGIN_ID):
        await instance.on_load()

    assert "通知状态迁移失败" in caplog.text
    assert json.loads(state_path.read_text(encoding="utf-8")) == {
        "version": 1,
        "sent": ["k1"],
    }


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

    await instance.on_config_update("self", {}, "1.2.0")
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
    task = asyncio.create_task(instance._send_text_with_retry("测试通知", "123456"))
    instance._daily_task = task

    await asyncio.sleep(0)
    await instance.on_unload()

    assert task.cancelled()
    assert len(instance.ctx.send.calls) == 1


@pytest.mark.asyncio
async def test_retry_reresolves_and_uses_new_stream(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(plugin, "SEND_RETRY_DELAYS_SECONDS", (0.0,))
    instance = ZjcsGuildNotifier()
    instance._ctx = make_context(
        tmp_path,
        send_result=[{"sent": False}, {"sent": True}],
        group_stream_results=[
            [],
            [
                {
                    "stream_id": "routed-stream",
                    "group_id": "123456",
                    "account_id": "1194036427",
                    "scope": None,
                }
            ],
        ],
    )

    assert await instance._send_text_with_retry("测试通知", "123456") is True
    assert [call[1] for call in instance.ctx.send.calls] == [
        "stream-123",
        "routed-stream",
    ]
    assert instance.ctx.chat.group_stream_calls == [
        {"platform": "qq"},
        {"platform": "qq"},
    ]
    assert len(instance.ctx.chat.calls) == 1


@pytest.mark.asyncio
async def test_retry_recovers_after_stream_resolution_error(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(plugin, "SEND_RETRY_DELAYS_SECONDS", (0.0,))
    instance = ZjcsGuildNotifier()
    instance._ctx = make_context(tmp_path)
    original_get_group_streams = instance.ctx.chat.get_group_streams
    calls = 0

    async def flaky_get_group_streams(**kwargs: str) -> object:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("temporary stream lookup failure")
        return await original_get_group_streams(**kwargs)

    instance.ctx.chat.get_group_streams = flaky_get_group_streams

    assert await instance._send_text_with_retry("测试通知", "123456") is True
    assert calls == 2
    assert len(instance.ctx.send.calls) == 1
    assert len(instance.ctx.chat.calls) == 1


@pytest.mark.asyncio
async def test_resolve_group_stream_prefers_route_metadata(tmp_path) -> None:
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
                "stream_id": "account-and-scope",
                "group_id": "123456",
                "account_id": "1194036427",
                "scope": "connection-a",
            },
        ],
    )

    target = await instance._resolve_group_stream("123456")

    assert target.stream_id == "account-and-scope"
    assert target.has_account_id is True
    assert target.has_scope is True
    assert instance.ctx.chat.calls == []


@pytest.mark.asyncio
async def test_resolve_group_stream_falls_back_for_other_groups(tmp_path) -> None:
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

    target = await instance._resolve_group_stream("123456")

    assert target.stream_id == "stream-123"
    assert target.has_account_id is False
    assert target.has_scope is False
    assert instance.ctx.chat.calls == [
        {
            "platform": "qq",
            "chat_type": "group",
            "group_id": "123456",
        }
    ]


@pytest.mark.asyncio
async def test_preview_is_marked_and_does_not_send_formal_or_write_state(
    tmp_path, monkeypatch
) -> None:
    event_reminder = Reminder(
        event_id="preview_event",
        category="event",
        name="预览事件",
        event_date=date(2026, 1, 2),
        remind_days_before=1,
        date_label="开放日期",
        payload={},
        current_server_day=1,
    )
    dungeon_reminder = Reminder(
        event_id="preview_dungeon",
        category="dungeon",
        name="预览副本",
        event_date=date(2026, 1, 2),
        remind_days_before=1,
        date_label="开放日期",
        payload={"region": "预览区", "requirements": {"普通": 10_000}},
        current_server_day=1,
    )

    class _FixedDatetime:
        @staticmethod
        def now(tz=None):
            return datetime(2026, 1, 1, 9, 0, tzinfo=tz)

    instance = ZjcsGuildNotifier()
    instance._ctx = make_context(tmp_path)
    instance.set_plugin_config(make_config())
    monkeypatch.setattr(plugin, "datetime", _FixedDatetime)
    monkeypatch.setattr(
        instance,
        "_build_configured_reminders",
        lambda *, today: ([event_reminder, dungeon_reminder], 1),
    )

    result = await instance.handle_zjcs_command(
        stream_id="operator-stream",
        matched_groups={"sub": "预览"},
    )

    assert result == (True, "今日提醒预览已生成", True)
    assert len(instance.ctx.send.calls) == 1
    message, stream_id, _ = instance.ctx.send.calls[0]
    assert stream_id == "operator-stream"
    assert "【杖剑助手 · 今日提醒预览】" in message
    assert "仅供预览" in message
    assert "预览事件" in message
    assert "准备建议：今天开始攒副本次数。" in message
    assert not (tmp_path / "notification_state.json").exists()
    assert instance.ctx.chat.group_stream_calls == []


@pytest.mark.asyncio
async def test_preview_reports_unconfirmed_send_as_failure(
    tmp_path, monkeypatch
) -> None:
    instance = ZjcsGuildNotifier()
    instance._ctx = make_context(tmp_path, send_result={"sent": False})
    instance.set_plugin_config(make_config())
    monkeypatch.setattr(
        instance,
        "_build_configured_reminders",
        lambda *, today: ([], 1),
    )

    result = await instance.handle_zjcs_command(
        stream_id="operator-stream",
        matched_groups={"sub": "预览"},
    )

    assert result == (False, "今日提醒预览发送失败", True)
    assert not (tmp_path / "notification_state.json").exists()


@pytest.mark.asyncio
async def test_test_command_sends_only_to_source_stream(tmp_path) -> None:
    instance = ZjcsGuildNotifier()
    instance._ctx = make_context(tmp_path)
    instance.set_plugin_config(make_config())

    result = await instance.handle_zjcs_command(
        stream_id="stream-123",
        group_id="123456",
        platform="qq",
        matched_groups={"sub": "测试"},
    )

    assert result == (True, "测试消息已发送", True)
    # 成功时不再追加第二条状态消息，TEST_MESSAGE 本身即证明链路正常。
    assert len(instance.ctx.send.calls) == 1
    message, stream_id, return_details = instance.ctx.send.calls[0]
    assert message == plugin.TEST_MESSAGE
    assert stream_id == "stream-123"
    assert return_details is True
    assert not (tmp_path / "notification_state.json").exists()


@pytest.mark.asyncio
async def test_multi_group_config_test_command_only_hits_source_group(
    tmp_path,
) -> None:
    instance = ZjcsGuildNotifier()
    instance._ctx = make_context(tmp_path)
    config = make_config()
    config["target"]["group_ids"] = ["111000111", "222000222", "333000333"]
    instance.set_plugin_config(config)

    result = await instance.handle_zjcs_command(
        stream_id="stream-B",
        group_id="222000222",
        platform="qq",
        matched_groups={"sub": "测试"},
    )

    assert result == (True, "测试消息已发送", True)
    # 指令严格锁定来源聊天：仅 stream-B 收到一次 TEST_MESSAGE，
    # 不解析、不联系 target.group_ids 中的其他群，也不写通知状态。
    assert len(instance.ctx.send.calls) == 1
    message, stream_id, _ = instance.ctx.send.calls[0]
    assert message == plugin.TEST_MESSAGE
    assert stream_id == "stream-B"
    assert instance.ctx.chat.calls == []
    assert instance.ctx.chat.group_stream_calls == []
    assert not (tmp_path / "notification_state.json").exists()


@pytest.mark.asyncio
async def test_test_command_works_outside_configured_targets(tmp_path) -> None:
    instance = ZjcsGuildNotifier()
    instance._ctx = make_context(tmp_path)
    config = make_config()
    config["target"]["group_ids"] = ["111000111"]
    instance.set_plugin_config(config)

    result = await instance.handle_zjcs_command(
        stream_id="stream-D",
        group_id="444000444",
        platform="qq",
        matched_groups={"sub": "测试"},
    )

    assert result == (True, "测试消息已发送", True)
    assert [
        (message, stream_id) for message, stream_id, _ in instance.ctx.send.calls
    ] == [(plugin.TEST_MESSAGE, "stream-D")]
    assert instance.ctx.chat.calls == []
    assert not (tmp_path / "notification_state.json").exists()


@pytest.mark.asyncio
async def test_test_command_requires_qq_group_context(tmp_path) -> None:
    for group_id, platform in (("", "qq"), ("222000222", "other")):
        instance = ZjcsGuildNotifier()
        instance._ctx = make_context(tmp_path)
        instance.set_plugin_config(make_config())

        result = await instance.handle_zjcs_command(
            stream_id="stream-ctx",
            group_id=group_id,
            platform=platform,
            matched_groups={"sub": "测试"},
        )

        assert result == (True, "已提示测试指令使用范围", True)
        assert [
            (message, stream_id) for message, stream_id, _ in instance.ctx.send.calls
        ] == [(plugin.TEST_GROUP_ONLY_MESSAGE, "stream-ctx")]
        assert not (tmp_path / "notification_state.json").exists()


def test_config_schema_is_chinese_and_multi_group_ready() -> None:
    schema = generate_plugin_config_schema(plugin.ZjcsGuildNotifierConfig)
    sections = schema["sections"]

    assert [section["title"] for section in sections.values()] == [
        "基础设置",
        "通知目标",
        "服务器进度",
        "S4+ 赛季日期",
        "每日调度",
        "提醒时间",
        "指令设置",
    ]
    expected_labels = {
        "plugin": {"enabled": "启用杖剑助手", "config_version": "配置版本"},
        "target": {"group_ids": "目标 QQ 群号"},
        "server": {"open_date": "开服日期"},
        "season_dates": {
            "s4_start_date": "S4 赛季开始日期",
            "s5_start_date": "S5 赛季开始日期",
            "s6_start_date": "S6 赛季开始日期",
        },
        "schedule": {"daily_check_time": "每日检查时间", "timezone": "时区"},
        "reminders": {
            "dungeon_remind_day": "副本提前提醒天数",
            "secret_treasure_remind_day": "秘宝大作战提前提醒天数",
            "bingo_remind_day": "宾果抽抽乐提前提醒天数",
            "scratch_remind_day": "幸运刮刮乐提前提醒天数",
            "fenek_remind_day": "菲涅克的谜题提前提醒天数",
            "event_remind_day": "遗物池及重要事件提前提醒天数",
        },
        "command": {"admin_qqs": "管理员 QQ 号列表"},
    }
    for section_name, labels in expected_labels.items():
        for field_name, label in labels.items():
            field = sections[section_name]["fields"][field_name]
            assert field["label"] == label
            assert field["description"]

    assert "season_anchor_dates" not in sections["server"]["fields"]
    assert all(
        field["type"] == "string"
        for field in sections["season_dates"]["fields"].values()
    )


def test_config_schema_declares_multi_group_input_for_target() -> None:
    schema = generate_plugin_config_schema(plugin.ZjcsGuildNotifierConfig)
    field = schema["sections"]["target"]["fields"]["group_ids"]

    assert field["type"] == "array"
    assert field["item_type"] == "string"
    assert field["default"] == []
    assert "所有 QQ 群" in field["description"]
    assert "多个群" in field["description"]


def test_config_schema_uses_date_placeholder_and_hides_timezone() -> None:
    schema = generate_plugin_config_schema(plugin.ZjcsGuildNotifierConfig)
    fields = schema["sections"]

    open_date_field = fields["server"]["fields"]["open_date"]
    assert open_date_field["placeholder"] == "YYYY-MM-DD"

    timezone_field = fields["schedule"]["fields"]["timezone"]
    assert timezone_field["hidden"] is True
    assert timezone_field["default"] == "Asia/Shanghai"
    assert fields["schedule"]["fields"]["daily_check_time"]["hidden"] is False


def test_config_schema_reminders_are_single_integers_with_zero_hint() -> None:
    schema = generate_plugin_config_schema(plugin.ZjcsGuildNotifierConfig)
    reminder_fields = schema["sections"]["reminders"]["fields"]

    assert list(reminder_fields) == [
        "dungeon_remind_day",
        "secret_treasure_remind_day",
        "bingo_remind_day",
        "scratch_remind_day",
        "fenek_remind_day",
        "event_remind_day",
    ]
    for field in reminder_fields.values():
        assert field["type"] == "integer"
        assert field["type"] != "array"
        assert field["min"] == 0
        assert "填写 0 可关闭此类提醒" in field["description"]


def test_config_defaults_match_v1_4_production_policy() -> None:
    config = plugin.ZjcsGuildNotifierConfig()

    assert config.plugin.config_version == "1.4.0"
    assert config.target.group_ids == []
    assert config.reminders.dungeon_remind_day == 1
    assert config.reminders.secret_treasure_remind_day == 2
    assert config.reminders.bingo_remind_day == 4
    assert config.reminders.scratch_remind_day == 2
    assert config.reminders.fenek_remind_day == 2
    assert config.reminders.event_remind_day == 2
    assert config.season_dates.s4_start_date == ""
    assert config.season_dates.s5_start_date == ""
    assert config.season_dates.s6_start_date == ""
    assert config.command.admin_qqs == []


def test_config_schema_declares_command_admin_field() -> None:
    schema = generate_plugin_config_schema(plugin.ZjcsGuildNotifierConfig)
    field = schema["sections"]["command"]["fields"]["admin_qqs"]

    assert field["label"] == "管理员 QQ 号列表"
    assert field["type"] == "array"
    assert field["item_type"] == "string"
    assert field["default"] == []
    assert field["placeholder"] == "123456789"
    assert "留空列表则所有人都可以使用" in field["description"]
    assert "仅列表中的 QQ 账号" in field["description"]


def test_public_default_config_contains_only_v1_4_fields() -> None:
    default_config = ZjcsGuildNotifier().get_default_config()

    assert default_config["target"] == {"group_ids": []}
    assert default_config["command"] == {"admin_qqs": []}
    assert "remind_days_before" not in default_config["schedule"]


def test_v1_2_0_config_migrates_to_v1_4_0_idempotently() -> None:
    v1_2_config = make_config()
    v1_2_config["plugin"]["config_version"] = "1.2.0"
    v1_2_config.pop("command")
    instance = ZjcsGuildNotifier()

    rebuilt, changed = instance.normalize_plugin_config(v1_2_config)

    assert changed is True
    assert rebuilt["plugin"]["config_version"] == "1.4.0"
    assert rebuilt["command"] == {"admin_qqs": []}
    # 原有配置全部保留。
    assert rebuilt["target"] == {"group_ids": ["123456"]}
    assert rebuilt["server"] == {"open_date": "2026-01-01"}
    assert rebuilt["schedule"]["daily_check_time"] == "09:00"
    assert rebuilt["reminders"]["dungeon_remind_day"] == 1
    assert rebuilt["season_dates"] == {
        "s4_start_date": "",
        "s5_start_date": "",
        "s6_start_date": "",
    }

    again, changed_again = instance.normalize_plugin_config(rebuilt)

    assert changed_again is False
    assert again == rebuilt


def test_v1_3_0_single_admin_migrates_to_admin_qqs_list() -> None:
    for legacy_admin, expected_admin_qqs in (("100", ["100"]), ("", [])):
        v1_3_config = make_config()
        v1_3_config["plugin"]["config_version"] = "1.3.0"
        v1_3_config["command"] = {"admin_qq": legacy_admin}
        instance = ZjcsGuildNotifier()

        rebuilt, changed = instance.normalize_plugin_config(v1_3_config)

        assert changed is True
        assert rebuilt["plugin"]["config_version"] == "1.4.0"
        assert rebuilt["command"] == {"admin_qqs": expected_admin_qqs}
        assert "admin_qq" not in rebuilt["command"]
        assert rebuilt["target"] == {"group_ids": ["123456"]}

        again, changed_again = instance.normalize_plugin_config(rebuilt)

        assert changed_again is False
        assert again == rebuilt


def test_command_registration_replaces_legacy_operator_commands() -> None:
    components = {
        component["name"]: component
        for component in ZjcsGuildNotifier().get_components()
    }

    # 旧开发阶段指令不再注册为正式 Command。
    assert "preview" not in components
    assert "test_send" not in components
    assert set(components) == {"zjcs_command"}
    metadata = components["zjcs_command"]["metadata"]
    assert metadata["command_pattern"] == plugin.COMMAND_PATTERN
    # 不带 Host operator gate，普通用户可进入插件内统一授权。
    assert "permission" not in metadata


def test_command_pattern_matches_both_roots_and_captures_subcommand() -> None:
    matched = re.search(plugin.COMMAND_PATTERN, "/杖剑传说 预览")
    assert matched is not None
    assert matched.groupdict() == {"sub": "预览"}

    matched = re.search(plugin.COMMAND_PATTERN, "/zjcs 测试")
    assert matched is not None
    assert matched.groupdict() == {"sub": "测试"}

    matched = re.search(plugin.COMMAND_PATTERN, "/zjcs 帮助")
    assert matched is not None
    assert matched.groupdict() == {"sub": "帮助"}

    matched = re.search(plugin.COMMAND_PATTERN, "/杖剑传说")
    assert matched is not None
    assert matched.groupdict() == {"sub": None}

    assert re.search(plugin.COMMAND_PATTERN, "/zjcs_preview") is None
    assert re.search(plugin.COMMAND_PATTERN, "/zjcs_test") is None


def test_is_command_allowed_follows_admin_qqs_config() -> None:
    instance = ZjcsGuildNotifier()

    # 未注入配置时按失败关闭处理。
    assert instance._is_command_allowed("123456789") is False

    instance.set_plugin_config(make_config())
    # 管理员列表为空：所有人可用。
    assert instance._is_command_allowed("任何用户") is True
    assert instance._is_command_allowed("") is True
    assert instance._is_command_allowed(None) is True

    config = make_config()
    config["command"]["admin_qqs"] = [" 100 ", "", "200", "100", " 300"]
    instance.set_plugin_config(config)
    # trim、去重、空项清理在授权比较时统一处理。
    assert instance._is_command_allowed("100") is True
    assert instance._is_command_allowed(" 100 ") is True
    assert instance._is_command_allowed("200") is True
    assert instance._is_command_allowed("300") is True
    assert instance._is_command_allowed("400") is False
    assert instance._is_command_allowed("") is False
    assert instance._is_command_allowed(None) is False


@pytest.mark.asyncio
async def test_command_denies_all_subcommands_for_non_admin_without_leaking_qq(
    tmp_path,
) -> None:
    instance = ZjcsGuildNotifier()
    instance._ctx = make_context(tmp_path)
    config = make_config()
    config["command"]["admin_qqs"] = ["10000"]
    instance.set_plugin_config(config)

    for matched_groups in (None, {}, {"sub": "帮助"}, {"sub": "预览"}, {"sub": "测试"}):
        result = await instance.handle_zjcs_command(
            stream_id="operator-stream",
            user_id="99999",
            group_id="222000222",
            platform="qq",
            matched_groups=matched_groups,
        )
        # return 元组的 success 反映拒绝提示本身的发送结果；关键约束是拦截。
        assert result[2] is True

    # 未授权提示主动发送，且只发到来源 stream；不触发任何其他发送或状态写入。
    assert len(instance.ctx.send.calls) == 5
    assert all(
        message == plugin.COMMAND_DENIED_MESSAGE and stream_id == "operator-stream"
        for message, stream_id, _ in instance.ctx.send.calls
    )
    assert "10000" not in plugin.COMMAND_DENIED_MESSAGE
    assert instance.ctx.chat.calls == []
    assert not (tmp_path / "notification_state.json").exists()


@pytest.mark.asyncio
async def test_unauthorized_denial_fails_safely_without_stream(tmp_path) -> None:
    instance = ZjcsGuildNotifier()
    instance._ctx = make_context(tmp_path)
    config = make_config()
    config["command"]["admin_qqs"] = ["10000"]
    instance.set_plugin_config(config)

    result = await instance.handle_zjcs_command(
        stream_id="", user_id="99999", matched_groups={"sub": "预览"}
    )

    assert result == (False, "缺少命令来源 stream_id", True)
    assert instance.ctx.send.calls == []


@pytest.mark.asyncio
async def test_admin_qqs_empty_allows_any_user_for_every_subcommand(
    tmp_path, monkeypatch
) -> None:
    instance = ZjcsGuildNotifier()
    instance._ctx = make_context(tmp_path)
    instance.set_plugin_config(make_config())
    monkeypatch.setattr(
        instance,
        "_build_configured_reminders",
        lambda *, today: ([], 1),
    )

    assert await instance.handle_zjcs_command(
        stream_id="s", user_id="任何用户", matched_groups=None
    ) == (True, "指令帮助已发送", True)
    assert await instance.handle_zjcs_command(
        stream_id="s", user_id="另一个用户", matched_groups={"sub": "预览"}
    ) == (True, "今日提醒预览已生成", True)
    assert await instance.handle_zjcs_command(
        stream_id="s",
        user_id="",
        group_id="123456",
        platform="qq",
        matched_groups={"sub": "测试"},
    ) == (True, "测试消息已发送", True)

    assert len(instance.ctx.send.calls) == 3


@pytest.mark.asyncio
async def test_help_is_sent_for_bare_root_help_and_unknown_subcommand(
    tmp_path,
) -> None:
    instance = ZjcsGuildNotifier()
    instance._ctx = make_context(tmp_path)
    instance.set_plugin_config(make_config())

    for matched_groups in (None, {}, {"sub": "帮助"}, {"sub": "不存在"}):
        assert await instance.handle_zjcs_command(
            stream_id="s", matched_groups=matched_groups
        ) == (True, "指令帮助已发送", True)

    assert len(instance.ctx.send.calls) == 4
    for message, stream_id, return_details in instance.ctx.send.calls:
        assert stream_id == "s"
        assert return_details is True
        assert message == plugin.COMMAND_HELP_MESSAGE
    assert "预览" in plugin.COMMAND_HELP_MESSAGE
    assert "测试" in plugin.COMMAND_HELP_MESSAGE
    assert "在当前 QQ 群发送一条链路测试消息" in plugin.COMMAND_HELP_MESSAGE
    assert "不影响提醒状态" in plugin.COMMAND_HELP_MESSAGE
    assert "/zjcs 预览" in plugin.COMMAND_HELP_MESSAGE


@pytest.mark.asyncio
async def test_preview_alias_roots_share_one_implementation(
    tmp_path, monkeypatch
) -> None:
    instance = ZjcsGuildNotifier()
    instance._ctx = make_context(tmp_path)
    instance.set_plugin_config(make_config())
    monkeypatch.setattr(
        instance,
        "_build_configured_reminders",
        lambda *, today: ([], 1),
    )

    first = await instance.handle_zjcs_command(
        stream_id="s1", matched_groups={"sub": "预览"}
    )
    second = await instance.handle_zjcs_command(
        stream_id="s2", matched_groups={"sub": "预览"}
    )

    assert first == second == (True, "今日提醒预览已生成", True)
    assert [call[1] for call in instance.ctx.send.calls] == ["s1", "s2"]
    assert not (tmp_path / "notification_state.json").exists()


@pytest.mark.asyncio
async def test_test_alias_roots_share_one_implementation(tmp_path) -> None:
    instance = ZjcsGuildNotifier()
    instance._ctx = make_context(tmp_path)
    instance.set_plugin_config(make_config())

    first = await instance.handle_zjcs_command(
        stream_id="s1",
        group_id="123456",
        platform="qq",
        matched_groups={"sub": "测试"},
    )
    second = await instance.handle_zjcs_command(
        stream_id="s2",
        group_id="123456",
        platform="qq",
        matched_groups={"sub": "测试"},
    )

    assert first == second == (True, "测试消息已发送", True)
    assert len(instance.ctx.send.calls) == 2
    assert all(call[0] == plugin.TEST_MESSAGE for call in instance.ctx.send.calls)
    assert [call[1] for call in instance.ctx.send.calls] == ["s1", "s2"]
    assert not (tmp_path / "notification_state.json").exists()


def test_v1_config_upgrade_migrates_anchors_groups_and_drops_obsolete_fields(
    tmp_path, monkeypatch
) -> None:
    legacy = {
        "plugin": {"enabled": True, "config_version": "1.0.0"},
        "target": {"group_id": "611817038"},
        "server": {
            "open_date": "2026-06-19",
            "season_anchor_dates": {"S4": "2026-09-20"},
        },
        "schedule": {
            "daily_check_time": "09:00",
            "timezone": "Asia/Shanghai",
            "remind_days_before": [2, 1],
        },
    }

    prepared = rebuild_plugin_config_data(
        plugin.ZjcsGuildNotifier.build_default_config(), legacy
    )
    config_path = tmp_path / "config.toml"
    write_v1_config(config_path, s4_start_date="2026-09-20")
    monkeypatch.setattr(plugin, "CONFIG_PATH", config_path)
    instance = ZjcsGuildNotifier()
    rebuilt, changed = instance.normalize_plugin_config(prepared)

    assert changed is True
    assert rebuilt["plugin"] == {"enabled": True, "config_version": "1.4.0"}
    assert rebuilt["target"] == {"group_ids": ["611817038"]}
    assert rebuilt["server"] == {"open_date": "2026-06-19"}
    assert "remind_days_before" not in rebuilt["schedule"]
    assert rebuilt["reminders"] == {
        "dungeon_remind_day": 1,
        "secret_treasure_remind_day": 2,
        "bingo_remind_day": 4,
        "scratch_remind_day": 2,
        "fenek_remind_day": 2,
        "event_remind_day": 2,
    }
    assert rebuilt["season_dates"] == {
        "s4_start_date": "2026-09-20",
        "s5_start_date": "",
        "s6_start_date": "",
    }
    assert instance._legacy_state_group_id == "611817038"


def test_v1_custom_remind_days_migrate_to_all_categories(tmp_path, monkeypatch) -> None:
    legacy = {
        "plugin": {"enabled": True, "config_version": "1.0.0"},
        "target": {"group_id": "611817038"},
        "server": {"open_date": "2026-06-19", "season_anchor_dates": {}},
        "schedule": {
            "daily_check_time": "09:00",
            "timezone": "Asia/Shanghai",
            "remind_days_before": [3],
        },
    }
    prepared = rebuild_plugin_config_data(
        plugin.ZjcsGuildNotifier.build_default_config(), legacy
    )
    config_path = tmp_path / "config.toml"
    write_v1_config(config_path, remind_days=(3,))
    monkeypatch.setattr(plugin, "CONFIG_PATH", config_path)

    rebuilt, changed = ZjcsGuildNotifier().normalize_plugin_config(prepared)

    assert changed is True
    assert all(value == 3 for value in rebuilt["reminders"].values())
    assert "remind_days_before" not in rebuilt["schedule"]


def test_v1_1_config_upgrade_migrates_group_and_max_remind_day(
    tmp_path, monkeypatch
) -> None:
    legacy = {
        "plugin": {"enabled": True, "config_version": "1.1.0"},
        "target": {"group_id": "611817038"},
        "server": {"open_date": "2026-06-19"},
        "season_dates": {
            "s4_start_date": "",
            "s5_start_date": "",
            "s6_start_date": "",
        },
        "schedule": {"daily_check_time": "09:00", "timezone": "Asia/Shanghai"},
        "reminders": {
            "dungeon_remind_days": [1],
            "secret_treasure_remind_days": [2, 1],
            "bingo_remind_days": [4],
            "scratch_remind_days": [2, 1],
            "fenek_remind_days": [2, 1],
            "event_remind_days": [2, 1],
        },
    }
    prepared = rebuild_plugin_config_data(
        plugin.ZjcsGuildNotifier.build_default_config(), legacy
    )
    config_path = tmp_path / "config.toml"
    write_v1_1_config(config_path)
    monkeypatch.setattr(plugin, "CONFIG_PATH", config_path)
    instance = ZjcsGuildNotifier()

    rebuilt, changed = instance.normalize_plugin_config(prepared)

    assert changed is True
    assert rebuilt["plugin"] == {"enabled": True, "config_version": "1.4.0"}
    assert rebuilt["target"] == {"group_ids": ["611817038"]}
    assert rebuilt["reminders"] == {
        "dungeon_remind_day": 1,
        "secret_treasure_remind_day": 2,
        "bingo_remind_day": 4,
        "scratch_remind_day": 2,
        "fenek_remind_day": 2,
        "event_remind_day": 2,
    }
    assert instance._legacy_state_group_id == "611817038"


def test_v1_1_direct_config_migrates_without_disk_fallback() -> None:
    legacy = {
        "plugin": {"enabled": True, "config_version": "1.1.0"},
        "target": {"group_id": "611817038"},
        "server": {"open_date": "2026-06-19"},
        "season_dates": {
            "s4_start_date": "",
            "s5_start_date": "",
            "s6_start_date": "",
        },
        "schedule": {"daily_check_time": "09:00", "timezone": "Asia/Shanghai"},
        "reminders": {
            "dungeon_remind_days": [1],
            "secret_treasure_remind_days": [2, 1],
            "bingo_remind_days": [4],
            "scratch_remind_days": [2, 1],
            "fenek_remind_days": [2, 1],
            "event_remind_days": [2, 1],
        },
    }
    instance = ZjcsGuildNotifier()

    rebuilt, changed = instance.normalize_plugin_config(legacy)

    assert changed is True
    assert rebuilt["target"] == {"group_ids": ["611817038"]}
    assert rebuilt["reminders"]["dungeon_remind_day"] == 1
    assert rebuilt["reminders"]["secret_treasure_remind_day"] == 2
    assert rebuilt["reminders"]["bingo_remind_day"] == 4
    for old_field in (
        "group_id",
        "dungeon_remind_days",
        "secret_treasure_remind_days",
    ):
        assert old_field not in rebuilt["target"]
        assert old_field not in rebuilt["reminders"]
    assert instance._legacy_state_group_id == "611817038"


def test_v1_1_empty_group_and_invalid_remind_lists_migrate_to_empty_and_zero(
    tmp_path, monkeypatch
) -> None:
    legacy = {
        "plugin": {"enabled": True, "config_version": "1.1.0"},
        "target": {"group_id": ""},
        "server": {"open_date": "2026-06-19"},
        "season_dates": {
            "s4_start_date": "",
            "s5_start_date": "",
            "s6_start_date": "",
        },
        "schedule": {"daily_check_time": "09:00", "timezone": "Asia/Shanghai"},
        "reminders": {
            "dungeon_remind_days": [],
            "secret_treasure_remind_days": [0, -1],
            "bingo_remind_days": [4],
            "scratch_remind_days": [2, 1],
            "fenek_remind_days": [2, 1],
            "event_remind_days": [2, 1],
        },
    }
    instance = ZjcsGuildNotifier()

    rebuilt, changed = instance.normalize_plugin_config(legacy)

    assert changed is True
    assert rebuilt["target"] == {"group_ids": []}
    assert rebuilt["reminders"]["dungeon_remind_day"] == 0
    assert rebuilt["reminders"]["secret_treasure_remind_day"] == 0
    assert rebuilt["reminders"]["bingo_remind_day"] == 4
    assert instance._legacy_state_group_id is None


def test_v1_1_custom_list_values_keep_the_earlier_reminder() -> None:
    legacy = {
        "plugin": {"enabled": True, "config_version": "1.1.0"},
        "target": {"group_id": "611817038"},
        "server": {"open_date": "2026-06-19"},
        "season_dates": {
            "s4_start_date": "",
            "s5_start_date": "",
            "s6_start_date": "",
        },
        "schedule": {"daily_check_time": "09:00", "timezone": "Asia/Shanghai"},
        "reminders": {
            "dungeon_remind_days": [1],
            "secret_treasure_remind_days": [3, 1],
            "bingo_remind_days": [5, 2],
            "scratch_remind_days": [2, 1],
            "fenek_remind_days": [2, 1],
            "event_remind_days": [2, 1],
        },
    }
    instance = ZjcsGuildNotifier()

    rebuilt, changed = instance.normalize_plugin_config(legacy)

    assert changed is True
    assert rebuilt["reminders"]["secret_treasure_remind_day"] == 3
    assert rebuilt["reminders"]["bingo_remind_day"] == 5


def test_v1_2_config_values_are_not_overwritten_by_legacy_disk(
    tmp_path, monkeypatch
) -> None:
    current = plugin.ZjcsGuildNotifierConfig().model_dump(mode="python")
    current["target"]["group_ids"] = ["999999999"]
    current["reminders"]["bingo_remind_day"] = 6
    config_path = tmp_path / "config.toml"
    write_v1_1_config(config_path)
    monkeypatch.setattr(plugin, "CONFIG_PATH", config_path)
    instance = ZjcsGuildNotifier()

    rebuilt, changed = instance.normalize_plugin_config(current)

    assert rebuilt["target"] == {"group_ids": ["999999999"]}
    assert rebuilt["reminders"]["bingo_remind_day"] == 6
    assert rebuilt["reminders"]["secret_treasure_remind_day"] == 2
    assert instance._legacy_state_group_id == "611817038"
    # 已有用户值未被覆盖，其余旧盘值恰好等于新版默认值，无需产生变更。
    assert changed is False


def test_stale_v1_1_fields_in_v1_2_config_are_ignored(tmp_path, monkeypatch) -> None:
    current = plugin.ZjcsGuildNotifierConfig().model_dump(mode="python")
    current["target"]["group_id"] = "611817038"
    current["reminders"]["dungeon_remind_days"] = [3]
    monkeypatch.setattr(plugin, "CONFIG_PATH", tmp_path / "missing-config.toml")

    rebuilt, _ = ZjcsGuildNotifier().normalize_plugin_config(current)

    assert rebuilt["target"] == {"group_ids": []}
    assert "dungeon_remind_days" not in rebuilt["reminders"]
    assert rebuilt["reminders"]["dungeon_remind_day"] == 1
    assert "remind_days_before" not in rebuilt["schedule"]


def test_invalid_disk_config_does_not_block_v1_2_normalization(
    tmp_path, monkeypatch, caplog
) -> None:
    invalid_config_path = tmp_path / "config.toml"
    invalid_config_path.write_text("[plugin\n", encoding="utf-8")
    monkeypatch.setattr(plugin, "CONFIG_PATH", invalid_config_path)
    current = plugin.ZjcsGuildNotifierConfig().model_dump(mode="python")

    with caplog.at_level(logging.WARNING, logger=plugin.PLUGIN_ID):
        rebuilt, _ = ZjcsGuildNotifier().normalize_plugin_config(current)

    assert rebuilt == current
    assert "将按 Host 已提供配置继续" in caplog.text


def test_normalized_group_ids_strip_drop_and_keep_order() -> None:
    assert plugin._normalized_group_ids([" 111 ", "", "222", "111", "  ", "333"]) == [
        "111",
        "222",
        "333",
    ]
    assert plugin._normalized_group_ids([]) == []
    assert plugin._normalized_group_ids(["", "   "]) == []


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
