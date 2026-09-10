from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
import json
from pathlib import Path
from typing import Any


NOTIFIABLE_STATUSES = frozenset(
    {"confirmed", "confirmed_partial", "confirmed_with_version_risk"}
)
_CATEGORY_ORDER = {"dungeon": 0, "activity": 1, "event": 2}
WEEKLY_ACTIVITY_POLICY_NAMES = {
    "宾果抽抽乐": "bingo",
    "幸运刮刮乐": "scratch",
    "菲涅克的谜题": "fenek",
}
BINGO_PREPARATION_HINT = "准备建议：现在开始攒果子，活动开始前至少留20个。"


@dataclass(frozen=True)
class Reminder:
    event_id: str
    category: str
    name: str
    event_date: date
    remind_days_before: int
    date_label: str
    payload: Mapping[str, Any]
    current_server_day: int | None


@dataclass(frozen=True)
class ReminderPolicy:
    """每类内容提前提醒的天数；0 表示关闭该类别提醒。"""

    dungeon: int = 1
    secret_treasure: int = 2
    bingo: int = 4
    scratch: int = 2
    fenek: int = 2
    event: int = 2

    def validated(self) -> ReminderPolicy:
        return ReminderPolicy(
            dungeon=validate_remind_day(self.dungeon, "dungeon_remind_day"),
            secret_treasure=validate_remind_day(
                self.secret_treasure, "secret_treasure_remind_day"
            ),
            bingo=validate_remind_day(self.bingo, "bingo_remind_day"),
            scratch=validate_remind_day(self.scratch, "scratch_remind_day"),
            fenek=validate_remind_day(self.fenek, "fenek_remind_day"),
            event=validate_remind_day(self.event, "event_remind_day"),
        )

    def weekly_day(self, activity_name: str) -> int:
        policy_name = WEEKLY_ACTIVITY_POLICY_NAMES.get(activity_name)
        if policy_name is None:
            return 0
        return getattr(self, policy_name)


def load_timeline(path: str | Path) -> dict[str, Any]:
    timeline_path = Path(path)
    try:
        raw = json.loads(timeline_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取时间线数据：{timeline_path}") from exc

    if not isinstance(raw, dict):
        raise ValueError("时间线根节点必须是对象")
    return raw


def parse_iso_date(value: object, field_name: str) -> date:
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} 必须是 YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} 必须是 YYYY-MM-DD") from exc


def calculate_server_day(today: date, open_date: date) -> int:
    return (today - open_date).days + 1


def calculate_event_date(
    item: Mapping[str, Any],
    open_date: date | None,
    season_anchor_dates: Mapping[str, date],
) -> date | None:
    season_day = _positive_int(item.get("season_day"))
    season = item.get("season")
    anchor_date = (
        season_anchor_dates.get(season)
        if isinstance(season, str) and _is_later_season(season)
        else None
    )
    if season_day is not None and isinstance(season, str) and _is_later_season(season):
        if anchor_date is None:
            return None
        return anchor_date + timedelta(days=season_day - 1)

    server_day = _positive_int(item.get("server_day"))
    if server_day is not None and open_date is not None:
        return open_date + timedelta(days=server_day - 1)

    if season_day is None or not isinstance(season, str):
        return None
    anchor_date = season_anchor_dates.get(season)
    if anchor_date is None:
        return None
    return anchor_date + timedelta(days=season_day - 1)


