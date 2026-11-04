"""S3 羽之国剩余时间线校准回归（2026-11-04 运营者截图第一事实来源）。

覆盖本轮截图校准的验收矩阵：战渊堡垒/净化之庭/君临之巢门槛修正、
秩序神殿/烈阳尖塔不漂移、遗物池与奇迹幻兽正式名称、Day141～204
每周轮换期数、第20～29期秘宝显式事实（第22期保持 fallback）、
君临之巢深渊延迟解锁语义、Day207 预计双倍 BUFF 的 estimated 隔离。
"""

from datetime import date, timedelta

import pytest

from timeline import (
    NOTIFIABLE_STATUSES,
    audit_timeline_integrity,
    build_query_facts,
    build_reminders,
    build_secret_treasure_overview,
    build_server_progress,
    build_upcoming_schedule,
    calculate_event_date,
    find_next_dungeon,
    format_daily_reminders,
    format_next_dungeon,
    format_secret_treasure_overview,
    load_timeline,
)

OPEN_DATE = date(2026, 6, 19)
PROD_TODAY = date(2026, 11, 4)  # 开服第 139 天（截图当天）


def _timeline() -> dict:
    return load_timeline("timeline_v1.json")


def _dungeon(timeline: dict, dungeon_id: str) -> dict:
    return next(item for item in timeline["dungeons"] if item["id"] == dungeon_id)


def _event(timeline: dict, event_id: str) -> dict:
    return next(item for item in timeline["events"] if item["id"] == event_id)


def _server_day(day: int) -> date:
    return OPEN_DATE + timedelta(days=day - 1)


def test_screenshot_source_is_registered_and_first_party() -> None:
    timeline = _timeline()

    source = timeline["sources"]["prod_timeline_screenshots_20261104"]
    assert source["kind"] == "server_timeline_screenshot"
    assert "estimated" in timeline["data_policy"]["statuses"]


def test_next_dungeon_on_prod_day139_is_war_abyss_fortress_with_calibrated_power():
    timeline = _timeline()

    entry = find_next_dungeon(timeline, today=PROD_TODAY, open_date=OPEN_DATE)

    assert entry is not None
    assert entry.name == "战渊堡垒"
    assert entry.event_date == date(2026, 11, 6)
    assert entry.payload["requirements"] == {
        "普通": 20_000_000,
        "困难": 26_000_000,
        "噩梦": 30_000_000,
        "炼狱": 46_000_000,
    }

    text = format_next_dungeon(entry, today=PROD_TODAY)
    assert "炼狱：4600万" in text
    assert "5200万" not in text


def test_purification_court_uses_calibrated_purgatory_power() -> None:
    timeline = _timeline()
    dungeon = _dungeon(timeline, "purification_court")

    assert dungeon["requirements"]["炼狱"] == 75_000_000
    assert "86000000" not in repr(dungeon["requirements"])
    assert calculate_event_date(dungeon, OPEN_DATE, {}) == date(2026, 11, 20)


def test_order_temple_and_blazing_sun_spire_do_not_drift() -> None:
    timeline = _timeline()

    assert _dungeon(timeline, "order_temple")["requirements"] == {
        "普通": 55_000_000,
        "困难": 65_000_000,
        "噩梦": 82_000_000,
        "炼狱": 115_000_000,
    }
    assert _dungeon(timeline, "blazing_sun_spire")["requirements"] == {
        "普通": 84_500_000,
        "困难": 100_000_000,
        "噩梦": 120_000_000,
        "炼狱": 180_000_000,
    }


def test_sovereign_nest_calibrated_with_delayed_deep_abyss() -> None:
    timeline = _timeline()
    dungeon = _dungeon(timeline, "sovereign_nest")

    assert dungeon["server_day"] == 197
    assert dungeon["requirements"]["普通"] == 125_000_000
    assert dungeon["requirements"]["困难"] == 145_000_000
    assert dungeon["requirements"]["噩梦"] == 180_000_000
    assert dungeon["requirements"]["炼狱"] == 250_000_000
    assert dungeon["requirements"]["深渊"] == 350_000_000
    assert dungeon["deep_abyss_server_day"] == 204

    entry_date = calculate_event_date(dungeon, OPEN_DATE, {})
    assert entry_date == date(2027, 1, 1)

    entries = build_upcoming_schedule(
        timeline, today=date(2026, 12, 30), open_date=OPEN_DATE
    )
    nest = next(entry for entry in entries if entry.name == "君临之巢")

    # 深渊门槛不得混入开放日常规 requirements。
    assert "深渊" not in nest.payload["requirements"]
    deep = nest.payload["deep_abyss"]
    assert deep["requirements"] == {"深渊": 350_000_000}
    assert deep["unlock_server_day"] == 204
    assert deep["unlock_date"] == "2027-01-08"
    assert deep["days_after_open"] == 7

    text = format_next_dungeon(nest, today=date(2026, 12, 30))
    assert "深渊：3.5亿（2027-01-08 · 副本开启 7 天后解锁）" in text
    # 开放日门槛列表中不得出现深渊。
    assert (
        "深渊：3.5亿\n"
        not in text.split("已确认准入战力：")[1].split("深渊：3.5亿（")[0]
    )


