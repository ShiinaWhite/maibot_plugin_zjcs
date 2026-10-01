from copy import deepcopy
from datetime import date, datetime, timedelta
import json
from types import SimpleNamespace

import pytest

import plugin
from plugin import ZjcsGuildNotifier
from timeline import (
    QUERY_TOPICS,
    build_query_facts,
    find_next_season,
    find_next_weekly_activity,
    load_timeline,
)

OPEN_DATE = date(2026, 6, 19)
TODAY = date(2026, 9, 14)


def facts(query, *, timeline=None, today=TODAY, anchors=None, activity=None):
    return build_query_facts(
        load_timeline("timeline_v1.json") if timeline is None else timeline,
        query=query,
        today=today,
        open_date=OPEN_DATE,
        season_anchor_dates=anchors,
        activity_name=activity,
    )


@pytest.mark.parametrize(
    ("activity", "server_day"),
    [("宾果抽抽乐", 99), ("幸运刮刮乐", 106), ("菲涅克的谜题", 92)],
)
def test_named_weekly_uses_real_rotation(activity, server_day):
    result = facts("next_weekly_activity", activity=activity)
    assert result["status"] == "ok"
    assert result["data"]["name"] == activity
    assert result["data"]["payload"]["server_day"] == server_day
    assert (
        result["data"]["event_date"]
        == (OPEN_DATE + timedelta(days=server_day - 1)).isoformat()
    )


def test_named_weekly_today_and_next_cycle():
    opening = OPEN_DATE + timedelta(days=98)
    assert (
        facts("next_weekly_activity", today=opening, activity="宾果抽抽乐")["data"][
            "days_until"
        ]
        == 0
    )
    assert (
        facts(
            "next_weekly_activity",
            today=opening + timedelta(days=1),
            activity="宾果抽抽乐",
        )["data"]["days_until"]
        == 20
    )


def test_named_weekly_data_driven_duplicate_rotation_and_unknown_name():
    timeline = {
        "activity_rules": {
            "weekly_side_activity_rotation": {
                "first_server_day": 15,
                "period_days": 5,
                "rotation": ["A", "B", "A", "C"],
            }
        }
    }
    entry = find_next_weekly_activity(
        timeline,
        today=OPEN_DATE + timedelta(days=15),
        open_date=OPEN_DATE,
        activity_name="A",
    )
    assert entry.payload["server_day"] == 25
    assert (
        find_next_weekly_activity(
            timeline, today=TODAY, open_date=OPEN_DATE, activity_name="missing"
        )
        is None
    )


def test_next_season_real_date_and_rollover():
    result = facts("next_season")
    assert result["data"]["payload"]["season"] == "S3"
    assert result["data"]["event_date"] == "2026-10-10"
    assert result["data"]["days_until"] == 26
    # S3 更新当天已属于 S3；不能继续称为下一赛季。
    assert facts("next_season", today=date(2026, 10, 10))["status"] == "unknown"


def test_next_season_missing_adjacent_anchor_does_not_skip_to_s5():
    result = facts(
        "next_season", today=date(2026, 10, 11), anchors={"S5": date(2027, 2, 1)}
    )
    assert result["status"] == "unknown"
    assert result["data"] is None
    assert "不推测" in result["reason"]
    result = facts(
        "next_season", today=date(2026, 10, 11), anchors={"S4": date(2026, 12, 1)}
    )
    assert result["data"]["event_date"] == "2026-12-01"
    assert result["data"]["payload"]["season"] == "S4"


@pytest.mark.parametrize(
    "change",
    [
        {"status": "pending"},
        {"server_day": None},
        {"event_date": "2026-10-10"},
        {"server_day": True},
    ],
)
def test_next_season_fails_closed_for_unreliable_or_ambiguous_data(change):
    timeline = load_timeline("timeline_v1.json")
    season = next(
        item for item in timeline["events"] if item["id"] == "season_s3_start"
    )
    season.update(change)
    assert find_next_season(timeline, today=TODAY, open_date=OPEN_DATE) is None