def build_reminders(
    timeline: Mapping[str, Any],
    *,
    today: date,
    open_date: date | None,
    season_anchor_dates: Mapping[str, date] | None = None,
    reminder_policy: ReminderPolicy | None = None,
) -> list[Reminder]:
    anchors = season_anchor_dates or {}
    policy = (reminder_policy or ReminderPolicy()).validated()
    current_server_day = (
        calculate_server_day(today, open_date) if open_date is not None else None
    )
    reminders: list[Reminder] = []

    for raw_dungeon in _mapping_list(timeline.get("dungeons")):
        status = raw_dungeon.get("status")
        if status not in NOTIFIABLE_STATUSES and status != "pending_formal_power":
            continue
        reminder = _build_reminder(
            raw_dungeon,
            event_id=raw_dungeon.get("id"),
            category="dungeon",
            date_label="开放日期",
            today=today,
            open_date=open_date,
            season_anchor_dates=anchors,
            remind_day=policy.dungeon,
            current_server_day=current_server_day,
            payload={
                "region": raw_dungeon.get("region"),
                "requirements": _confirmed_requirements(raw_dungeon),
                "status": status,
            },
        )
        if reminder is not None:
            reminders.append(reminder)

    for raw_event in _mapping_list(timeline.get("events")):
        if raw_event.get("status") not in NOTIFIABLE_STATUSES:
            continue
        reminder = _build_reminder(
            raw_event,
            event_id=raw_event.get("id"),
            category="event",
            date_label="开放日期",
            today=today,
            open_date=open_date,
            season_anchor_dates=anchors,
            remind_day=policy.event,
            current_server_day=current_server_day,
            payload={"type": raw_event.get("type"), "status": raw_event.get("status")},
        )
        if reminder is not None:
            reminders.append(reminder)

    reminders.extend(
        _build_secret_treasure_reminders(
            timeline,
            open_date=open_date,
            remind_day=policy.secret_treasure,
            current_server_day=current_server_day,
        )
    )
    reminders.extend(
        _build_weekly_activity_reminders(
            timeline,
            today=today,
            open_date=open_date,
            reminder_policy=policy,
            current_server_day=current_server_day,
        )
    )

    return sorted(
        reminders,
        key=lambda item: (
            item.event_date,
            item.remind_days_before,
            _CATEGORY_ORDER.get(item.category, 99),
            item.event_id,
        ),
    )


def format_reminder(reminder: Reminder) -> str:
    remaining = reminder.remind_days_before
    if reminder.category == "dungeon":
        lines = ["【杖剑传说 · 副本提醒】", "", f"还有 {remaining} 天开放：", ""]
        region = reminder.payload.get("region")
        if isinstance(region, str) and region:
            lines.append(f"{region} · {reminder.name}")
        else:
            lines.append(reminder.name)

        requirements = reminder.payload.get("requirements")
        if isinstance(requirements, Mapping) and requirements:
            lines.extend(["", "已确认准入战力："])
            lines.extend(
                f"{label}：{format_power(power)}"
                for label, power in requirements.items()
            )
    elif reminder.category == "activity":
        lines = [
            "【杖剑传说 · 活动提醒】",
            "",
            f"还有 {remaining} 天：",
            "",
            reminder.name,
        ]
        reward = reminder.payload.get("featured_reward")
        if isinstance(reward, Mapping):
            reward_name = reward.get("name")
            if isinstance(reward_name, str) and reward_name:
                amount = reward.get("amount")
                reward_text = reward_name
                if amount is not None:
                    reward_text = f"{reward_text} ×{amount}"
                lines.extend(["", "重点奖励：", reward_text])
        else:
            reward_category = reminder.payload.get("featured_reward_category")
            if isinstance(reward_category, str) and reward_category:
                lines.extend(["", "重点奖励类别：", reward_category])
    else:
        lines = [
            "【杖剑传说 · 事件提醒】",
            "",
            f"还有 {remaining} 天：",
            "",
            reminder.name,
        ]

    lines.extend(["", f"{reminder.date_label}：{reminder.event_date.isoformat()}"])
    if reminder.current_server_day is not None:
        lines.append(f"当前服务器进度：开服第 {reminder.current_server_day} 天")
    return "\n".join(lines)


