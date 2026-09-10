from datetime import date, timedelta

import pytest

from timeline import (
    Reminder,
    ReminderPolicy,
    build_reminders,
    calculate_event_date,
    format_power,
    format_daily_reminders,
    format_relative_day,
    format_reminder,
    load_timeline,
    make_notification_key,
    validate_remind_day,
)


def two_day_policy() -> ReminderPolicy:
    return ReminderPolicy(
        dungeon=2,
        secret_treasure=2,
        bingo=2,
        scratch=2,
        fenek=2,
        event=2,
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
        reminder_policy=two_day_policy(),
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
        reminder_policy=two_day_policy(),
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
        reminder_policy=two_day_policy(),
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
        reminder_policy=two_day_policy(),
    )

    assert [reminder.event_id for reminder in reminders] == ["pending_power"]


def test_secret_treasure_includes_confirmed_reward_for_known_phase() -> None:
    timeline = {
        "activity_rules": {
            "secret_treasure_battle": {
                "first_server_day": 8,
                "period_days": 7,
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
                ],
            }
        }
    }

    reminders = build_reminders(
        timeline,
        today=date(2026, 3, 17),
        open_date=date(2026, 1, 1),
        reminder_policy=two_day_policy(),
    )

    assert len(reminders) == 1
    message = format_reminder(reminders[0])
    assert reminders[0].event_id == "secret_treasure_11"
    assert "重点奖励：\n自选4阶技能碎片 ×180" in message
    assert "当前服务器进度：开服第 76 天" in message


def test_secret_treasure_phase_17_falls_back_to_confirmed_category_rule() -> None:
    open_date = date(2026, 1, 1)
    timeline = {
        "activity_rules": {
            "secret_treasure_battle": {
                "first_server_day": 8,
                "period_days": 7,
                "known_phases": [],
                "post_phase_16_rule": {
                    "status": "rule_confirmed_reward_detail_dynamic",
                    "pattern_categories": [
                        "自选当期奇迹遗物箱",
                        "自选特殊遗物箱Ⅰ",
                        "自选当前转职阶技能碎片×180",
                        "自选特殊遗物箱Ⅱ",
                    ],
                },
            }
        }
    }

    reminders = build_reminders(
        timeline,
        today=open_date + timedelta(days=117),
        open_date=open_date,
        reminder_policy=two_day_policy(),
    )

    assert len(reminders) == 1
    reminder = reminders[0]
    assert reminder.event_id == "secret_treasure_17"
    assert reminder.event_date == open_date + timedelta(days=119)
    assert reminder.payload["featured_reward_category"] == "自选当期奇迹遗物箱"
    message = format_reminder(reminder)
    assert "重点奖励类别：\n自选当期奇迹遗物箱" in message
    assert "重点奖励：\n" not in message

    assert (
        build_reminders(
            timeline,
            today=open_date + timedelta(days=118),
            open_date=open_date,
            reminder_policy=two_day_policy(),
        )
        == []
    )


def test_secret_treasure_explicit_future_phase_reward_takes_priority() -> None:
    open_date = date(2026, 1, 1)
    timeline = {
        "activity_rules": {
            "secret_treasure_battle": {
                "first_server_day": 8,
                "period_days": 7,
                "known_phases": [
                    {
                        "phase": 17,
                        "server_day": 120,
                        "name": "秘宝大作战·第17期",
                        "featured_reward": {
                            "name": "明确记录的第17期奖励",
                            "status": "confirmed",
                        },
                        "status": "confirmed",
                    }
                ],
                "post_phase_16_rule": {
                    "status": "rule_confirmed_reward_detail_dynamic",
                    "pattern_categories": ["不应使用的回退类别"],
                },
            }
        }
    }

    reminders = build_reminders(
        timeline,
        today=open_date + timedelta(days=117),
        open_date=open_date,
        reminder_policy=two_day_policy(),
    )

    assert len(reminders) == 1
    message = format_reminder(reminders[0])
    assert "重点奖励：\n明确记录的第17期奖励" in message
    assert "不应使用的回退类别" not in message


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
        reminder_policy=two_day_policy(),
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
        reminder_policy=two_day_policy(),
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


def test_later_season_requires_anchor_even_when_server_day_exists() -> None:
    event = {
        "id": "s4_without_anchor",
        "season": "S4",
        "season_day": 3,
        "server_day": 3,
        "name": "缺少锚点的 S4 事件",
        "status": "confirmed",
    }

    assert calculate_event_date(event, date(2026, 1, 1), {}) is None
    assert (
        build_reminders(
            {"events": [event]},
            today=date(2026, 1, 1),
            open_date=date(2026, 1, 1),
            season_anchor_dates={},
            reminder_policy=two_day_policy(),
        )
        == []
    )


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


