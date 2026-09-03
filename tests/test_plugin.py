from __future__ import annotations

import asyncio
from datetime import date, datetime, time
import json
import logging
from types import SimpleNamespace

from maibot_sdk.config import generate_plugin_config_schema, rebuild_plugin_config_data
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
        "plugin": {"enabled": True, "config_version": "1.1.0"},
        "target": {"group_id": "123456"},
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
            "dungeon_remind_days": [1],
            "secret_treasure_remind_days": [1],
            "bingo_remind_days": [1],
            "scratch_remind_days": [1],
            "fenek_remind_days": [1],
            "event_remind_days": [1],
        },
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


def read_sent_keys(tmp_path) -> list[str]:
    return json.loads(
        (tmp_path / "notification_state.json").read_text(encoding="utf-8")
    )["sent"]


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
    assert message.count("【杖剑传说 · 每日提醒】") == 1
    assert "【副本】测试区 · 测试副本" in message
    assert "【活动】宾果抽抽乐" in message
    assert "【事件】测试事件" in message
    assert read_sent_keys(tmp_path) == [
        "test_dungeon:2026-01-02:1",
        "test_event:2026-01-02:1",
        "weekly_side_activity_2:2026-01-02:1",
    ]
    assert "reminders=3" in caplog.text
    assert "pending=3" in caplog.text
    assert "merged_reminders=3" in caplog.text
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
    assert len(read_sent_keys(tmp_path)) == 3