def test_sovereign_nest_facts_express_delayed_abyss_not_day197_access() -> None:
    timeline = _timeline()

    facts = build_query_facts(
        timeline, query="schedule", today=date(2026, 12, 30), open_date=OPEN_DATE
    )
    nest = next(
        entry for entry in facts["data"]["entries"] if entry["name"] == "君临之巢"
    )
    assert "深渊" not in nest["payload"]["requirements"]
    assert nest["payload"]["deep_abyss"]["unlock_date"] == "2027-01-08"
    assert nest["payload"]["deep_abyss"]["days_after_open"] == 7


def test_s5_origin_gate_keeps_season_based_deep_abyss_semantics() -> None:
    timeline = _timeline()
    dungeon = _dungeon(timeline, "origin_gate")

    assert dungeon["deep_abyss_season_day"] == 91
    entries = build_upcoming_schedule(
        timeline,
        today=date(2026, 3, 20),  # 起源之门 season_day 84 → 2026-03-24。
        open_date=OPEN_DATE,
        season_anchor_dates={"S5": date(2026, 1, 1)},
    )
    gate = next(entry for entry in entries if entry.name == "起源之门")
    assert "深渊" not in gate.payload["requirements"]
    assert gate.payload["deep_abyss"]["unlock_season_day"] == 91
    assert gate.payload["deep_abyss"]["unlock_date"] == "2026-04-01"
    assert gate.payload["deep_abyss"]["days_after_open"] == 7


def test_calibrated_event_names_keep_stable_ids() -> None:
    timeline = _timeline()

    relic_2 = _event(timeline, "feather_relic_2")
    assert relic_2["name"] == "羽2遗物池-天穹圣约"
    assert relic_2["server_day"] == 144
    assert calculate_event_date(relic_2, OPEN_DATE, {}) == date(2026, 11, 9)

    beast = _event(timeline, "rainbow_star_spirit")
    assert beast["name"] == "奇迹幻兽-虹彩星灵"
    assert beast["server_day"] == 159

    relic_3 = _event(timeline, "feather_relic_3")
    assert relic_3["name"] == "羽3遗物池-苍辉古律"
    assert relic_3["server_day"] == 174
    assert calculate_event_date(relic_3, OPEN_DATE, {}) == date(2026, 12, 9)


def test_s3_pilgrimage_tokens_recorded_from_screenshots() -> None:
    timeline = _timeline()
    expected = {
        "pilgrimage_feather2_crimson_core": (
            141,
            "巡礼之证：羽2-赤红晶石（火亲和+攻击）",
        ),
        "pilgrimage_feather2_blue_moon_pendant": (
            155,
            "巡礼之证：羽2-蓝月吊坠（水亲和+防御）",
        ),
        "pilgrimage_feather3_glory_star_emblem": (
            169,
            "巡礼之证：羽3-荣耀星徽（光庇护+生命）",
        ),
        "pilgrimage_feather3_thousand_bird_knuckle": (
            183,
            "巡礼之证：羽3-千鸟指虎（风亲和+攻击）",
        ),
        "pilgrimage_feather3_eternal_fire_fang": (
            197,
            "巡礼之证：羽3-永火獠牙（火亲和+攻击）",
        ),
    }
    for event_id, (server_day, name) in expected.items():
        event = _event(timeline, event_id)
        assert event["type"] == "pilgrimage_token"
        assert event["status"] == "confirmed"
        assert event["server_day"] == server_day
        assert event["name"] == name

    entries = build_upcoming_schedule(
        timeline, today=date(2026, 11, 3), open_date=OPEN_DATE
    )
    names = {entry.name for entry in entries}
    assert "巡礼之证：羽2-赤红晶石（火亲和+攻击）" in names

    reminders = build_reminders(timeline, today=date(2026, 11, 4), open_date=OPEN_DATE)
    # Day 139 + event 默认提前 2 天 → Day 141 的赤红晶石进入提醒。
    assert any(item.name.startswith("巡礼之证：羽2-赤红晶石") for item in reminders)