def test_next_season_accepts_absolute_date_and_no_data_means_unknown():
    timeline = {
        "events": [
            {
                "id": "season_s1_start",
                "name": "S1",
                "type": "season",
                "season": "S1",
                "event_date": "2026-09-20",
                "status": "confirmed",
            }
        ]
    }
    assert facts("next_season", timeline=timeline)["data"]["event_date"] == "2026-09-20"
    assert facts("next_season", timeline={})["status"] == "unknown"


@pytest.mark.parametrize("today", [date(2026, 9, 10), TODAY])
def test_absolute_current_season_selects_adjacent_next_season(today):
    timeline = {
        "events": [
            {
                "id": "s1",
                "name": "S1",
                "type": "season",
                "season": "S1",
                "event_date": "2026-09-10",
                "status": "confirmed",
            },
            {
                "id": "s2",
                "name": "S2",
                "type": "season",
                "season": "S2",
                "event_date": "2026-09-20",
                "status": "confirmed",
            },
        ]
    }
    result = facts("next_season", timeline=timeline, today=today)
    assert result["data"]["payload"]["season"] == "S2"
    assert result["data"]["event_date"] == "2026-09-20"


def test_dungeon_facts_keep_raw_power_and_preparation_dates():
    result = facts("next_dungeon")
    assert result["data"]["name"] == "仙海云舟"
    assert result["data"]["payload"]["requirements"]["普通"] == 16_500_000
    assert result["data"]["prepare_date"] == "2026-09-24"
    assert result["data"]["days_until_prepare"] == 10
    assert result["data"]["requirements_available"] is True


def test_pending_power_never_leaks_to_tool():
    timeline = {
        "dungeons": [
            {
                "id": "pending",
                "name": "pending",
                "server_day": 99,
                "status": "pending_formal_power",
                "requirements": {"普通": 999},
            }
        ]
    }
    data = facts("next_dungeon", timeline=timeline)["data"]
    assert data["payload"]["requirements"] == {}
    assert data["requirements_available"] is False


def test_partial_dungeon_power_does_not_invent_missing_difficulties():
    timeline = {
        "dungeons": [
            {
                "id": "partial",
                "name": "测试副本",
                "server_day": 99,
                "status": "confirmed_partial",
                "requirements": {"普通": 16_500_000, "困难": None},
            }
        ]
    }
    data = facts("next_dungeon", timeline=timeline)["data"]
    assert data["payload"]["requirements"] == {"普通": 16_500_000}
    assert data["requirements_available"] is True
    assert "噩梦" not in data["payload"]["requirements"]


def test_progress_day_one_and_schedule_window():
    assert facts("progress", today=OPEN_DATE)["data"]["server_day"] == 1
    result = facts("schedule")
    assert result["data"]["horizon_days"] == 14
    assert result["data"]["end_date"] == "2026-09-27"
    assert any(entry["name"] == "非人哉联动" for entry in result["data"]["entries"])
    assert all(0 <= entry["days_until"] < 14 for entry in result["data"]["entries"])
    assert facts("schedule", timeline={})["data"]["entries"] == []


@pytest.mark.parametrize(
    ("phase_index", "phase_key"), [(11, "current_phase"), (12, "next_phase")]
)
def test_treasure_explicit_category_and_unavailable_are_distinct(
    phase_index, phase_key
):
    result = facts("secret_treasure")
    assert result["data"]["current_phase"]["reward_mode"] == "explicit"
    result = facts("secret_treasure", today=OPEN_DATE + timedelta(days=119))
    assert result["data"]["current_phase"]["reward_mode"] == "rule_fallback"
    assert "featured_reward" not in result["data"]["current_phase"]["payload"]
    timeline = load_timeline("timeline_v1.json")
    phase = timeline["activity_rules"]["secret_treasure_battle"]["known_phases"][
        phase_index
    ]
    phase["status"] = "pending"
    phase["name"] = "PENDING_PHASE_NAME_DO_NOT_EXPOSE"
    phase["featured_reward"]["name"] = "DO_NOT_EXPOSE"
    result = facts("secret_treasure", timeline=timeline)
    assert result["data"][phase_key]["reward_mode"] == "unavailable"
    assert "DO_NOT_EXPOSE" not in json.dumps(result)


