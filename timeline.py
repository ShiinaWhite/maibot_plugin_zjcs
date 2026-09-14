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
SCHEDULE_HORIZON_DAYS = 14
WEEKLY_ACTIVITY_POLICY_NAMES = {
    "宾果抽抽乐": "bingo",
    "幸运刮刮乐": "scratch",
    "菲涅克的谜题": "fenek",
}
BINGO_MIN_FRUIT_COUNT = 20
BINGO_PREPARATION_HINT = (
    f"准备建议：现在开始攒果子，活动开始前至少留{BINGO_MIN_FRUIT_COUNT}个。"
)
WEEKLY_ACTIVITY_PRE_OPEN_MESSAGE = (
    "【杖剑助手 · 下一个活动】\n\n"
    "当前状态：服务器尚未开服。\n\n"
    "每周活动将在服务器开服后按时间线周期计算。"
)
RESERVED_GENERATED_ID_PREFIXES = (
    "secret_treasure_",
    "weekly_side_activity_",
)


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
class ScheduleEntry:
    """近期日程查询条目：描述时间线上实际发生的内容，与提醒策略无关。"""

    event_id: str
    category: str
    name: str
    event_date: date
    payload: Mapping[str, Any]
    current_server_day: int | None


@dataclass(frozen=True)
class ServerProgress:
    """服务器进度查询结果：一屏展示当前进度与前后关键节点。"""

    today: date
    open_date: date
    server_day: int
    current_season: str | None
    season_start_date: date | None
    season_day: int | None
    recent_node: ScheduleEntry | None
    next_node: ScheduleEntry | None


REWARD_MODE_EXPLICIT = "explicit"
REWARD_MODE_RULE_FALLBACK = "rule_fallback"
REWARD_MODE_UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class SecretTreasurePhase:
    """秘宝单期信息；reward_mode 明确区分奖励可信度来源。"""

    phase: int
    server_day: int
    event_date: date
    name: str
    payload: Mapping[str, Any]
    reward_mode: str


@dataclass(frozen=True)
class SecretTreasureOverview:
    """秘宝大作战查询结果：当前期（最近已开启）与下一期。"""

    today: date
    current_server_day: int
    current_phase: SecretTreasurePhase | None
    next_phase: SecretTreasurePhase | None


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


def _timeline_date_model(item: Mapping[str, Any]) -> str | None:
    """识别条目唯一的日期模型：event_date / server_day / season_day。

    区分「字段缺失」与「字段存在但非法」：后者属于坏数据，立即 fail
    closed 返回 None，而不是悄悄忽略后改用其他载体。允许 0 个或多个
    合法载体共存时同样返回 None。season 字段本身是元数据，可与
    server_day 合法共存。
    """

    carriers: list[str] = []
    if "event_date" in item and item["event_date"] is not None:
        event_date = item["event_date"]
        if isinstance(event_date, str) and event_date:
            try:
                date.fromisoformat(event_date)
            except ValueError:
                return None
            carriers.append("event_date")
        else:
            return None
    if "server_day" in item and item["server_day"] is not None:
        if _positive_int(item["server_day"]) is None:
            return None
        carriers.append("server_day")
    if "season_day" in item and item["season_day"] is not None:
        season = item.get("season")
        if _positive_int(item["season_day"]) is None:
            return None
        if not isinstance(season, str) or not season:
            return None
        carriers.append("season_day")
    if len(carriers) != 1:
        return None
    return carriers[0]


def calculate_event_date(
    item: Mapping[str, Any],
    open_date: date | None,
    season_anchor_dates: Mapping[str, date],
) -> date | None:
    """按条目唯一的日期模型计算日期；歧义或非法数据一律不可计算。"""

    model = _timeline_date_model(item)
    if model is None:
        return None
    if model == "event_date":
        return date.fromisoformat(item["event_date"])
    if model == "server_day":
        if open_date is None:
            return None
        return open_date + timedelta(days=item["server_day"] - 1)
    season = item["season"]
    anchor = season_anchor_dates.get(season)
    if anchor is None:
        return None
    return anchor + timedelta(days=item["season_day"] - 1)


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