def test_estimated_double_buff_is_inert_until_confirmed() -> None:
    timeline = _timeline()
    event = _event(timeline, "unicom_double_buff")

    assert event["status"] == "estimated"
    assert event["status"] not in NOTIFIABLE_STATUSES
    assert event["event_date"] == "2027-01-11"
    assert "【预计】" in event["name"]
    # 保留来源与不确定性说明，不以确定口吻推送。
    assert "不参与任何自动提醒" in event["notes"]

    for today in (date(2027, 1, 5), date(2027, 1, 9), date(2027, 1, 11)):
        reminders = build_reminders(timeline, today=today, open_date=OPEN_DATE)
        assert all(item.event_id != "unicom_double_buff" for item in reminders)

        entries = build_upcoming_schedule(timeline, today=today, open_date=OPEN_DATE)
        assert all(entry.event_id != "unicom_double_buff" for entry in entries)

        progress = build_server_progress(timeline, today=today, open_date=OPEN_DATE)
        nodes = [progress.recent_node, progress.next_node]
        assert all(
            node is None or node.event_id != "unicom_double_buff" for node in nodes
        )


def test_weekly_rotation_day141_to_204_matches_screenshot_phases() -> None:
    timeline = _timeline()
    expected = {
        141: "宾果抽抽乐",
        148: "幸运刮刮乐",
        155: "菲涅克的谜题",
        162: "宾果抽抽乐",
        169: "幸运刮刮乐",
        176: "菲涅克的谜题",
        183: "宾果抽抽乐",
        190: "幸运刮刮乐",
        197: "菲涅克的谜题",
        204: "宾果抽抽乐",
    }
    for server_day, name in expected.items():
        entries = build_upcoming_schedule(
            timeline, today=_server_day(server_day), open_date=OPEN_DATE
        )
        weekly = [
            entry
            for entry in entries
            if entry.payload.get("type") == "weekly_side_activity"
            and entry.event_date == _server_day(server_day)
        ]
        assert len(weekly) == 1
        assert weekly[0].name == name


def test_treasure_phases_20_to_29_explicit_except_22() -> None:
    timeline = _timeline()
    phases = {
        phase["phase"]: phase
        for phase in timeline["activity_rules"]["secret_treasure_battle"][
            "known_phases"
        ]
    }
    assert 22 not in phases  # 截图未完整显示，保持规则级 fallback，不猜。

    expected_singles = {
        21: ("自选奇迹遗物箱·羽II", 148),
        23: ("自选5阶技能碎片", 162),
        25: ("自选奇迹遗物箱·羽III", 176),
        27: ("自选5阶技能碎片", 190),
        29: ("自选奇迹遗物箱·羽III", 204),
    }
    for phase_number, (name, server_day) in expected_singles.items():
        phase = phases[phase_number]
        assert phase["featured_reward"]["name"] == name
        assert phase["featured_reward"]["status"] == "confirmed"
        assert phase["server_day"] == server_day
        assert "featured_rewards" not in phase

    for phase_number in (20, 24, 26, 28):
        phase = phases[phase_number]
        rewards = phase["featured_rewards"]
        assert len(rewards) == 2
        assert all(reward["status"] == "confirmed" for reward in rewards)

    assert [reward["name"] for reward in phases[26]["featured_rewards"]] == [
        "幸运神像-翻倍",
        "黄金神木-木材",
    ]
    assert [reward["name"] for reward in phases[20]["featured_rewards"]] == [
        "原初宝石-宝石",
        "贤者之石-石块",
    ]
    assert phases[23]["featured_reward"]["amount"] == 180


def test_treasure_overview_day139_next_phase20_renders_dual_rewards() -> None:
    timeline = _timeline()

    overview = build_secret_treasure_overview(
        timeline, today=PROD_TODAY, open_date=OPEN_DATE
    )
    assert overview.current_server_day == 139
    assert overview.current_phase is not None
    assert overview.current_phase.phase == 19
    assert overview.current_phase.reward_mode == "rule_fallback"
    assert overview.next_phase is not None
    assert overview.next_phase.phase == 20
    assert overview.next_phase.reward_mode == "explicit"

    text = format_secret_treasure_overview(overview)
    assert "秘宝大作战·第20期" in text
    assert "重点奖励：原初宝石-宝石 ｜ 贤者之石-石块" in text