def test_secret_treasure_explicit_server_day_overrides_formula() -> None:
    open_date = date(2026, 1, 1)
    timeline = {
        "activity_rules": {
            "secret_treasure_battle": {
                "first_server_day": 8,
                "period_days": 7,
                "known_phases": [
                    {
                        "phase": 2,
                        "server_day": 20,
                        "name": "秘宝大作战·第2期（调整）",
                        "featured_reward": {
                            "name": "显式日期奖励",
                            "status": "confirmed",
                        },
                        "status": "confirmed",
                    }
                ],
            }
        }
    }

    reminders = build_reminders(
        timeline,
        today=open_date + timedelta(days=17),
        open_date=open_date,
        reminder_policy=two_day_policy(),
    )

    assert len(reminders) == 1
    assert reminders[0].event_id == "secret_treasure_2"
    assert reminders[0].event_date == open_date + timedelta(days=19)
    assert (
        build_reminders(
            timeline,
            today=open_date + timedelta(days=12),
            open_date=open_date,
            reminder_policy=two_day_policy(),
        )
        == []
    )


@pytest.mark.parametrize(
    ("activity_name", "target_server_day", "policy_field", "days_before"),
    [
        ("宾果抽抽乐", 15, "bingo", 4),
        ("幸运刮刮乐", 22, "scratch", 3),
        ("菲涅克的谜题", 29, "fenek", 2),
    ],
)
def test_weekly_activities_use_their_own_policy(
    activity_name: str,
    target_server_day: int,
    policy_field: str,
    days_before: int,
) -> None:
    timeline = {
        "activity_rules": {
            "weekly_side_activity_rotation": {
                "first_server_day": 15,
                "period_days": 7,
                "rotation": ["宾果抽抽乐", "幸运刮刮乐", "菲涅克的谜题"],
            }
        }
    }
    policy_values = {
        "dungeon": 1,
        "secret_treasure": 1,
        "bingo": 1,
        "scratch": 1,
        "fenek": 1,
        "event": 1,
    }
    policy_values[policy_field] = days_before
    policy = ReminderPolicy(**policy_values)
    today = date(2026, 1, 1) + timedelta(days=target_server_day - days_before - 1)

    reminders = build_reminders(
        timeline,
        today=today,
        open_date=date(2026, 1, 1),
        reminder_policy=policy,
    )

    assert [reminder.name for reminder in reminders] == [activity_name]
    assert reminders[0].remind_days_before == days_before


def test_dungeon_and_event_use_independent_policies() -> None:
    timeline = {
        "dungeons": [
            {
                "id": "dungeon",
                "name": "测试副本",
                "server_day": 2,
                "status": "confirmed",
            }
        ],
        "events": [
            {
                "id": "event",
                "name": "测试事件",
                "server_day": 3,
                "status": "confirmed",
            }
        ],
    }
    policy = ReminderPolicy(dungeon=1, event=2)

    reminders = build_reminders(
        timeline,
        today=date(2026, 1, 1),
        open_date=date(2026, 1, 1),
        reminder_policy=policy,
    )

    assert [(item.event_id, item.remind_days_before) for item in reminders] == [
        ("dungeon", 1),
        ("event", 2),
    ]


def test_daily_format_merges_categories_and_groups_different_dates() -> None:
    reminders = [
        Reminder(
            event_id="event",
            category="event",
            name="未来事件",
            event_date=date(2026, 1, 5),
            remind_days_before=4,
            date_label="开放日期",
            payload={},
            current_server_day=1,
        ),
        Reminder(
            event_id="dungeon",
            category="dungeon",
            name="测试副本",
            event_date=date(2026, 1, 2),
            remind_days_before=1,
            date_label="开放日期",
            payload={"region": "测试区", "requirements": {"普通": 10_000}},
            current_server_day=1,
        ),
        Reminder(
            event_id="activity",
            category="activity",
            name="测试活动",
            event_date=date(2026, 1, 2),
            remind_days_before=1,
            date_label="开放日期",
            payload={},
            current_server_day=1,
        ),
    ]

    message = format_daily_reminders(reminders, today=date(2026, 1, 1))

    assert message.count("【杖剑传说 · 近期提醒】") == 1
    assert "每日提醒" not in message
    assert message.count("明日 · 2026-01-02") == 1
    assert message.count("4 天后 · 2026-01-05") == 1
    assert message.index("【副本】测试区 · 测试副本") < message.index(
        "【活动】测试活动"
    )
    assert "已确认准入战力：\n普通：1万" in message
    assert message.rstrip().endswith("当前服务器进度：开服第 1 天")


def test_format_relative_day_uses_colloquial_labels() -> None:
    assert format_relative_day(0) == "今天"
    assert format_relative_day(1) == "明天"
    assert format_relative_day(2) == "后天"
    assert format_relative_day(3) == "3天后"
    assert format_relative_day(10) == "10天后"


