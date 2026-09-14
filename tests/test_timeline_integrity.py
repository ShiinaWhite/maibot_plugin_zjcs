from datetime import date

from timeline import audit_timeline_integrity, calculate_event_date, load_timeline


def _timeline_with_event(event: dict) -> dict:
    return {"events": [event]}


def test_real_timeline_passes_integrity_audit() -> None:
    timeline = load_timeline("timeline_v1.json")

    assert audit_timeline_integrity(timeline) == []


def test_audit_detects_duplicate_event_id() -> None:
    timeline = {
        "events": [
            {
                "id": "same_id",
                "name": "事件一",
                "server_day": 10,
                "status": "confirmed",
            },
            {
                "id": "same_id",
                "name": "事件二",
                "server_day": 20,
                "status": "confirmed",
            },
        ]
    }

    issues = audit_timeline_integrity(timeline)

    assert any("same_id" in issue and "重复" in issue for issue in issues)


def test_audit_detects_cross_category_duplicate_id() -> None:
    timeline = {
        "dungeons": [
            {
                "id": "clash",
                "name": "副本",
                "server_day": 10,
                "status": "confirmed",
            }
        ],
        "events": [
            {
                "id": "clash",
                "name": "事件",
                "server_day": 20,
                "status": "confirmed",
            }
        ],
    }

    issues = audit_timeline_integrity(timeline)

    assert any("clash" in issue and "重复" in issue for issue in issues)


def test_audit_detects_reserved_generated_prefix() -> None:
    timeline = {
        "events": [
            {
                "id": "secret_treasure_custom",
                "name": "保留前缀事件",
                "server_day": 10,
                "status": "confirmed",
            }
        ]
    }

    issues = audit_timeline_integrity(timeline)

    assert any("保留前缀" in issue for issue in issues)


def test_audit_detects_unregistered_source_key() -> None:
    timeline = {
        "events": [
            {
                "id": "with_bad_source",
                "name": "坏来源事件",
                "event_date": "2026-09-24",
                "status": "confirmed",
                "sources": ["does_not_exist"],
            }
        ]
    }

    issues = audit_timeline_integrity(timeline)

    assert any("does_not_exist" in issue for issue in issues)


def test_audit_allows_empty_sources_but_rejects_malformed() -> None:
    empty = {
        "events": [
            {
                "id": "no_sources",
                "name": "无来源事件",
                "event_date": "2026-09-24",
                "status": "confirmed",
            }
        ]
    }
    malformed = {
        "events": [
            {
                "id": "bad_sources",
                "name": "坏格式事件",
                "event_date": "2026-09-24",
                "status": "confirmed",
                "sources": "not-a-list",
            }
        ]
    }

    assert audit_timeline_integrity(empty) == []
    issues = audit_timeline_integrity(malformed)
    assert any("sources 必须是字符串数组" in issue for issue in issues)


def test_audit_flags_ambiguous_and_invalid_date_models() -> None:
    ambiguous = {
        "events": [
            {
                "id": "mixed",
                "name": "混写事件",
                "event_date": "2026-09-24",
                "server_day": 10,
                "status": "confirmed",
            }
        ]
    }
    invalid_date = {
        "events": [
            {
                "id": "bad_iso",
                "name": "非法日期事件",
                "event_date": "2026-13-99",
                "status": "confirmed",
            }
        ]
    }
    missing_model = {
        "events": [{"id": "no_date", "name": "无日期事件", "status": "confirmed"}]
    }
    season_day_without_season = {
        "events": [
            {
                "id": "season_day_only",
                "name": "缺赛季事件",
                "season_day": 3,
                "status": "confirmed",
            }
        ]
    }

    assert len(audit_timeline_integrity(ambiguous)) == 1
    assert len(audit_timeline_integrity(invalid_date)) == 1
    assert len(audit_timeline_integrity(missing_model)) == 1
    assert len(audit_timeline_integrity(season_day_without_season)) == 1


def test_audit_accepts_server_day_with_season_metadata() -> None:
    timeline = {
        "events": [
            {
                "id": "meta_event",
                "name": "带赛季元数据的事件",
                "season": "S2",
                "server_day": 10,
                "status": "confirmed",
            }
        ]
    }

    assert audit_timeline_integrity(timeline) == []


def test_audit_detects_duplicate_treasure_phase_number() -> None:
    timeline = {
        "activity_rules": {
            "secret_treasure_battle": {
                "first_server_day": 8,
                "period_days": 7,
                "known_phases": [
                    {"phase": 1, "server_day": 8, "status": "confirmed"},
                    {"phase": 1, "server_day": 15, "status": "confirmed"},
                ],
            }
        }
    }

    issues = audit_timeline_integrity(timeline)

    assert any("phase 1 与" in issue and "重复" in issue for issue in issues)


def test_audit_detects_duplicate_explicit_treasure_server_day() -> None:
    timeline = {
        "activity_rules": {
            "secret_treasure_battle": {
                "first_server_day": 8,
                "period_days": 7,
                "known_phases": [
                    {"phase": 1, "server_day": 8, "status": "confirmed"},
                    {"phase": 2, "server_day": 8, "status": "confirmed"},
                ],
            }
        }
    }

    issues = audit_timeline_integrity(timeline)

    assert any("server_day 8" in issue and "重复" in issue for issue in issues)