def test_treasure_phase22_stays_rule_fallback() -> None:
    timeline = _timeline()

    overview = build_secret_treasure_overview(
        timeline, today=_server_day(155), open_date=OPEN_DATE
    )
    assert overview.current_phase is not None
    assert overview.current_phase.phase == 22
    assert overview.current_phase.reward_mode == "rule_fallback"
    assert "featured_reward" not in overview.current_phase.payload

    text = format_secret_treasure_overview(overview)
    assert "重点奖励类别：自选特殊遗物箱Ⅰ（幸运神像/黄金神木/后续新增同类）" in text


def test_day141_full_schedule_matches_screenshot_content() -> None:
    timeline = _timeline()

    entries = build_upcoming_schedule(
        timeline, today=_server_day(141), open_date=OPEN_DATE
    )
    by_name = {entry.name: entry for entry in entries}

    fortress = by_name["战渊堡垒"]
    assert fortress.payload["requirements"]["炼狱"] == 46_000_000
    assert "秘宝大作战·第20期" in by_name
    assert "宾果抽抽乐" in by_name
    assert "巡礼之证：羽2-赤红晶石（火亲和+攻击）" in by_name


def test_real_timeline_audit_stays_clean() -> None:
    assert audit_timeline_integrity(_timeline()) == []


def test_audit_flags_invalid_deep_abyss_fields() -> None:
    base = {
        "id": "deep_bad",
        "name": "深渊副本",
        "server_day": 100,
        "status": "confirmed",
        "requirements": {"普通": 1},
    }

    invalid_value = {**base, "deep_abyss_server_day": True}
    mixed = {
        **base,
        "deep_abyss_server_day": 107,
        "deep_abyss_season_day": 7,
        "season": "S5",
        "season_day": 84,
    }
    not_after = {**base, "deep_abyss_server_day": 100}

    issues = "\n".join(audit_timeline_integrity({"dungeons": [invalid_value]}))
    assert "deep_abyss_server_day 如果存在必须是正整数" in issues
    issues = "\n".join(audit_timeline_integrity({"dungeons": [mixed]}))
    assert "不得混写" in issues
    issues = "\n".join(audit_timeline_integrity({"dungeons": [not_after]}))
    assert "必须晚于副本开放 server_day" in issues

    # 合法字段不产生 issue。
    ok = {
        **base,
        "deep_abyss_server_day": 107,
        "requirements": {"普通": 1, "深渊": 2},
    }
    assert audit_timeline_integrity({"dungeons": [ok]}) == []


def test_multi_reward_phase_fails_closed_without_leaking_names() -> None:
    from timeline import build_secret_treasure_overview

    def _timeline_with(phase: dict) -> dict:
        return {
            "activity_rules": {
                "secret_treasure_battle": {
                    "first_server_day": 8,
                    "period_days": 7,
                    "known_phases": [phase],
                }
            }
        }

    today = date(2026, 6, 26)  # Day 8：第一期当期。

    # 非法 featured_rewards（status 不可通知）→ unavailable，且不泄漏名称。
    pending = {
        "phase": 1,
        "server_day": 8,
        "name": "秘宝大作战·第1期",
        "status": "confirmed",
        "featured_rewards": [
            {"name": "测试服奖励A", "status": "confirmed"},
            {"name": "测试服奖励B", "status": "pending"},
        ],
    }
    overview = build_secret_treasure_overview(
        _timeline_with(pending), today=today, open_date=OPEN_DATE
    )
    assert overview.current_phase is not None
    assert overview.current_phase.reward_mode == "unavailable"
    assert "测试服奖励" not in format_secret_treasure_overview(overview)

    # featured_reward 与 featured_rewards 混写 → audit issue 且 fail closed。
    mixed = {
        "phase": 1,
        "server_day": 8,
        "status": "confirmed",
        "featured_reward": {"name": "单一奖励", "status": "confirmed"},
        "featured_rewards": [{"name": "奖励A", "status": "confirmed"}],
    }
    issues = "\n".join(audit_timeline_integrity(_timeline_with(mixed)))
    assert "不得混写" in issues
    overview = build_secret_treasure_overview(
        _timeline_with(mixed), today=today, open_date=OPEN_DATE
    )
    assert overview.current_phase is not None
    assert overview.current_phase.reward_mode == "unavailable"

    # 空 featured_rewards → audit issue 且 fail closed。
    empty = {
        "phase": 1,
        "server_day": 8,
        "status": "confirmed",
        "featured_rewards": [],
    }
    issues = "\n".join(audit_timeline_integrity(_timeline_with(empty)))
    assert "featured_rewards 必须是非空数组" in issues