def format_daily_reminders(
    reminders: Iterable[Reminder],
    *,
    today: date,
    preview: bool = False,
) -> str:
    ordered = sorted(
        reminders,
        key=lambda item: (
            item.event_date,
            item.remind_days_before,
            _CATEGORY_ORDER.get(item.category, 99),
            item.event_id,
        ),
    )
    title = "【杖剑助手 · 今日提醒预览】" if preview else "【杖剑传说 · 近期提醒】"
    if not ordered:
        suffix = "\n\n今日没有符合当前提醒规则的内容。"
        if preview:
            suffix = "\n\n仅供预览，不会发送正式通知或写入提醒状态。" + suffix
        return title + suffix

    lines = [title]
    if preview:
        lines.extend(["", "仅供预览，不会发送正式通知或写入提醒状态。"])

    current_group: tuple[date, int] | None = None
    for reminder in ordered:
        group = (reminder.event_date, reminder.remind_days_before)
        if group != current_group:
            lines.extend(
                [
                    "",
                    f"{_relative_date_label(reminder.remind_days_before)} · "
                    f"{reminder.event_date.isoformat()}",
                ]
            )
            current_group = group

        lines.extend(["", _format_daily_reminder_item(reminder, today)])

    server_days = {
        reminder.current_server_day
        for reminder in ordered
        if reminder.current_server_day is not None
    }
    if len(server_days) == 1:
        lines.extend(["", f"当前服务器进度：开服第 {server_days.pop()} 天"])
    return "\n".join(lines)


def format_relative_day(days: int) -> str:
    """把距今天数格式化为中文相对时间：今天/明天/后天/N天后。"""

    if days == 0:
        return "今天"
    if days == 1:
        return "明天"
    if days == 2:
        return "后天"
    return f"{days}天后"


def make_notification_key(
    event_id: str,
    event_date: date,
    remind_days_before: int,
) -> str:
    return f"{event_id}:{event_date.isoformat()}:{remind_days_before}"


