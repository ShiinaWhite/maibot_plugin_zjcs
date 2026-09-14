from timeline import audit_timeline_integrity, load_timeline


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