def _deep_abyss_case_timeline(deep_fields: dict) -> dict:
    """以君临之巢为模板构造带指定延迟深渊字段的独立副本数据。"""

    dungeon = {
        "id": "deep_case",
        "season": "S3",
        "region": "羽之国",
        "name": "延迟解锁测试副本",
        "server_day": 197,
        "status": "confirmed",
        "requirements": {
            "普通": 125_000_000,
            "困难": 145_000_000,
            "噩梦": 180_000_000,
            "炼狱": 250_000_000,
            "深渊": 350_000_000,
        },
    }
    dungeon.update(deep_fields)
    return {"dungeons": [dungeon]}


@pytest.mark.parametrize(
    ("case_id", "deep_fields"),
    [
        ("mixed_carriers", {"deep_abyss_server_day": 204, "deep_abyss_season_day": 91}),
        ("invalid_bool", {"deep_abyss_server_day": True}),
        ("invalid_string", {"deep_abyss_server_day": "204"}),
        ("invalid_zero", {"deep_abyss_server_day": 0}),
        ("not_after_open", {"deep_abyss_server_day": 197}),
        ("before_open", {"deep_abyss_server_day": 150}),
    ],
)
def test_broken_deep_abyss_fails_closed_everywhere(
    case_id: str, deep_fields: dict
) -> None:
    """延迟深渊配置损坏时，任何出口都不得把它当成开放日普通门槛。

    不变量：只要数据声称“深渊是延迟解锁难度”，即使延迟字段坏掉，
    也绝不能退化成“深渊与普通难度同日开放”。
    """

    timeline = _deep_abyss_case_timeline(deep_fields)
    today = date(2026, 12, 30)  # Day 195：副本尚未开放。

    # audit 必须报错。
    assert audit_timeline_integrity(timeline), case_id

    # /副本 与 next_dungeon facts：深渊不进普通 requirements，无延迟行。
    entry = find_next_dungeon(timeline, today=today, open_date=OPEN_DATE)
    assert entry is not None
    assert "深渊" not in entry.payload["requirements"]
    assert "deep_abyss" not in entry.payload
    assert "深渊：" not in format_next_dungeon(entry, today=today)

    facts = build_query_facts(
        timeline, query="next_dungeon", today=today, open_date=OPEN_DATE
    )
    assert facts["status"] == "ok"
    assert "深渊" not in facts["data"]["payload"]["requirements"]
    assert "deep_abyss" not in facts["data"]["payload"]

    # schedule 与 reminder 同样不得暴露深渊门槛或延迟行。
    schedule = build_upcoming_schedule(timeline, today=today, open_date=OPEN_DATE)
    assert len(schedule) == 1
    assert "深渊" not in schedule[0].payload["requirements"]
    assert "deep_abyss" not in schedule[0].payload

    remind_today = date(2026, 12, 31)  # Day 196：默认提前 1 天提醒。
    reminders = build_reminders(timeline, today=remind_today, open_date=OPEN_DATE)
    assert len(reminders) == 1
    assert "深渊" not in reminders[0].payload["requirements"]
    assert "deep_abyss" not in reminders[0].payload
    daily_text = format_daily_reminders(reminders, today=remind_today)
    assert "深渊：" not in daily_text


def test_valid_deep_abyss_case_still_renders_delayed_unlock() -> None:
    """对照：同一模板上的合法配置仍完整表达延迟语义，不受 broken 分支影响。"""

    timeline = _deep_abyss_case_timeline({"deep_abyss_server_day": 204})
    today = date(2026, 12, 30)

    assert audit_timeline_integrity(timeline) == []
    entry = find_next_dungeon(timeline, today=today, open_date=OPEN_DATE)
    assert entry.payload["deep_abyss"]["unlock_server_day"] == 204
    assert entry.payload["deep_abyss"]["unlock_date"] == "2027-01-08"
    assert entry.payload["deep_abyss"]["days_after_open"] == 7
    assert "深渊" not in entry.payload["requirements"]
    assert "深渊：3.5亿（2027-01-08 · 副本开启 7 天后解锁）" in format_next_dungeon(
        entry, today=today
    )