def test_audit_detects_notifiable_phase_without_reward_name() -> None:
    timeline = {
        "activity_rules": {
            "secret_treasure_battle": {
                "first_server_day": 8,
                "period_days": 7,
                "known_phases": [
                    {
                        "phase": 1,
                        "server_day": 8,
                        "status": "confirmed",
                        "featured_reward": {"status": "confirmed"},
                    }
                ],
            }
        }
    }

    issues = audit_timeline_integrity(timeline)

    assert any("featured_reward.name" in issue for issue in issues)


def test_audit_tolerates_pending_reward_without_name() -> None:
    timeline = {
        "activity_rules": {
            "secret_treasure_battle": {
                "first_server_day": 8,
                "period_days": 7,
                "known_phases": [
                    {
                        "phase": 1,
                        "server_day": 8,
                        "status": "confirmed",
                        "featured_reward": {"status": "pending"},
                    }
                ],
            }
        }
    }

    issues = audit_timeline_integrity(timeline)

    assert issues == []


def test_audit_detects_broken_fallback_rule() -> None:
    timeline = {
        "activity_rules": {
            "secret_treasure_battle": {
                "first_server_day": 8,
                "period_days": 7,
                "post_phase_16_rule": {
                    "status": "rule_confirmed_reward_detail_dynamic",
                    "pattern_categories": [],
                },
            }
        }
    }

    issues = audit_timeline_integrity(timeline)

    assert any("pattern_categories" in issue for issue in issues)


def test_audit_detects_malformed_weekly_rule() -> None:
    timeline = {
        "activity_rules": {
            "weekly_side_activity_rotation": {
                "first_server_day": 15,
                "period_days": 7,
                "rotation": [],
            }
        }
    }

    issues = audit_timeline_integrity(timeline)

    assert any("rotation" in issue for issue in issues)


def test_audit_detects_missing_name_and_status() -> None:
    timeline = {
        "events": [{"id": "broken", "server_day": 10, "status": "", "name": ""}]
    }

    issues = audit_timeline_integrity(timeline)

    assert any("name" in issue for issue in issues)
    assert any("status" in issue for issue in issues)


def test_audit_flags_present_but_invalid_server_day() -> None:
    for bad_server_day in ("92", 0, True):
        event = {
            "id": "mixed_invalid",
            "name": "混写非法事件",
            "event_date": "2026-09-24",
            "status": "confirmed",
            "server_day": bad_server_day,
        }
        timeline = _timeline_with_event(dict(event))

        issues = audit_timeline_integrity(timeline)
        assert issues, f"server_day={bad_server_day!r} 应产生 audit issue"
        assert calculate_event_date(dict(event), date(2026, 6, 19), {}) is None, (
            f"server_day={bad_server_day!r} 应 fail closed"
        )


def test_treasure_audit_flags_invalid_explicit_server_day() -> None:
    for bad_server_day in ("92", 0, True):
        timeline = {
            "activity_rules": {
                "secret_treasure_battle": {
                    "first_server_day": 8,
                    "period_days": 7,
                    "known_phases": [
                        {
                            "phase": 1,
                            "server_day": bad_server_day,
                            "status": "confirmed",
                        }
                    ],
                }
            }
        }

        issues = audit_timeline_integrity(timeline)

        assert any("server_day 如果存在必须是正整数" in issue for issue in issues), (
            f"server_day={bad_server_day!r} 应产生 audit issue"
        )


def test_treasure_audit_allows_absent_explicit_server_day() -> None:
    timeline = {
        "activity_rules": {
            "secret_treasure_battle": {
                "first_server_day": 8,
                "period_days": 7,
                "known_phases": [
                    {"phase": 1, "status": "confirmed"},
                ],
            }
        }
    }

    treasure_issues = [
        issue for issue in audit_timeline_integrity(timeline) if "server_day" in issue
    ]

    assert treasure_issues == []


def test_explicit_null_carriers_fail_closed() -> None:
    from timeline import calculate_event_date

    for null_carrier in ({"server_day": None}, {"season_day": None}):
        event = {
            "id": "null_carrier",
            "name": "空载体事件",
            "event_date": "2026-09-24",
            "status": "confirmed",
            **null_carrier,
        }
        timeline = _timeline_with_event(dict(event))

        assert calculate_event_date(dict(event), date(2026, 6, 19), {}) is None, (
            f"{null_carrier} 应 fail closed"
        )
        assert audit_timeline_integrity(timeline), f"{null_carrier} 应产生 audit issue"


def test_audit_reward_integrity_not_bound_to_server_day_branch() -> None:
    # 公式期次（无 server_day）+ confirmed/confirmed 但 reward name 为空
    # → audit 必须报 issue，不能被 server_day 分支的 continue 意外跳过。
    timeline = {
        "activity_rules": {
            "secret_treasure_battle": {
                "first_server_day": 8,
                "period_days": 7,
                "known_phases": [
                    {
                        "phase": 3,
                        "status": "confirmed",
                        "featured_reward": {"status": "confirmed"},
                    }
                ],
            }
        }
    }

    issues = audit_timeline_integrity(timeline)

    assert any("featured_reward.name" in issue for issue in issues)

    # 对照：同样的 phase 带上合法 reward name → 无 issue。
    ok_phase = {
        "phase": 3,
        "status": "confirmed",
        "featured_reward": {"name": "合法奖励", "status": "confirmed"},
    }
    timeline["activity_rules"]["secret_treasure_battle"]["known_phases"] = [ok_phase]

    assert audit_timeline_integrity(timeline) == []
