"""0.1.12 Release Candidate 最终产品矩阵。

把 0.1.5～0.1.11 累积的时间线 contract 与 0.1.6～0.1.10 的查询能力
组合成一个可部署、可验证的最终回归基准。
"""

from datetime import date

from plugin import COMMAND_HELP_MESSAGE
from timeline import (
    ReminderPolicy,
    audit_timeline_integrity,
    build_reminders,
    build_secret_treasure_overview,
    build_server_progress,
    build_upcoming_schedule,
    dungeon_prepare_date,
    find_next_dungeon,
    find_next_weekly_activity,
    load_timeline,
    make_notification_key,
)

RC_TODAY = date(2026, 9, 14)
RC_OPEN_DATE = date(2026, 6, 19)
REMINDER_LEADS = {
    "dungeon": 2,
    "secret_treasure": 2,
    "bingo": 4,
    "scratch": 2,
    "fenek": 2,
    "event": 2,
}


def _timeline() -> dict:
    return load_timeline("timeline_v1.json")


def test_rc_timeline_integrity_is_clean() -> None:
    assert audit_timeline_integrity(_timeline()) == []


def test_rc_plugin_id_is_frozen() -> None:
    from plugin import PLUGIN_ID

    assert PLUGIN_ID == "zjcs.guild-notifier"


def test_rc_final_command_inventory_is_locked() -> None:
    inventory = ["帮助", "预览", "日程", "副本", "进度", "秘宝", "活动", "测试"]
    for subcommand in inventory:
        assert subcommand in COMMAND_HELP_MESSAGE
        assert f"/zjcs {subcommand}" in COMMAND_HELP_MESSAGE
    for legacy in ("/zjcs_preview", "/zjcs_test"):
        assert legacy not in COMMAND_HELP_MESSAGE


def test_rc_real_day88_query_matrix() -> None:
    timeline = _timeline()

    progress = build_server_progress(
        timeline,
        today=RC_TODAY,
        open_date=RC_OPEN_DATE,
        season_anchor_dates={},
    )
    assert progress.server_day == 88
    assert progress.current_season == "S2"
    assert progress.season_day == 42
    assert progress.recent_node is not None
    assert progress.recent_node.name == "龙国第二期遗物：道衍天机"
    assert progress.next_node is not None
    assert progress.next_node.name == "新幻兽：竹林仙君"
    assert "非人哉联动" not in (
        progress.recent_node.name,
        progress.next_node.name,
    )

    schedule = build_upcoming_schedule(timeline, today=RC_TODAY, open_date=RC_OPEN_DATE)
    by_date = {}
    for entry in schedule:
        by_date.setdefault(entry.event_date, set()).add(entry.name)
    assert by_date[date(2026, 9, 18)] >= {
        "秘宝大作战·第13期",
        "菲涅克的谜题",
        "新幻兽：竹林仙君",
    }
    assert "非人哉联动" in by_date[date(2026, 9, 24)]
    assert by_date[date(2026, 9, 25)] >= {
        "仙海云舟",
        "秘宝大作战·第14期",
        "宾果抽抽乐",
    }

    dungeon = find_next_dungeon(timeline, today=RC_TODAY, open_date=RC_OPEN_DATE)
    assert dungeon is not None
    assert dungeon.name == "仙海云舟"
    assert dungeon.payload["region"] == "龙之国"
    assert dungeon.event_date == date(2026, 9, 25)
    assert dungeon.payload["requirements"]["普通"] == 16_500_000
    assert dungeon_prepare_date(dungeon.event_date) == date(2026, 9, 24)

    treasure = build_secret_treasure_overview(
        timeline, today=RC_TODAY, open_date=RC_OPEN_DATE
    )
    assert treasure.current_phase is not None
    assert treasure.current_phase.phase == 12
    assert treasure.current_phase.payload["featured_reward"]["name"] == "原初宝石"
    assert treasure.next_phase is not None
    assert treasure.next_phase.phase == 13
    assert (
        treasure.next_phase.payload["featured_reward"]["name"]
        == "自选奇迹遗物箱·龙Ⅱ（道衍天机）"
    )

    weekly = find_next_weekly_activity(timeline, today=RC_TODAY, open_date=RC_OPEN_DATE)
    assert weekly is not None
    assert weekly.name == "菲涅克的谜题"
    assert weekly.payload["server_day"] == 92
    assert weekly.event_date == date(2026, 9, 18)


def test_rc_reminder_dates_0916_and_0922() -> None:
    timeline = _timeline()
    production_policy = dict(REMINDER_LEADS)

    reminders_0916 = build_reminders(
        timeline,
        today=date(2026, 9, 16),
        open_date=RC_OPEN_DATE,
        reminder_policy=ReminderPolicy(**production_policy),
    )
    names_0916 = {reminder.name for reminder in reminders_0916}
    assert {"秘宝大作战·第13期", "菲涅克的谜题", "新幻兽：竹林仙君"} <= names_0916

    reminders_0922 = build_reminders(
        timeline,
        today=date(2026, 9, 22),
        open_date=RC_OPEN_DATE,
        reminder_policy=ReminderPolicy(**production_policy),
    )
    feiren = [
        reminder
        for reminder in reminders_0922
        if reminder.event_id == "feiren_zai_collaboration"
    ]
    assert len(feiren) == 1
    assert (
        make_notification_key(
            feiren[0].event_id, feiren[0].event_date, feiren[0].remind_days_before
        )
        == "feiren_zai_collaboration:2026-09-24:2"
    )


def test_rc_state_contract_queries_are_read_only() -> None:
    # 只读查询构建器是纯函数：同一输入两次构建结果一致，且不接触任何状态。
    timeline = _timeline()
    first = build_upcoming_schedule(timeline, today=RC_TODAY, open_date=RC_OPEN_DATE)
    second = build_upcoming_schedule(timeline, today=RC_TODAY, open_date=RC_OPEN_DATE)

    assert first == second


def test_rc_version_contract() -> None:
    import json
    from pathlib import Path

    manifest = json.loads(
        (Path(__file__).resolve().parent.parent / "_manifest.json").read_text(
            encoding="utf-8"
        )
    )

    assert manifest["version"] == "0.1.12"
    assert manifest["id"] == "zjcs.guild-notifier"
