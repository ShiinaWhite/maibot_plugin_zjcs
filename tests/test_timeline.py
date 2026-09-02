from datetime import date

from timeline import (
    build_reminders,
    calculate_event_date,
    format_power,
    format_reminder,
    load_timeline,
    make_notification_key,
)


def test_current_server_day_is_the_message_day() -> None:
    timeline = {
        "dungeons": [
            {
                "id": "test_dungeon",
                "name": "测试副本",
                "server_day": 3,
                "requirements": {"普通": 6_200_000},
                "status": "confirmed",
            }
        ]
    }

    reminders = build_reminders(
        timeline,
        today=date(2026, 1, 1),
        open_date=date(2026, 1, 1),
        remind_days_before=[2],
    )

    assert len(reminders) == 1
    message = format_reminder(reminders[0])
    assert "还有 2 天" in message
    assert "开放日期：2026-01-03" in message
    assert "当前服务器进度：开服第 1 天" in message


def test_pending_formal_power_keeps_dungeon_date_but_hides_power() -> None:
    timeline = {
        "dungeons": [
            {
                "id": "pending_dungeon",
                "name": "待确认副本",
                "server_day": 3,
                "requirements": {"普通": 6_200_000},
                "status": "pending_formal_power",
            }
        ]
    }

    reminders = build_reminders(
        timeline,
        today=date(2026, 1, 1),
        open_date=date(2026, 1, 1),
        remind_days_before=[2],
    )

    assert len(reminders) == 1
    message = format_reminder(reminders[0])
    assert "待确认副本" in message
    assert "开放日期：2026-01-03" in message
    assert "已确认准入战力" not in message
    assert "620万" not in message


def test_version_risk_is_not_added_to_group_message() -> None:
    timeline = {
        "dungeons": [
            {
                "id": "risky_dungeon",
                "name": "版本副本",
                "server_day": 3,
                "requirements": {"困难": 100_000_000},
                "status": "confirmed_with_version_risk",
            }
        ]
    }

    reminders = build_reminders(
        timeline,
        today=date(2026, 1, 1),
        open_date=date(2026, 1, 1),
        remind_days_before=[2],
    )

    assert len(reminders) == 1
    message = format_reminder(reminders[0])
    assert "1亿" in message
    assert "版本风险" not in message


def test_pending_event_is_skipped_but_pending_formal_power_dungeon_is_not() -> None:
    timeline = {
        "dungeons": [
            {
                "id": "pending_power",
                "name": "副本",
                "server_day": 3,
                "status": "pending_formal_power",
            }
        ],
        "events": [
            {
                "id": "pending_event",
                "name": "待确认事件",
                "server_day": 3,
                "status": "pending",
            }
        ],
    }

    reminders = build_reminders(
        timeline,
        today=date(2026, 1, 1),
        open_date=date(2026, 1, 1),
        remind_days_before=[2],
    )

    assert [reminder.event_id for reminder in reminders] == ["pending_power"]


def test_secret_treasure_includes_confirmed_reward_for_known_phase() -> None:
    timeline = {
        "activity_rules": {
            "secret_treasure_battle": {
                "known_phases": [
                    {
                        "phase": 11,
                        "server_day": 78,
                        "name": "秘宝大作战·第11期",
                        "featured_reward": {
                            "name": "自选4阶技能碎片",
                            "amount": 180,
                            "status": "confirmed",
                        },
                        "status": "confirmed",
                    }
                ]
            }
        }
    }

    reminders = build_reminders(
        timeline,
        today=date(2026, 3, 17),
        open_date=date(2026, 1, 1),
        remind_days_before=[2],
    )

    assert len(reminders) == 1
    message = format_reminder(reminders[0])
    assert reminders[0].event_id == "secret_treasure_11"
    assert "重点奖励：\n自选4阶技能碎片 ×180" in message
    assert "当前服务器进度：开服第 76 天" in message


def test_weekly_side_activity_uses_target_server_day() -> None:
    timeline = {
        "activity_rules": {
            "weekly_side_activity_rotation": {
                "first_server_day": 15,
                "period_days": 7,
                "rotation": ["宾果抽抽乐", "幸运刮刮乐"],
            }
        }
    }

    reminders = build_reminders(
        timeline,
        today=date(2026, 1, 13),
        open_date=date(2026, 1, 1),
        remind_days_before=[2],
    )

    assert len(reminders) == 1
    assert reminders[0].name == "宾果抽抽乐"
    assert reminders[0].event_date == date(2026, 1, 15)


def test_season_day_uses_configured_anchor_when_server_day_is_absent() -> None:
    timeline = {
        "events": [
            {
                "id": "s4_test",
                "season": "S4",
                "season_day": 3,
                "name": "S4 测试事件",
                "status": "confirmed",
            }
        ]
    }

    reminders = build_reminders(
        timeline,
        today=date(2026, 2, 1),
        open_date=None,
        season_anchor_dates={"S4": date(2026, 2, 1)},
        remind_days_before=[2],
    )

    assert len(reminders) == 1
    assert reminders[0].event_date == date(2026, 2, 3)
    assert "当前服务器进度" not in format_reminder(reminders[0])


def test_later_season_anchor_takes_priority_over_observed_server_day() -> None:
    event = {
        "season": "S4",
        "season_day": 3,
        "server_day": 200,
        "name": "S4 测试事件",
    }

    assert calculate_event_date(
        event,
        date(2026, 1, 1),
        {"S4": date(2026, 2, 1)},
    ) == date(2026, 2, 3)


def test_notification_key_includes_event_date() -> None:
    first = make_notification_key("event", date(2026, 1, 3), 2)
    moved = make_notification_key("event", date(2026, 1, 4), 2)
    different_reminder = make_notification_key("event", date(2026, 1, 3), 1)

    assert first != moved
    assert first != different_reminder


def test_actual_timeline_contains_expected_confirmed_entries() -> None:
    timeline = load_timeline("timeline_v1.json")
    qingyun = next(
        item for item in timeline["dungeons"] if item["id"] == "qingyun_temple"
    )
    phase_11 = next(
        item
        for item in timeline["activity_rules"]["secret_treasure_battle"]["known_phases"]
        if item["phase"] == 11
    )

    assert qingyun["requirements"]["普通"] == 6_200_000
    assert qingyun["status"] == "confirmed"
    assert phase_11["featured_reward"]["name"] == "自选4阶技能碎片"


def test_power_format_uses_readable_units() -> None:
    assert format_power(36_000) == "3.6万"
    assert format_power(100_000_000) == "1亿"