def build_upcoming_schedule(
    timeline: Mapping[str, Any],
    *,
    today: date,
    open_date: date | None,
    season_anchor_dates: Mapping[str, date] | None = None,
    horizon_days: int = SCHEDULE_HORIZON_DAYS,
) -> list[ScheduleEntry]:
    """汇总窗口内实际会发生的内容；只读查询，不依赖提醒提前天数。"""

    if isinstance(horizon_days, bool) or not isinstance(horizon_days, int):
        raise TypeError("horizon_days 必须是整数")
    if horizon_days < 1:
        raise ValueError("horizon_days 必须是大于等于 1 的整数")
    anchors = season_anchor_dates or {}
    current_server_day = (
        calculate_server_day(today, open_date) if open_date is not None else None
    )
    end_date = today + timedelta(days=horizon_days - 1)
    entries: list[ScheduleEntry] = []

    for raw_dungeon in _mapping_list(timeline.get("dungeons")):
        entry = _dungeon_schedule_entry(
            raw_dungeon,
            open_date=open_date,
            anchors=anchors,
            current_server_day=current_server_day,
        )
        if entry is None or not today <= entry.event_date <= end_date:
            continue
        entries.append(entry)

    for raw_event in _mapping_list(timeline.get("events")):
        if raw_event.get("status") not in NOTIFIABLE_STATUSES:
            continue
        event_id = raw_event.get("id")
        name = raw_event.get("name")
        if not isinstance(event_id, str) or not event_id:
            continue
        if not isinstance(name, str) or not name:
            continue
        event_date = calculate_event_date(raw_event, open_date, anchors)
        if event_date is None or not today <= event_date <= end_date:
            continue
        entries.append(
            ScheduleEntry(
                event_id=event_id,
                category="event",
                name=name,
                event_date=event_date,
                payload={
                    "type": raw_event.get("type"),
                    "status": raw_event.get("status"),
                },
                current_server_day=current_server_day,
            )
        )

    entries.extend(
        _schedule_secret_treasure(
            timeline,
            open_date=open_date,
            current_server_day=current_server_day,
            horizon_days=horizon_days,
        )
    )
    entries.extend(
        _schedule_weekly_activities(
            timeline,
            open_date=open_date,
            current_server_day=current_server_day,
            horizon_days=horizon_days,
        )
    )

    return sorted(
        entries,
        key=lambda item: (
            item.event_date,
            _CATEGORY_ORDER.get(item.category, 99),
            item.event_id,
        ),
    )


def dungeon_prepare_date(event_date: date) -> date:
    """副本开放前 1 天开始攒次数；正式提醒与主动查询共用同一规则。"""

    return event_date - timedelta(days=1)


def find_next_dungeon(
    timeline: Mapping[str, Any],
    *,
    today: date,
    open_date: date | None,
    season_anchor_dates: Mapping[str, date] | None = None,
) -> ScheduleEntry | None:
    """返回今天起（含今天）最近一个日期可确定的副本；只读查询。"""

    anchors = season_anchor_dates or {}
    current_server_day = (
        calculate_server_day(today, open_date) if open_date is not None else None
    )
    candidates: list[ScheduleEntry] = []
    for raw_dungeon in _mapping_list(timeline.get("dungeons")):
        entry = _dungeon_schedule_entry(
            raw_dungeon,
            open_date=open_date,
            anchors=anchors,
            current_server_day=current_server_day,
        )
        if entry is None or entry.event_date < today:
            continue
        candidates.append(entry)
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item.event_date, item.event_id))
    return candidates[0]