def format_power(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return str(value)

    decimal_value = Decimal(str(value))
    if decimal_value >= 100_000_000:
        return _format_decimal(decimal_value / Decimal(100_000_000), "亿")
    if decimal_value >= 10_000:
        return _format_decimal(decimal_value / Decimal(10_000), "万")
    return _format_decimal(decimal_value)


def _build_secret_treasure_reminders(
    timeline: Mapping[str, Any],
    *,
    open_date: date | None,
    remind_day: int,
    current_server_day: int | None,
) -> list[Reminder]:
    if open_date is None or current_server_day is None or remind_day <= 0:
        return []

    activity_rules = timeline.get("activity_rules")
    if not isinstance(activity_rules, Mapping):
        return []
    rule = activity_rules.get("secret_treasure_battle")
    if not isinstance(rule, Mapping):
        return []

    first_server_day = _positive_int(rule.get("first_server_day"))
    period_days = _positive_int(rule.get("period_days"))
    if first_server_day is None or period_days is None:
        return []

    explicit_phases = {
        phase_number: phase
        for phase in _mapping_list(rule.get("known_phases"))
        if (phase_number := _positive_int(phase.get("phase"))) is not None
    }
    fallback_categories = _secret_treasure_fallback_categories(rule)

    target_server_day = current_server_day + remind_day
    phase_number, phase = _secret_treasure_phase_for_server_day(
        explicit_phases,
        target_server_day=target_server_day,
        first_server_day=first_server_day,
        period_days=period_days,
    )
    if phase_number is None:
        return []
    name = f"秘宝大作战·第{phase_number}期"
    payload: dict[str, Any] = {"phase": phase_number}

    if phase is not None:
        phase_status = phase.get("status")
        reward = phase.get("featured_reward")
        if phase_status not in NOTIFIABLE_STATUSES or not isinstance(reward, Mapping):
            return []
        if reward.get("status") not in NOTIFIABLE_STATUSES:
            return []
        if not isinstance(reward.get("name"), str) or not reward["name"]:
            return []
        phase_name = phase.get("name")
        if isinstance(phase_name, str) and phase_name:
            name = phase_name
        payload["featured_reward"] = dict(reward)
    elif phase_number > 16 and fallback_categories:
        payload["featured_reward_category"] = fallback_categories[
            (phase_number - 1) % len(fallback_categories)
        ]
    else:
        return []

    return [
        Reminder(
            event_id=f"secret_treasure_{phase_number}",
            category="activity",
            name=name,
            event_date=open_date + timedelta(days=target_server_day - 1),
            remind_days_before=remind_day,
            date_label="开放日期",
            payload=payload,
            current_server_day=current_server_day,
        )
    ]


def _secret_treasure_fallback_categories(
    rule: Mapping[str, Any],
) -> tuple[str, ...]:
    post_phase_rule = rule.get("post_phase_16_rule")
    if not isinstance(post_phase_rule, Mapping):
        return ()
    if post_phase_rule.get("status") != "rule_confirmed_reward_detail_dynamic":
        return ()
    return tuple(_string_list(post_phase_rule.get("pattern_categories")))


def _build_weekly_activity_reminders(
    timeline: Mapping[str, Any],
    *,
    today: date,
    open_date: date | None,
    reminder_policy: ReminderPolicy,
    current_server_day: int | None,
) -> list[Reminder]:
    if open_date is None or current_server_day is None:
        return []

    activity_rules = timeline.get("activity_rules")
    if not isinstance(activity_rules, Mapping):
        return []
    rule = activity_rules.get("weekly_side_activity_rotation")
    if not isinstance(rule, Mapping):
        return []

    first_server_day = _positive_int(rule.get("first_server_day"))
    period_days = _positive_int(rule.get("period_days"))
    rotation = _string_list(rule.get("rotation"))
    if first_server_day is None or period_days is None or not rotation:
        return []

    reminders: list[Reminder] = []
    candidate_days = sorted(
        {
            day
            for activity_name in rotation
            if (day := reminder_policy.weekly_day(activity_name)) > 0
        },
        reverse=True,
    )
    for remind_days_before in candidate_days:
        target_server_day = current_server_day + remind_days_before
        if target_server_day < first_server_day:
            continue
        if (target_server_day - first_server_day) % period_days != 0:
            continue

        rotation_index = ((target_server_day - first_server_day) // period_days) % len(
            rotation
        )
        activity_name = rotation[rotation_index]
        if reminder_policy.weekly_day(activity_name) != remind_days_before:
            continue
        event_date = open_date + timedelta(days=target_server_day - 1)
        reminders.append(
            Reminder(
                event_id=f"weekly_side_activity_{target_server_day}",
                category="activity",
                name=activity_name,
                event_date=event_date,
                remind_days_before=remind_days_before,
                date_label="开放日期",
                payload={"type": "weekly_side_activity"},
                current_server_day=current_server_day,
            )
        )
    return reminders


def _build_reminder(
    item: Mapping[str, Any],
    *,
    event_id: object,
    category: str,
    date_label: str,
    today: date,
    open_date: date | None,
    season_anchor_dates: Mapping[str, date],
    remind_day: int,
    current_server_day: int | None,
    payload: Mapping[str, Any],
) -> Reminder | None:
    if not isinstance(event_id, str) or not event_id:
        return None
    name = item.get("name")
    if not isinstance(name, str) or not name:
        return None

    event_date = calculate_event_date(item, open_date, season_anchor_dates)
    if event_date is None:
        return None
    days_until = (event_date - today).days
    if remind_day <= 0 or days_until != remind_day:
        return None

    return Reminder(
        event_id=event_id,
        category=category,
        name=name,
        event_date=event_date,
        remind_days_before=days_until,
        date_label=date_label,
        payload=payload,
        current_server_day=current_server_day,
    )


def _confirmed_requirements(item: Mapping[str, Any]) -> dict[str, object]:
    if item.get("status") == "pending_formal_power":
        return {}

    requirements = item.get("requirements")
    if not isinstance(requirements, Mapping):
        return {}
    return {
        str(label): value for label, value in requirements.items() if value is not None
    }


def validate_remind_day(value: object, field_name: str = "remind_day") -> int:
    """校验单类别提前提醒天数；0 表示关闭，负数与布尔值无效。"""

    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} 必须是大于等于 0 的整数")
    return value