@pytest.mark.parametrize("query", QUERY_TOPICS)
def test_facts_are_json_ready_deterministic_and_do_not_mutate_timeline(query):
    timeline = load_timeline("timeline_v1.json")
    before = deepcopy(timeline)
    first = facts(query, timeline=timeline)
    assert json.loads(json.dumps(first)) == first
    assert facts(query, timeline=timeline) == first
    assert timeline == before
    assert facts(query, today=OPEN_DATE - timedelta(days=1))["status"] == "unknown"


@pytest.mark.parametrize(
    ("query", "activity"),
    [
        ("invalid", None),
        ("next_weekly_activity", "随便"),
        ("progress", "宾果抽抽乐"),
    ],
)
def test_invalid_query_arguments_are_rejected(query, activity):
    with pytest.raises(ValueError):
        facts(query, activity=activity)


@pytest.fixture
def tool_instance(monkeypatch):
    class FixedDatetime:
        @staticmethod
        def now(tz):
            # 对应 UTC 2026-09-13 16:00，上海已跨日。
            return datetime(2026, 9, 14, 0, 0, tzinfo=tz)

    monkeypatch.setattr(plugin, "datetime", FixedDatetime)
    instance = ZjcsGuildNotifier()
    instance.set_plugin_config(
        {
            "server": {"open_date": OPEN_DATE.isoformat()},
            "command": {"admin_qqs": ["111111"]},
            "plugin": {"enabled": False, "config_version": "1.4.0"},
            "schedule": {"timezone": "Asia/Shanghai", "daily_check_time": "bad"},
            "reminders": {
                "dungeon_remind_day": 0,
                "secret_treasure_remind_day": 0,
                "bingo_remind_day": 0,
                "scratch_remind_day": 0,
                "fenek_remind_day": 0,
                "event_remind_day": 0,
            },
        }
    )
    # Tool 不需要消息投递、路径、持久化等宿主上下文能力。
    instance._ctx = SimpleNamespace()
    return instance


def test_sdk_registers_one_visible_tool_with_typed_parameters():
    components = ZjcsGuildNotifier().get_components()
    assert {(item["type"], item["name"]) for item in components} == {
        ("COMMAND", "zjcs_command"),
        ("TOOL", "zjcs_query"),
    }
    tool = next(item for item in components if item["type"] == "TOOL")
    metadata = tool["metadata"]
    assert metadata["visibility"] == "visible"
    assert metadata["invoke_method"] == "plugin.invoke_tool"
    assert metadata["handler_name"] == "query_zjcs_facts"
    query, activity = metadata["parameters"]
    assert query["name"] == "query" and query["required"] is True
    assert query["enum_values"] == list(QUERY_TOPICS)
    assert activity["name"] == "activity" and activity["required"] is False
    assert activity["enum_values"] == ["宾果抽抽乐", "幸运刮刮乐", "菲涅克的谜题"]


@pytest.mark.asyncio
@pytest.mark.parametrize("query", QUERY_TOPICS)
async def test_tool_does_not_touch_state_send_or_scheduler(
    tool_instance, tmp_path, query
):
    state_file = tmp_path / "notification_state.json"
    before = b'{"version":2,"groups":{"test":["already-sent"]}}'
    state_file.write_bytes(before)
    result = await tool_instance.query_zjcs_facts(
        query=query,
        stream_id="source",
        group_id="123456",
        user_id="999999",
        platform="qq",
        today="2099-01-01",
        open_date="2099-01-01",
    )
    assert result["success"] is True
    assert json.loads(result["content"]) == result["facts"]
    assert result["facts"]["as_of"] == "2026-09-14"
    assert result["facts"]["timezone"] == "Asia/Shanghai"
    assert "999999" not in result["content"]
    assert "123456" not in result["content"]
    assert state_file.read_bytes() == before
    assert list(tmp_path.iterdir()) == [state_file]
    assert tool_instance._daily_task is None