@pytest.mark.parametrize(
    ("days_before", "expected_hint"),
    [
        (1, "准备建议：今天开始攒副本次数。"),
        (2, "准备建议：明天开始攒副本次数。"),
        (3, "准备建议：后天开始攒副本次数。"),
        (4, "准备建议：3天后开始攒副本次数。"),
        (5, "准备建议：4天后开始攒副本次数。"),
    ],
)
def test_dungeon_preparation_hint_uses_relative_day_from_check_date(
    days_before: int, expected_hint: str
) -> None:
    open_date = date(2026, 1, 1)
    event_date = date(2026, 1, 4)
    today = event_date - timedelta(days=days_before)
    timeline = {
        "dungeons": [
            {
                "id": "hint_dungeon",
                "name": "古剑城",
                "region": "龙之国",
                "server_day": 4,
                "requirements": {"普通": 10_000_000},
                "status": "confirmed",
            }
        ]
    }

    reminders = build_reminders(
        timeline,
        today=today,
        open_date=open_date,
        reminder_policy=ReminderPolicy(dungeon=days_before),
    )
    message = format_daily_reminders(reminders, today=today)

    assert len(reminders) == 1
    assert reminders[0].event_date == event_date
    assert expected_hint in message
    assert "起攒副本次数" not in message


def test_bingo_activity_includes_fruit_preparation_hint() -> None:
    open_date = date(2026, 1, 1)
    today = date(2026, 1, 11)
    timeline = {
        "activity_rules": {
            "weekly_side_activity_rotation": {
                "first_server_day": 15,
                "period_days": 7,
                "rotation": ["宾果抽抽乐"],
            }
        }
    }

    reminders = build_reminders(
        timeline,
        today=today,
        open_date=open_date,
        reminder_policy=ReminderPolicy(bingo=4),
    )
    message = format_daily_reminders(reminders, today=today)

    assert [reminder.name for reminder in reminders] == ["宾果抽抽乐"]
    assert "准备建议：现在开始攒果子，活动开始前至少留20个。" in message


@pytest.mark.parametrize("activity_name", ["幸运刮刮乐", "菲涅克的谜题"])
def test_other_weekly_activities_have_no_preparation_hint(activity_name: str) -> None:
    open_date = date(2026, 1, 1)
    timeline = {
        "activity_rules": {
            "weekly_side_activity_rotation": {
                "first_server_day": 15,
                "period_days": 7,
                "rotation": ["宾果抽抽乐", "幸运刮刮乐", "菲涅克的谜题"],
            }
        }
    }
    if activity_name == "幸运刮刮乐":
        policy = ReminderPolicy(scratch=2)
        today = date(2026, 1, 20)
    else:
        policy = ReminderPolicy(fenek=2)
        today = date(2026, 1, 27)

    reminders = build_reminders(
        timeline,
        today=today,
        open_date=open_date,
        reminder_policy=policy,
    )
    message = format_daily_reminders(reminders, today=today)

    assert [reminder.name for reminder in reminders] == [activity_name]
    assert "准备建议" not in message
    assert "至少留20个" not in message