@pytest.mark.asyncio
async def test_partial_dedupe_merges_only_pending_items(tmp_path, monkeypatch) -> None:
    write_three_reminder_timeline(tmp_path)
    monkeypatch.setattr(plugin, "TIMELINE_PATH", tmp_path / "timeline.json")
    NotificationState(tmp_path / "notification_state.json").load().mark_sent(
        "test_dungeon:2026-01-02:1"
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
    assert len(read_sent_keys(tmp_path)) == 3


@pytest.mark.asyncio
async def test_state_batch_write_failure_does_not_repeat_send(
    tmp_path, monkeypatch
) -> None:
    write_three_reminder_timeline(tmp_path)
    monkeypatch.setattr(plugin, "TIMELINE_PATH", tmp_path / "timeline.json")

    def fail_mark_sent_many(_state, _keys: list[str]) -> None:
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
@pytest.mark.parametrize("remind_days", [[], [0], [-1], [2, 0]])
async def test_invalid_policy_logs_config_error_and_skips_round(
    tmp_path, monkeypatch, caplog, remind_days
) -> None:
    write_three_reminder_timeline(tmp_path)
    monkeypatch.setattr(plugin, "TIMELINE_PATH", tmp_path / "timeline.json")
    instance = ZjcsGuildNotifier()
    instance._ctx = make_context(tmp_path)
    config = make_config()
    config["reminders"]["dungeon_remind_days"] = remind_days
    instance.set_plugin_config(config)

    with caplog.at_level(logging.ERROR, logger=plugin.PLUGIN_ID):
        await instance._run_daily_check(today=date(2026, 1, 1))

    assert "dungeon_remind_days" in caplog.text
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

    await instance.on_config_update("self", {}, "1.1.0")
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
    reminder = Reminder(
        event_id="preview_event",
        category="event",
        name="预览事件",
        event_date=date(2026, 1, 2),
        remind_days_before=1,
        date_label="开放日期",
        payload={},
        current_server_day=1,
    )
    instance = ZjcsGuildNotifier()
    instance._ctx = make_context(tmp_path)
    instance.set_plugin_config(make_config())
    monkeypatch.setattr(
        instance,
        "_build_configured_reminders",
        lambda *, today: ([reminder], 1),
    )

    result = await instance.handle_preview(stream_id="operator-stream")

    assert result == (True, "今日提醒预览已生成", True)
    assert len(instance.ctx.send.calls) == 1
    message, stream_id, _ = instance.ctx.send.calls[0]
    assert stream_id == "operator-stream"
    assert "【杖剑助手 · 今日提醒预览】" in message
    assert "仅供预览" in message
    assert "预览事件" in message
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

    result = await instance.handle_preview(stream_id="operator-stream")

    assert result == (False, "今日提醒预览发送失败", True)
    assert not (tmp_path / "notification_state.json").exists()


@pytest.mark.asyncio
async def test_test_send_uses_normal_chain_and_does_not_write_state(tmp_path) -> None:
    instance = ZjcsGuildNotifier()
    instance._ctx = make_context(tmp_path)
    instance.set_plugin_config(make_config())

    result = await instance.handle_test_send()

    assert result == (True, "测试消息发送成功", True)
    assert len(instance.ctx.send.calls) == 1
    message, stream_id, return_details = instance.ctx.send.calls[0]
    assert message == plugin.TEST_MESSAGE
    assert "测试消息" in message
    assert "这不是游戏活动提醒" in message
    assert stream_id == "stream-123"
    assert return_details is True
    assert not (tmp_path / "notification_state.json").exists()


def test_config_schema_is_chinese_and_has_no_object_season_field() -> None:
    schema = generate_plugin_config_schema(plugin.ZjcsGuildNotifierConfig)
    sections = schema["sections"]

    assert [section["title"] for section in sections.values()] == [
        "基础设置",
        "通知目标",
        "服务器进度",
        "S4+ 赛季日期",
        "每日调度",
        "提醒时间",
    ]
    expected_labels = {
        "plugin": {"enabled": "启用杖剑助手", "config_version": "配置版本"},
        "target": {"group_id": "目标 QQ 群号"},
        "server": {"open_date": "开服日期"},
        "season_dates": {
            "s4_start_date": "S4 赛季开始日期",
            "s5_start_date": "S5 赛季开始日期",
            "s6_start_date": "S6 赛季开始日期",
        },
        "schedule": {"daily_check_time": "每日检查时间", "timezone": "时区"},
        "reminders": {
            "dungeon_remind_days": "副本提前提醒天数",
            "secret_treasure_remind_days": "秘宝大作战提前提醒天数",
            "bingo_remind_days": "宾果抽抽乐提前提醒天数",
            "scratch_remind_days": "幸运刮刮乐提前提醒天数",
            "fenek_remind_days": "菲涅克的谜题提前提醒天数",
            "event_remind_days": "遗物池及重要事件提前提醒天数",
        },
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
    assert all(
        field["type"] == "array" and field["item_type"] == "number"
        for field in sections["reminders"]["fields"].values()
    )


def test_config_defaults_match_v1_1_production_policy() -> None:
    config = plugin.ZjcsGuildNotifierConfig()

    assert config.plugin.config_version == "1.1.0"
    assert config.reminders.dungeon_remind_days == [1]
    assert config.reminders.secret_treasure_remind_days == [2, 1]
    assert config.reminders.bingo_remind_days == [4]
    assert config.reminders.scratch_remind_days == [2, 1]
    assert config.reminders.fenek_remind_days == [2, 1]
    assert config.reminders.event_remind_days == [2, 1]
    assert config.season_dates.s4_start_date == ""
    assert config.season_dates.s5_start_date == ""
    assert config.season_dates.s6_start_date == ""


def test_public_default_config_contains_only_v1_1_fields() -> None:
    default_config = ZjcsGuildNotifier().get_default_config()

    assert "season_anchor_dates" not in default_config["server"]
    assert "remind_days_before" not in default_config["schedule"]


def test_diagnostic_commands_are_operator_only() -> None:
    components = {
        component["name"]: component
        for component in ZjcsGuildNotifier().get_components()
    }

    assert components["preview"]["metadata"]["permission"] == "operator"
    assert components["preview"]["metadata"]["command_pattern"] == (
        r"^/zjcs_preview\s*$"
    )
    assert components["test_send"]["metadata"]["permission"] == "operator"
    assert components["test_send"]["metadata"]["command_pattern"] == (
        r"^/zjcs_test\s*$"
    )


def test_v1_config_upgrade_migrates_anchor_and_drops_obsolete_fields(
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
    rebuilt, changed = ZjcsGuildNotifier().normalize_plugin_config(prepared)

    assert changed is True
    assert rebuilt["plugin"] == {"enabled": True, "config_version": "1.1.0"}
    assert rebuilt["target"]["group_id"] == "611817038"
    assert rebuilt["server"] == {"open_date": "2026-06-19"}
    assert "remind_days_before" not in rebuilt["schedule"]
    assert rebuilt["reminders"]["dungeon_remind_days"] == [1]
    assert rebuilt["reminders"]["bingo_remind_days"] == [4]
    assert rebuilt["season_dates"] == {
        "s4_start_date": "2026-09-20",
        "s5_start_date": "",
        "s6_start_date": "",
    }


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
    assert all(value == [3] for value in rebuilt["reminders"].values())
    assert "remind_days_before" not in rebuilt["schedule"]


def test_stale_v1_remind_days_in_v1_1_config_are_ignored() -> None:
    current = plugin.ZjcsGuildNotifierConfig().model_dump(mode="python")
    current["plugin"]["config_version"] = "1.1.0"
    current["schedule"]["remind_days_before"] = [3]

    rebuilt, _ = ZjcsGuildNotifier().normalize_plugin_config(current)

    assert rebuilt["reminders"]["dungeon_remind_days"] == [1]
    assert rebuilt["reminders"]["secret_treasure_remind_days"] == [2, 1]
    assert rebuilt["reminders"]["bingo_remind_days"] == [4]
    assert "remind_days_before" not in rebuilt["schedule"]


def test_invalid_disk_config_does_not_block_v1_1_normalization(
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