@pytest.mark.asyncio
async def test_tool_returns_unknown_as_successful_fact_query(tool_instance):
    config = tool_instance.config.model_dump()
    config["server"]["open_date"] = "2026-01-01"
    tool_instance.set_plugin_config(config)
    result = await tool_instance.query_zjcs_facts("next_season")
    assert result["success"] is True
    assert result["facts"]["status"] == "unknown"
    assert result["facts"]["data"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "activity"),
    [
        ("invalid", None),
        ("", None),
        ("progress", "宾果抽抽乐"),
        ("next_weekly_activity", "宾果"),
        ("next_weekly_activity", []),
    ],
)
async def test_tool_reports_invalid_args_without_querying(
    tool_instance, monkeypatch, query, activity
):
    def should_not_read(*args):
        raise AssertionError("无效参数不得读取数据")

    monkeypatch.setattr(plugin, "load_timeline", should_not_read)
    result = await tool_instance.query_zjcs_facts(query, activity)
    assert result["success"] is False
    assert result["facts"]["status"] == "error"
    assert result["facts"]["data"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "config_change",
    [
        {"server": {"open_date": ""}},
        {"server": {"open_date": "bad"}},
        {"schedule": {"timezone": "Invalid/Zone"}},
        {"season_dates": {"s4_start_date": "bad"}},
    ],
)
async def test_tool_reports_bad_config_without_leaking_values(
    tool_instance, config_change
):
    config = tool_instance.config.model_dump()
    for section, change in config_change.items():
        config[section].update(change)
    tool_instance.set_plugin_config(config)
    result = await tool_instance.query_zjcs_facts("next_dungeon")
    assert result["success"] is False
    assert "Invalid/Zone" not in result["content"]
    assert result["facts"]["data"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "contents",
    [
        "{",
        "[]",
        '{"dungeons": [], "events": []}',
        '{"dungeons": [{"id": "overflow", "name": "overflow", "status": "confirmed", "server_day": 999999999}]}',
    ],
)
async def test_tool_handles_missing_bad_and_empty_timeline(
    tool_instance, tmp_path, monkeypatch, contents
):
    path = tmp_path / "private-timeline.json"
    monkeypatch.setattr(plugin, "TIMELINE_PATH", path)
    missing = await tool_instance.query_zjcs_facts("next_dungeon")
    assert missing["success"] is False
    assert str(path) not in missing["content"]
    path.write_text(contents, encoding="utf-8")
    result = await tool_instance.query_zjcs_facts("next_dungeon")
    assert result["facts"]["status"] == (
        "unknown" if contents == '{"dungeons": [], "events": []}' else "error"
    )
    assert result["facts"]["data"] is None


@pytest.mark.asyncio
async def test_tool_uses_fresh_config_and_clock_timezone(tool_instance, monkeypatch):
    from zoneinfo import ZoneInfo

    class UtcBoundary:
        @staticmethod
        def now(tz):
            return datetime(2026, 9, 13, 16, 0, tzinfo=ZoneInfo("UTC")).astimezone(tz)

    monkeypatch.setattr(plugin, "datetime", UtcBoundary)
    first = await tool_instance.query_zjcs_facts("progress")
    assert first["facts"]["data"]["server_day"] == 88
    config = tool_instance.config.model_dump()
    config["server"]["open_date"] = "2026-06-20"
    config["schedule"]["timezone"] = "UTC"
    tool_instance.set_plugin_config(config)
    second = await tool_instance.query_zjcs_facts("progress")
    assert second["facts"]["as_of"] == "2026-09-13"
    assert second["facts"]["data"]["server_day"] == 86