def test_merged_message_keeps_each_preparation_hint_in_its_own_block() -> None:
    open_date = date(2026, 1, 1)
    today = date(2026, 1, 12)
    timeline = {
        "dungeons": [
            {
                "id": "merged_dungeon",
                "name": "古剑城",
                "region": "龙之国",
                "server_day": 14,
                "requirements": {"普通": 10_000_000},
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
    }

    reminders = build_reminders(
        timeline,
        today=today,
        open_date=open_date,
        reminder_policy=ReminderPolicy(dungeon=2, bingo=4),
    )
    message = format_daily_reminders(reminders, today=today)

    assert [reminder.category for reminder in reminders] == ["dungeon", "activity"]
    assert message.count("【杖剑传说 · 近期提醒】") == 1
    assert "每日提醒" not in message
    assert message.index("2 天后 · 2026-01-14") < message.index("4 天后 · 2026-01-16")
    dungeon_hint_index = message.index("准备建议：明天开始攒副本次数。")
    assert message.index("【副本】龙之国 · 古剑城") < dungeon_hint_index
    assert dungeon_hint_index < message.index("4 天后 · 2026-01-16")
    bingo_hint_index = message.index("准备建议：现在开始攒果子，活动开始前至少留20个。")
    assert message.index("【活动】宾果抽抽乐") < bingo_hint_index


def test_preview_format_keeps_upcoming_title_and_preparation_hints() -> None:
    reminder = Reminder(
        event_id="preview_dungeon",
        category="dungeon",
        name="预览副本",
        event_date=date(2026, 1, 2),
        remind_days_before=1,
        date_label="开放日期",
        payload={"region": "预览区", "requirements": {"普通": 10_000}},
        current_server_day=1,
    )

    message = format_daily_reminders([reminder], today=date(2026, 1, 1), preview=True)

    assert message.startswith("【杖剑助手 · 今日提醒预览】")
    assert "仅供预览" in message
    assert "每日提醒" not in message
    assert "准备建议：今天开始攒副本次数。" in message


def test_validate_remind_day_accepts_zero_and_rejects_invalid() -> None:
    assert validate_remind_day(0, "dungeon_remind_day") == 0
    assert validate_remind_day(4) == 4

    for invalid in (-1, True, 1.5, "2", None):
        with pytest.raises(ValueError):
            validate_remind_day(invalid, "dungeon_remind_day")


def test_validated_policy_rejects_negative_day_as_runtime_defense() -> None:
    with pytest.raises(ValueError, match="dungeon_remind_day"):
        ReminderPolicy(dungeon=-1).validated()


def test_zero_policy_disables_all_categories() -> None:
    open_date = date(2026, 1, 1)
    timeline = {
        "dungeons": [
            {
                "id": "dungeon",
                "name": "测试副本",
                "server_day": 3,
                "status": "confirmed",
            }
        ],
        "events": [
            {
                "id": "event",
                "name": "测试事件",
                "server_day": 3,
                "status": "confirmed",
            }
        ],
        "activity_rules": {
            "secret_treasure_battle": {
                "first_server_day": 8,
                "period_days": 7,
                "known_phases": [
                    {
                        "phase": 1,
                        "server_day": 8,
                        "name": "秘宝大作战·第1期",
                        "featured_reward": {
                            "name": "测试奖励",
                            "status": "confirmed",
                        },
                        "status": "confirmed",
                    }
                ],
            },
            "weekly_side_activity_rotation": {
                "first_server_day": 2,
                "period_days": 7,
                "rotation": ["宾果抽抽乐", "幸运刮刮乐", "菲涅克的谜题"],
            },
        },
    }
    disabled_policy = ReminderPolicy(
        dungeon=0,
        secret_treasure=0,
        bingo=0,
        scratch=0,
        fenek=0,
        event=0,
    )

    # 秘宝第 1 期在第 8 天；提前 1 天应能生成，但 0 策略下全部关闭。
    enabled_day = open_date + timedelta(days=6)
    assert (
        len(
            build_reminders(
                timeline,
                today=enabled_day,
                open_date=open_date,
                reminder_policy=ReminderPolicy(
                    dungeon=0,
                    secret_treasure=1,
                    bingo=0,
                    scratch=0,
                    fenek=0,
                    event=0,
                ),
            )
        )
        == 1
    )
    assert (
        build_reminders(
            timeline,
            today=enabled_day,
            open_date=open_date,
            reminder_policy=disabled_policy,
        )
        == []
    )


def test_each_category_generates_at_most_one_reminder_day() -> None:
    open_date = date(2026, 1, 1)
    timeline = {
        "dungeons": [
            {
                "id": "dungeon",
                "name": "测试副本",
                "server_day": 3,
                "status": "confirmed",
            }
        ]
    }
    policy = two_day_policy()

    reminders = build_reminders(
        timeline,
        today=open_date,
        open_date=open_date,
        reminder_policy=policy,
    )
    assert [reminder.remind_days_before for reminder in reminders] == [2]

    # 旧列表语义下还差 1 天会再次提醒；单整数策略只允许一次。
    assert (
        build_reminders(
            timeline,
            today=open_date + timedelta(days=1),
            open_date=open_date,
            reminder_policy=policy,
        )
        == []
    )


def test_weekly_activity_zero_policy_skips_that_activity() -> None:
    open_date = date(2026, 1, 1)
    timeline = {
        "activity_rules": {
            "weekly_side_activity_rotation": {
                "first_server_day": 15,
                "period_days": 7,
                "rotation": ["宾果抽抽乐", "幸运刮刮乐", "菲涅克的谜题"],
            }
        }
    }
    policy = ReminderPolicy(
        dungeon=0,
        secret_treasure=0,
        bingo=0,
        scratch=2,
        fenek=0,
        event=0,
    )

    # 开服第 15 天轮到宾果，但宾果策略为 0，不生成提醒。
    assert (
        build_reminders(
            timeline,
            today=date(2026, 1, 13),
            open_date=open_date,
            reminder_policy=policy,
        )
        == []
    )

    # 第 22 天轮到幸运刮刮乐，提前 2 天提醒。
    reminders = build_reminders(
        timeline,
        today=date(2026, 1, 20),
        open_date=open_date,
        reminder_policy=policy,
    )
    assert [reminder.name for reminder in reminders] == ["幸运刮刮乐"]
    assert reminders[0].remind_days_before == 2
    assert reminders[0].event_date == date(2026, 1, 22)