def _secret_treasure_phase_for_server_day(
    explicit_phases: Mapping[int, Mapping[str, Any]],
    *,
    target_server_day: int,
    first_server_day: int,
    period_days: int,
) -> tuple[int | None, Mapping[str, Any] | None]:
    explicit_matches = sorted(
        (
            (phase_number, phase)
            for phase_number, phase in explicit_phases.items()
            if _positive_int(phase.get("server_day")) == target_server_day
        ),
        key=lambda item: item[0],
    )
    if explicit_matches:
        return explicit_matches[0]

    phase_offset = target_server_day - first_server_day
    if phase_offset < 0 or phase_offset % period_days != 0:
        return None, None

    phase_number = (phase_offset // period_days) + 1
    phase = explicit_phases.get(phase_number)
    if phase is not None and _positive_int(phase.get("server_day")) is not None:
        return None, None
    return phase_number, phase


def _relative_date_label(days_before: int) -> str:
    return "明日" if days_before == 1 else f"{days_before} 天后"


def _format_daily_reminder_item(reminder: Reminder, today: date) -> str:
    category_label = {
        "dungeon": "副本",
        "activity": "活动",
        "event": "事件",
    }.get(reminder.category, "提醒")
    lines: list[str] = []
    if reminder.category == "dungeon":
        region = reminder.payload.get("region")
        name = (
            f"{region} · {reminder.name}"
            if isinstance(region, str) and region
            else reminder.name
        )
        lines.append(f"【{category_label}】{name}")
        requirements = reminder.payload.get("requirements")
        if isinstance(requirements, Mapping) and requirements:
            lines.append("已确认准入战力：")
            lines.extend(
                f"{label}：{format_power(power)}"
                for label, power in requirements.items()
            )
        lines.extend(["", _dungeon_preparation_hint(reminder.event_date, today)])
    else:
        lines.append(f"【{category_label}】{reminder.name}")
        reward = reminder.payload.get("featured_reward")
        if isinstance(reward, Mapping):
            reward_name = reward.get("name")
            if isinstance(reward_name, str) and reward_name:
                amount = reward.get("amount")
                reward_text = reward_name
                if amount is not None:
                    reward_text = f"{reward_text} ×{amount}"
                lines.append(f"重点奖励：{reward_text}")
        else:
            reward_category = reminder.payload.get("featured_reward_category")
            if isinstance(reward_category, str) and reward_category:
                lines.append(f"重点奖励类别：{reward_category}")
        if WEEKLY_ACTIVITY_POLICY_NAMES.get(reminder.name) == "bingo":
            lines.extend(["", BINGO_PREPARATION_HINT])
    return "\n".join(lines)


def _dungeon_preparation_hint(event_date: date, today: date) -> str:
    """副本开放前 1 天开始攒次数，相对时间基于本轮 check 日期。"""

    days_until_prepare = (event_date - timedelta(days=1) - today).days
    return f"准备建议：{format_relative_day(days_until_prepare)}开始攒副本次数。"


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return None
    return value


def _is_later_season(season: str) -> bool:
    if not season.startswith("S"):
        return False
    try:
        return int(season[1:]) >= 4
    except ValueError:
        return False


def _mapping_list(value: object) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _format_decimal(value: Decimal, suffix: str = "") -> str:
    if value == value.to_integral_value():
        return f"{value.quantize(Decimal(1))}{suffix}"
    return f"{value.normalize():f}{suffix}"