def _dungeon_schedule_entry(
    raw_dungeon: Mapping[str, Any],
    *,
    open_date: date | None,
    anchors: Mapping[str, date],
    current_server_day: int | None,
) -> ScheduleEntry | None:
    status = raw_dungeon.get("status")
    if status not in NOTIFIABLE_STATUSES and status != "pending_formal_power":
        return None
    event_id = raw_dungeon.get("id")
    name = raw_dungeon.get("name")
    if not isinstance(event_id, str) or not event_id:
        return None
    if not isinstance(name, str) or not name:
        return None
    event_date = calculate_event_date(raw_dungeon, open_date, anchors)
    if event_date is None:
        return None
    return ScheduleEntry(
        event_id=event_id,
        category="dungeon",
        name=name,
        event_date=event_date,
        payload={
            "region": raw_dungeon.get("region"),
            "requirements": _confirmed_requirements(raw_dungeon),
            "status": status,
        },
        current_server_day=current_server_day,
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


def format_upcoming_schedule(
    entries: Iterable[ScheduleEntry],
    *,
    today: date,
    horizon_days: int = SCHEDULE_HORIZON_DAYS,
) -> str:
    ordered = sorted(
        entries,
        key=lambda item: (
            item.event_date,
            _CATEGORY_ORDER.get(item.category, 99),
            item.event_id,
        ),
    )
    end_date = today + timedelta(days=horizon_days - 1)
    title = "【杖剑助手 · 近期日程】"
    if not ordered:
        return f"{title}\n\n未来 {horizon_days} 天没有已确认的日程内容。"

    lines = [
        title,
        "",
        f"未来 {horizon_days} 天 · {today.isoformat()} ～ {end_date.isoformat()}",
    ]
    current_date: date | None = None
    for entry in ordered:
        if entry.event_date != current_date:
            days_until = (entry.event_date - today).days
            lines.extend(
                [
                    "",
                    f"{entry.event_date.isoformat()} · {_schedule_relative_label(days_until)}",
                ]
            )
            current_date = entry.event_date
        lines.extend(_schedule_entry_lines(entry))
    return "\n".join(lines)


def format_next_dungeon(
    entry: ScheduleEntry | None,
    *,
    today: date,
) -> str:
    title = "【杖剑助手 · 下一个副本】"
    if entry is None:
        return f"{title}\n\n当前时间线中没有可确定日期的后续副本。"

    region = entry.payload.get("region")
    name = (
        f"{region} · {entry.name}" if isinstance(region, str) and region else entry.name
    )
    lines = [
        title,
        "",
        name,
        "",
        f"开放日期：{entry.event_date.isoformat()}",
        f"距离开放：{_schedule_relative_label((entry.event_date - today).days)}",
    ]

    requirements = entry.payload.get("requirements")
    if isinstance(requirements, Mapping) and requirements:
        lines.extend(["", "已确认准入战力："])
        lines.extend(
            f"{label}：{format_power(power)}" for label, power in requirements.items()
        )
    else:
        lines.extend(["", "准入战力：暂未获得可靠的正式服数据。"])

    prepare_date = dungeon_prepare_date(entry.event_date)
    prepare_offset = (prepare_date - today).days
    if prepare_offset < 0:
        lines.extend(["", "准备建议：副本今天开放，无需再提前攒次数。"])
    else:
        prepare_text = (
            f"准备建议：{prepare_date.isoformat()} 开始攒副本次数"
            f"（{_schedule_relative_label(prepare_offset)}）。"
        )
        lines.extend(["", prepare_text])
    return "\n".join(lines)


def build_server_progress(
    timeline: Mapping[str, Any],
    *,
    today: date,
    open_date: date,
    season_anchor_dates: Mapping[str, date] | None = None,
) -> ServerProgress:
    """汇总服务器当前进度；关键节点仅含服务器/赛季进度型 generic event。"""

    anchors = season_anchor_dates or {}
    server_day = calculate_server_day(today, open_date)
    current_server_day = server_day if server_day >= 1 else None

    progression_nodes: list[ScheduleEntry] = []
    season_candidates: list[tuple[date, str]] = []
    for raw_event in _mapping_list(timeline.get("events")):
        entry = _progression_node_entry(
            raw_event,
            open_date=open_date,
            anchors=anchors,
            current_server_day=current_server_day,
        )
        if entry is not None:
            progression_nodes.append(entry)

        if raw_event.get("type") != "season":
            continue
        if raw_event.get("status") not in NOTIFIABLE_STATUSES:
            continue
        season = raw_event.get("season")
        if not isinstance(season, str) or not season:
            continue
        event_date = calculate_event_date(raw_event, open_date, anchors)
        if event_date is None or event_date > today:
            continue
        season_candidates.append((event_date, season))

    recent_node: ScheduleEntry | None = None
    next_node: ScheduleEntry | None = None
    if progression_nodes:
        ordered = sorted(
            progression_nodes, key=lambda item: (item.event_date, item.event_id)
        )
        reached = [item for item in ordered if item.event_date <= today]
        upcoming = [item for item in ordered if item.event_date > today]
        if reached:
            recent_node = reached[-1]
        if upcoming:
            next_node = upcoming[0]

    current_season: str | None = None
    season_start_date: date | None = None
    season_day: int | None = None
    if season_candidates:
        season_candidates.sort()
        season_start_date, current_season = season_candidates[-1]
        season_day = (today - season_start_date).days + 1

    return ServerProgress(
        today=today,
        open_date=open_date,
        server_day=server_day,
        current_season=current_season,
        season_start_date=season_start_date,
        season_day=season_day,
        recent_node=recent_node,
        next_node=next_node,
    )


def _progression_node_entry(
    raw_event: Mapping[str, Any],
    *,
    open_date: date | None,
    anchors: Mapping[str, date],
    current_server_day: int | None,
) -> ScheduleEntry | None:
    """进度节点仅限服务器/赛季进度模型的事件，绝对日历事件不算。"""

    if raw_event.get("status") not in NOTIFIABLE_STATUSES:
        return None
    if _timeline_date_model(raw_event) not in ("server_day", "season_day"):
        return None
    event_id = raw_event.get("id")
    name = raw_event.get("name")
    if not isinstance(event_id, str) or not event_id:
        return None
    if not isinstance(name, str) or not name:
        return None
    event_date = calculate_event_date(raw_event, open_date, anchors)
    if event_date is None:
        return None
    return ScheduleEntry(
        event_id=event_id,
        category="event",
        name=name,
        event_date=event_date,
        payload={"type": raw_event.get("type"), "status": raw_event.get("status")},
        current_server_day=current_server_day,
    )


def format_server_progress(progress: ServerProgress) -> str:
    title = "【杖剑助手 · 服务器进度】"
    lines = [
        title,
        "",
        f"今天：{progress.today.isoformat()}",
        f"开服日期：{progress.open_date.isoformat()}",
    ]
    if progress.server_day < 1:
        days_until_open = (progress.open_date - progress.today).days
        lines.extend(
            [
                "",
                "当前状态：服务器尚未开服",
                f"距离开服：{_progress_relative_label(days_until_open)}",
            ]
        )
        return "\n".join(lines)

    lines.append(f"当前服务器进度：开服第 {progress.server_day} 天")

    if progress.current_season is None or progress.season_start_date is None:
        lines.extend(["", "当前赛季：尚未进入 S1"])
    else:
        lines.extend(
            [
                "",
                f"当前赛季：{progress.current_season}",
                f"赛季开始：{progress.season_start_date.isoformat()}",
                f"当前赛季进度：第 {progress.season_day} 天",
            ]
        )

    if progress.recent_node is None:
        lines.extend(["", "最近关键节点：", "暂无已到达的关键节点。"])
    else:
        recent_offset = (progress.recent_node.event_date - progress.today).days
        lines.extend(
            [
                "",
                "最近关键节点：",
                f"{progress.recent_node.event_date.isoformat()} · {_progress_relative_label(recent_offset)}",
                progress.recent_node.name,
            ]
        )

    if progress.next_node is None:
        lines.extend(
            ["", "下一关键节点：", "当前时间线中没有可确定日期的后续关键节点。"]
        )
    else:
        next_offset = (progress.next_node.event_date - progress.today).days
        lines.extend(
            [
                "",
                "下一关键节点：",
                f"{progress.next_node.event_date.isoformat()} · {_progress_relative_label(next_offset)}",
                progress.next_node.name,
            ]
        )
    return "\n".join(lines)


def build_secret_treasure_overview(
    timeline: Mapping[str, Any],
    *,
    today: date,
    open_date: date,
) -> SecretTreasureOverview:
    """查询秘宝当前期（最近已开启）与下一期；与提醒提前天数无关。"""

    current_server_day = calculate_server_day(today, open_date)
    if current_server_day < 1:
        return SecretTreasureOverview(
            today=today,
            current_server_day=current_server_day,
            current_phase=None,
            next_phase=None,
        )

    inputs = _secret_treasure_rule_inputs(timeline)
    if inputs is None:
        return SecretTreasureOverview(
            today=today,
            current_server_day=current_server_day,
            current_phase=None,
            next_phase=None,
        )
    first_server_day, period_days, explicit_phases, fallback_categories = inputs

    # 候选期 = 有界生成的公式期次 ∪ 全部显式期次；显式 server_day override
    # 允许打破“期号顺序 == 时间顺序”，因此不能按公式推算候选范围边界。
    candidate_days = _secret_treasure_occurrence_days(
        first_server_day,
        period_days,
        explicit_phases,
        through_server_day=current_server_day,
    )

    phases: list[SecretTreasurePhase] = [
        _secret_treasure_phase(
            phase_number,
            phase_day,
            explicit_phases,
            fallback_categories,
            open_date,
        )
        for phase_number, phase_day in sorted(candidate_days.items())
    ]
    phases.sort(key=lambda item: (item.server_day, item.phase))

    reached = [item for item in phases if item.server_day <= current_server_day]
    upcoming = [item for item in phases if item.server_day > current_server_day]
    current_phase = reached[-1] if reached else None
    next_phase = upcoming[0] if upcoming else None

    return SecretTreasureOverview(
        today=today,
        current_server_day=current_server_day,
        current_phase=current_phase,
        next_phase=next_phase,
    )


def _secret_treasure_occurrence_days(
    first_server_day: int,
    period_days: int,
    explicit_phases: Mapping[int, Mapping[str, Any]],
    *,
    through_server_day: int,
) -> dict[int, int]:
    """生成期次→开服日映射；显式 server_day override 优先于公式。

    全部显式期次先进入候选集；公式期次按期号递增生成。由于公式开服日
    随期号严格递增，遇到第一个未被显式覆盖且越过 through_server_day 的
    公式期次后，剩余未覆盖期次必然更晚，不可能改变 current/next，
    可安全停止；显式期次已在第 1 步全量进入候选集，不依赖扫描顺序。
    """

    occurrence_days: dict[int, int] = {}
    for phase_number, explicit in explicit_phases.items():
        if not isinstance(explicit, Mapping):
            continue
        override = _positive_int(explicit.get("server_day"))
        if override is not None:
            occurrence_days[phase_number] = override

    phase_number = 1
    while True:
        if phase_number not in occurrence_days:
            formula_day = first_server_day + (phase_number - 1) * period_days
            occurrence_days[phase_number] = formula_day
            if formula_day > through_server_day:
                return occurrence_days
        phase_number += 1


def _weekly_rotation_name(
    server_day: int,
    first_server_day: int,
    period_days: int,
    rotation: list[str],
) -> str:
    """单一事实源：由开服日序换算轮换活动名。"""

    return rotation[((server_day - first_server_day) // period_days) % len(rotation)]


def find_next_weekly_activity(
    timeline: Mapping[str, Any],
    *,
    today: date,
    open_date: date,
) -> ScheduleEntry | None:
    """查询今天起（含今天）的下一项每周轮换活动；只读、与提醒策略无关。"""

    inputs = _weekly_rotation_rule_inputs(timeline)
    if inputs is None:
        return None
    first_server_day, period_days, rotation = inputs
    current_server_day = calculate_server_day(today, open_date)
    if current_server_day < 1:
        # 未开服：fail closed，避免生成带负数进度语义的条目。
        return None

    if current_server_day <= first_server_day:
        target_server_day = first_server_day
    else:
        delta = current_server_day - first_server_day
        if delta % period_days == 0:
            target_server_day = current_server_day
        else:
            target_server_day = (
                first_server_day
                + ((delta + period_days - 1) // period_days) * period_days
            )

    return ScheduleEntry(
        event_id=f"weekly_side_activity_{target_server_day}",
        category="activity",
        name=_weekly_rotation_name(
            target_server_day, first_server_day, period_days, rotation
        ),
        event_date=open_date + timedelta(days=target_server_day - 1),
        payload={"type": "weekly_side_activity", "server_day": target_server_day},
        current_server_day=current_server_day,
    )


def format_next_weekly_activity(
    entry: ScheduleEntry | None,
    *,
    today: date,
) -> str:
    title = "【杖剑助手 · 下一个活动】"
    if entry is None:
        return f"{title}\n\n当前时间线中没有可确定日期的后续每周活动。"

    server_day = entry.payload.get("server_day")
    server_day_text = (
        f"开服第 {server_day} 天" if isinstance(server_day, int) else "开服第 ? 天"
    )
    lines = [
        title,
        "",
        entry.name,
        "",
        f"活动日期：{entry.event_date.isoformat()}",
        f"服务器进度：{server_day_text}",
        f"距离活动：{_schedule_relative_label((entry.event_date - today).days)}",
    ]
    if entry.name == "宾果抽抽乐":
        lines.extend(
            ["", f"准备建议：活动开始前至少留 {BINGO_MIN_FRUIT_COUNT} 个果子。"]
        )
    else:
        lines.extend(["", "准备建议：当前时间线未记录固定准备建议。"])
    return "\n".join(lines)


def _secret_treasure_phase(
    phase_number: int,
    server_day: int,
    explicit_phases: Mapping[int, Mapping[str, Any]],
    fallback_categories: tuple[str, ...],
    open_date: date,
) -> SecretTreasurePhase:
    explicit = explicit_phases.get(phase_number)
    built = _secret_treasure_name_and_payload(
        phase_number, explicit, fallback_categories
    )
    if explicit is not None and built is not None:
        reward_mode = REWARD_MODE_EXPLICIT
    elif built is not None:
        reward_mode = REWARD_MODE_RULE_FALLBACK
    else:
        reward_mode = REWARD_MODE_UNAVAILABLE

    if built is not None:
        name, payload = built
    else:
        name = f"秘宝大作战·第{phase_number}期"
        payload = {"phase": phase_number}
        if isinstance(explicit, Mapping):
            explicit_name = explicit.get("name")
            if isinstance(explicit_name, str) and explicit_name:
                name = explicit_name

    return SecretTreasurePhase(
        phase=phase_number,
        server_day=server_day,
        event_date=open_date + timedelta(days=server_day - 1),
        name=name,
        payload=payload,
        reward_mode=reward_mode,
    )


def format_secret_treasure_overview(overview: SecretTreasureOverview) -> str:
    title = "【杖剑助手 · 秘宝大作战】"
    if overview.current_server_day < 1:
        return (
            f"{title}\n\n"
            "当前状态：服务器尚未开服。\n\n"
            "秘宝大作战将在服务器开服后按时间线周期计算。"
        )

    lines: list[str] = []
    for label, phase in (
        ("当前期（最近已开启）", overview.current_phase),
        ("下一期", overview.next_phase),
    ):
        lines.extend(["", f"{label}："])
        if phase is None:
            if label.startswith("当前"):
                lines.append("尚未开始")
            else:
                lines.append("暂无可确定的下一期。")
            continue

        offset = (phase.event_date - overview.today).days
        lines.append(phase.name)
        lines.append(
            f"开服第 {phase.server_day} 天 · "
            f"{phase.event_date.isoformat()}（{_progress_relative_label(offset)}）"
        )
        lines.extend(_secret_treasure_reward_lines(phase))
    return "\n".join([title] + lines)


def _secret_treasure_reward_lines(phase: SecretTreasurePhase) -> list[str]:
    if phase.reward_mode == REWARD_MODE_EXPLICIT:
        reward = phase.payload.get("featured_reward")
        if isinstance(reward, Mapping):
            reward_name = reward.get("name")
            if isinstance(reward_name, str) and reward_name:
                amount = reward.get("amount")
                reward_text = reward_name
                if amount is not None:
                    reward_text = f"{reward_text} ×{amount}"
                return [f"重点奖励：{reward_text}"]
        return ["重点奖励：暂未获得可靠确认。"]
    if phase.reward_mode == REWARD_MODE_RULE_FALLBACK:
        category = phase.payload.get("featured_reward_category")
        if isinstance(category, str) and category:
            return [
                f"重点奖励类别：{category}",
                "具体奖励：当前仅确认类别规律，以当期正式信息为准。",
            ]
    return ["重点奖励：暂未获得可靠确认。"]


def _progress_relative_label(days_offset: int) -> str:
    """支持正负天数偏移的相对时间：昨天/前天/N天前，今天/明天/后天/N天后。"""

    if days_offset >= 0:
        return _schedule_relative_label(days_offset)
    if days_offset == -1:
        return "昨天"
    if days_offset == -2:
        return "前天"
    return f"{-days_offset} 天前"


def _schedule_relative_label(days_until: int) -> str:
    if days_until == 0:
        return "今天"
    if days_until == 1:
        return "明天"
    if days_until == 2:
        return "后天"
    return f"{days_until} 天后"


def _schedule_entry_lines(entry: ScheduleEntry) -> list[str]:
    category_label = {
        "dungeon": "副本",
        "activity": "活动",
        "event": "事件",
    }.get(entry.category, "提醒")
    if entry.category == "dungeon":
        region = entry.payload.get("region")
        name = (
            f"{region} · {entry.name}"
            if isinstance(region, str) and region
            else entry.name
        )
        lines = [f"【{category_label}】{name}"]
        requirements = entry.payload.get("requirements")
        if isinstance(requirements, Mapping) and requirements:
            lines.append("已确认准入战力：")
            lines.extend(
                f"{label}：{format_power(power)}"
                for label, power in requirements.items()
            )
        return lines

    lines = [f"【{category_label}】{entry.name}"]
    reward = entry.payload.get("featured_reward")
    if isinstance(reward, Mapping):
        reward_name = reward.get("name")
        if isinstance(reward_name, str) and reward_name:
            amount = reward.get("amount")
            reward_text = reward_name
            if amount is not None:
                reward_text = f"{reward_text} ×{amount}"
            lines.append(f"重点奖励：{reward_text}")
    else:
        reward_category = entry.payload.get("featured_reward_category")
        if isinstance(reward_category, str) and reward_category:
            lines.append(f"重点奖励类别：{reward_category}")
    return lines


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


def _secret_treasure_rule_inputs(
    timeline: Mapping[str, Any],
) -> tuple[int, int, dict[int, Mapping[str, Any]], tuple[str, ...]] | None:
    activity_rules = timeline.get("activity_rules")
    if not isinstance(activity_rules, Mapping):
        return None
    rule = activity_rules.get("secret_treasure_battle")
    if not isinstance(rule, Mapping):
        return None

    first_server_day = _positive_int(rule.get("first_server_day"))
    period_days = _positive_int(rule.get("period_days"))
    if first_server_day is None or period_days is None:
        return None

    explicit_phases = {
        phase_number: phase
        for phase in _mapping_list(rule.get("known_phases"))
        if (phase_number := _positive_int(phase.get("phase"))) is not None
    }
    fallback_categories = _secret_treasure_fallback_categories(rule)
    return first_server_day, period_days, explicit_phases, fallback_categories


def _secret_treasure_name_and_payload(
    phase_number: int,
    phase: Mapping[str, Any] | None,
    fallback_categories: tuple[str, ...],
) -> tuple[str, dict[str, Any]] | None:
    name = f"秘宝大作战·第{phase_number}期"
    payload: dict[str, Any] = {"phase": phase_number}

    if phase is not None:
        phase_status = phase.get("status")
        reward = phase.get("featured_reward")
        if phase_status not in NOTIFIABLE_STATUSES or not isinstance(reward, Mapping):
            return None
        if reward.get("status") not in NOTIFIABLE_STATUSES:
            return None
        if not isinstance(reward.get("name"), str) or not reward["name"]:
            return None
        phase_name = phase.get("name")
        if isinstance(phase_name, str) and phase_name:
            name = phase_name
        payload["featured_reward"] = dict(reward)
    elif phase_number > 16 and fallback_categories:
        payload["featured_reward_category"] = fallback_categories[
            (phase_number - 1) % len(fallback_categories)
        ]
    else:
        return None
    return name, payload


def _build_secret_treasure_reminders(
    timeline: Mapping[str, Any],
    *,
    open_date: date | None,
    remind_day: int,
    current_server_day: int | None,
) -> list[Reminder]:
    if open_date is None or current_server_day is None or remind_day <= 0:
        return []

    inputs = _secret_treasure_rule_inputs(timeline)
    if inputs is None:
        return []
    first_server_day, period_days, explicit_phases, fallback_categories = inputs

    target_server_day = current_server_day + remind_day
    phase_number, phase = _secret_treasure_phase_for_server_day(
        explicit_phases,
        target_server_day=target_server_day,
        first_server_day=first_server_day,
        period_days=period_days,
    )
    if phase_number is None:
        return []
    built = _secret_treasure_name_and_payload(phase_number, phase, fallback_categories)
    if built is None:
        return []
    name, payload = built

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


def _weekly_rotation_rule_inputs(
    timeline: Mapping[str, Any],
) -> tuple[int, int, list[str]] | None:
    activity_rules = timeline.get("activity_rules")
    if not isinstance(activity_rules, Mapping):
        return None
    rule = activity_rules.get("weekly_side_activity_rotation")
    if not isinstance(rule, Mapping):
        return None

    first_server_day = _positive_int(rule.get("first_server_day"))
    period_days = _positive_int(rule.get("period_days"))
    rotation = _string_list(rule.get("rotation"))
    if first_server_day is None or period_days is None or not rotation:
        return None
    return first_server_day, period_days, rotation


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

    inputs = _weekly_rotation_rule_inputs(timeline)
    if inputs is None:
        return []
    first_server_day, period_days, rotation = inputs

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

        activity_name = _weekly_rotation_name(
            target_server_day, first_server_day, period_days, rotation
        )
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


def _schedule_secret_treasure(
    timeline: Mapping[str, Any],
    *,
    open_date: date | None,
    current_server_day: int | None,
    horizon_days: int,
) -> list[ScheduleEntry]:
    if open_date is None or current_server_day is None:
        return []
    inputs = _secret_treasure_rule_inputs(timeline)
    if inputs is None:
        return []
    first_server_day, period_days, explicit_phases, fallback_categories = inputs

    entries: list[ScheduleEntry] = []
    for offset in range(horizon_days):
        target_server_day = current_server_day + offset
        phase_number, phase = _secret_treasure_phase_for_server_day(
            explicit_phases,
            target_server_day=target_server_day,
            first_server_day=first_server_day,
            period_days=period_days,
        )
        if phase_number is None:
            continue
        built = _secret_treasure_name_and_payload(
            phase_number, phase, fallback_categories
        )
        if built is None:
            continue
        name, payload = built
        entries.append(
            ScheduleEntry(
                event_id=f"secret_treasure_{phase_number}",
                category="activity",
                name=name,
                event_date=open_date + timedelta(days=target_server_day - 1),
                payload=payload,
                current_server_day=current_server_day,
            )
        )
    return entries


def _schedule_weekly_activities(
    timeline: Mapping[str, Any],
    *,
    open_date: date | None,
    current_server_day: int | None,
    horizon_days: int,
) -> list[ScheduleEntry]:
    if open_date is None or current_server_day is None:
        return []
    inputs = _weekly_rotation_rule_inputs(timeline)
    if inputs is None:
        return []
    first_server_day, period_days, rotation = inputs

    entries: list[ScheduleEntry] = []
    for offset in range(horizon_days):
        target_server_day = current_server_day + offset
        if target_server_day < first_server_day:
            continue
        if (target_server_day - first_server_day) % period_days != 0:
            continue
        entries.append(
            ScheduleEntry(
                event_id=f"weekly_side_activity_{target_server_day}",
                category="activity",
                name=_weekly_rotation_name(
                    target_server_day, first_server_day, period_days, rotation
                ),
                event_date=open_date + timedelta(days=target_server_day - 1),
                payload={"type": "weekly_side_activity"},
                current_server_day=current_server_day,
            )
        )
    return entries


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

    days_until_prepare = (dungeon_prepare_date(event_date) - today).days
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


def audit_timeline_integrity(timeline: Mapping[str, Any]) -> list[str]:
    """静态审计时间线数据一致性；返回确定顺序的 issue 描述列表。

    用途是仓库测试门与人工 review，不在运行时暴露为用户命令。
    """

    issues: list[str] = []
    registry = timeline.get("sources")
    registered_source_keys: set[str] = set()
    if registry is not None and not isinstance(registry, Mapping):
        issues.append("sources: source registry 必须是对象")
    elif isinstance(registry, Mapping):
        for key, value in registry.items():
            if not isinstance(key, str) or not key:
                issues.append("sources: 存在无效的 source key")
                continue
            registered_source_keys.add(key)
            if not isinstance(value, Mapping):
                issues.append(f"sources.{key}: source 条目必须是对象")

    seen_ids: dict[str, str] = {}
    for kind in ("dungeons", "events"):
        raw_items = timeline.get(kind)
        if raw_items is not None and not isinstance(raw_items, list):
            issues.append(f"{kind}: 必须是数组")
            continue
        for index, item in enumerate(raw_items or []):
            _audit_timeline_item(
                kind, index, item, registered_source_keys, seen_ids, issues
            )

    _audit_secret_treasure_rule(timeline, registered_source_keys, issues)
    _audit_weekly_rotation_rule(timeline, registered_source_keys, issues)
    return sorted(issues)


def _audit_timeline_item(
    kind: str,
    index: int,
    item: object,
    registered_source_keys: set[str],
    seen_ids: dict[str, str],
    issues: list[str],
) -> None:
    label = f"{kind}[{index}]"
    if not isinstance(item, Mapping):
        issues.append(f"{label}: 条目必须是对象")
        return

    item_id = item.get("id")
    if not isinstance(item_id, str) or not item_id:
        issues.append(f"{label}: id 必须是非空字符串")
    else:
        if item_id.startswith(RESERVED_GENERATED_ID_PREFIXES):
            issues.append(f"{label}: id {item_id} 使用了系统保留前缀")
        previous = seen_ids.get(item_id)
        if previous is not None:
            issues.append(f"{label}: id {item_id} 与 {previous} 重复")
        else:
            seen_ids[item_id] = label

    name = item.get("name")
    if not isinstance(name, str) or not name:
        issues.append(f"{label}: name 必须是非空字符串")

    status = item.get("status")
    if not isinstance(status, str) or not status:
        issues.append(f"{label}: status 必须是非空字符串")

    if _timeline_date_model(item) is None:
        issues.append(f"{label}: 日期模型缺失、非法或歧义")

    _audit_source_references(label, item, registered_source_keys, issues)


def _audit_source_references(
    label: str,
    holder: Mapping[str, Any],
    registered_source_keys: set[str],
    issues: list[str],
) -> None:
    raw_sources = holder.get("sources")
    if raw_sources is None:
        return
    if not isinstance(raw_sources, list):
        issues.append(f"{label}: sources 必须是字符串数组")
        return
    for key in raw_sources:
        if not isinstance(key, str) or not key:
            issues.append(f"{label}: sources 存在无效 key")
        elif key not in registered_source_keys:
            issues.append(f"{label}: sources 引用未注册的 source key {key}")


def _audit_secret_treasure_rule(
    timeline: Mapping[str, Any],
    registered_source_keys: set[str],
    issues: list[str],
) -> None:
    activity_rules = timeline.get("activity_rules")
    if not isinstance(activity_rules, Mapping):
        return
    rule = activity_rules.get("secret_treasure_battle")
    if not isinstance(rule, Mapping):
        return
    label = "activity_rules.secret_treasure_battle"
    _audit_source_references(label, rule, registered_source_keys, issues)

    if _positive_int(rule.get("first_server_day")) is None:
        issues.append(f"{label}: first_server_day 必须是正整数")
    if _positive_int(rule.get("period_days")) is None:
        issues.append(f"{label}: period_days 必须是正整数")

    raw_phases = rule.get("known_phases")
    if raw_phases is not None and not isinstance(raw_phases, list):
        issues.append(f"{label}.known_phases: 必须是数组")
        raw_phases = None

    seen_phases: dict[int, str] = {}
    seen_override_days: dict[int, str] = {}
    for index, phase in enumerate(raw_phases or []):
        phase_label = f"{label}.known_phases[{index}]"
        if not isinstance(phase, Mapping):
            issues.append(f"{phase_label}: 条目必须是对象")
            continue
        _audit_source_references(phase_label, phase, registered_source_keys, issues)

        number = _positive_int(phase.get("phase"))
        if number is None:
            issues.append(f"{phase_label}: phase 必须是正整数")
        elif number in seen_phases:
            issues.append(
                f"{phase_label}: phase {number} 与 {seen_phases[number]} 重复"
            )
        else:
            seen_phases[number] = phase_label

        if "server_day" not in phase:
            continue
        override_day = _positive_int(phase.get("server_day"))
        if override_day is None:
            issues.append(f"{phase_label}: server_day 如果存在必须是正整数")
            continue
        if override_day in seen_override_days:
            issues.append(
                f"{phase_label}: 显式 server_day {override_day} "
                f"与 {seen_override_days[override_day]} 重复"
            )
        else:
            seen_override_days[override_day] = phase_label

        phase_status = phase.get("status")
        reward = phase.get("featured_reward")
        if (
            isinstance(phase_status, str)
            and phase_status in NOTIFIABLE_STATUSES
            and isinstance(reward, Mapping)
            and isinstance(reward.get("status"), str)
            and reward["status"] in NOTIFIABLE_STATUSES
        ):
            reward_name = reward.get("name")
            if not isinstance(reward_name, str) or not reward_name:
                issues.append(
                    f"{phase_label}: 可通知状态下的 featured_reward.name "
                    "必须是非空字符串"
                )

    post_rule = rule.get("post_phase_16_rule")
    if (
        isinstance(post_rule, Mapping)
        and post_rule.get("status") == "rule_confirmed_reward_detail_dynamic"
        and not _string_list(post_rule.get("pattern_categories"))
    ):
        issues.append(
            f"{label}.post_phase_16_rule: pattern_categories 至少需要一个非空字符串"
        )


def _audit_weekly_rotation_rule(
    timeline: Mapping[str, Any],
    registered_source_keys: set[str],
    issues: list[str],
) -> None:
    activity_rules = timeline.get("activity_rules")
    if not isinstance(activity_rules, Mapping):
        return
    rule = activity_rules.get("weekly_side_activity_rotation")
    if not isinstance(rule, Mapping):
        return
    label = "activity_rules.weekly_side_activity_rotation"
    _audit_source_references(label, rule, registered_source_keys, issues)
    if _positive_int(rule.get("first_server_day")) is None:
        issues.append(f"{label}: first_server_day 必须是正整数")
    if _positive_int(rule.get("period_days")) is None:
        issues.append(f"{label}: period_days 必须是正整数")
    if not _string_list(rule.get("rotation")):
        issues.append(f"{label}: rotation 必须是至少一个非空字符串的数组")
