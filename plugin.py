from __future__ import annotations

import asyncio
from collections.abc import Mapping
from contextlib import suppress
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import logging
from pathlib import Path
import tomllib
from zoneinfo import ZoneInfo

from maibot_sdk import Command, Field, MaiBotPlugin, PluginConfigBase

try:
    from .state import NotificationState, StateFileError
    from .timeline import (
        build_reminders,
        calculate_server_day,
        format_daily_reminders,
        load_timeline,
        make_notification_key,
        parse_iso_date,
        Reminder,
        ReminderPolicy,
        validate_remind_days,
    )
except ImportError:
    from state import NotificationState, StateFileError
    from timeline import (
        build_reminders,
        calculate_server_day,
        format_daily_reminders,
        load_timeline,
        make_notification_key,
        parse_iso_date,
        Reminder,
        ReminderPolicy,
        validate_remind_days,
    )


PLUGIN_ID = "zjcs.guild-notifier"
TIMELINE_PATH = Path(__file__).with_name("timeline_v1.json")
CONFIG_PATH = Path(__file__).with_name("config.toml")
SEND_RETRY_DELAYS_SECONDS = (1.0, 3.0, 5.0)
LEGACY_REMIND_DAYS_DEFAULT = (2, 1)
TEST_MESSAGE = """【杖剑助手 · 测试消息】

如果你看到这条消息，说明插件到 QQ 群的发送链路正常。

这不是游戏活动提醒。"""

_REMINDER_FIELD_DEFAULTS = {
    "dungeon_remind_days": (1,),
    "secret_treasure_remind_days": (2, 1),
    "bingo_remind_days": (4,),
    "scratch_remind_days": (2, 1),
    "fenek_remind_days": (2, 1),
    "event_remind_days": (2, 1),
}


class PluginSectionConfig(PluginConfigBase):
    """控制插件是否运行。"""

    __ui_label__ = "基础设置"
    __ui_icon__ = "package"
    __ui_order__ = 0

    enabled: bool = Field(
        default=False,
        description="开启后，插件会按每日调度向目标 QQ 群发送提醒。",
        json_schema_extra={"label": "启用杖剑助手"},
    )
    config_version: str = Field(
        default="1.1.0",
        description="插件内部配置结构版本。",
        json_schema_extra={
            "label": "配置版本",
            "hidden": True,
        },
    )


class TargetConfig(PluginConfigBase):
    """设置每日提醒发送到哪个 QQ 群。"""

    __ui_label__ = "通知目标"
    __ui_icon__ = "users"
    __ui_order__ = 1

    group_id: str = Field(
        default="",
        description="自动提醒发送到哪个 QQ 群。",
        json_schema_extra={
            "label": "目标 QQ 群号",
            "placeholder": "611817038",
        },
    )


class ServerConfig(PluginConfigBase):
    """设置服务器开服日期。"""

    __ui_label__ = "服务器进度"
    __ui_icon__ = "calendar"
    __ui_order__ = 2

    open_date: str = Field(
        default="",
        description="用于计算当前是开服第几天，格式为 YYYY-MM-DD。",
        json_schema_extra={
            "label": "开服日期",
            "placeholder": "2026-06-19",
        },
    )


class SeasonAnchorConfig(PluginConfigBase):
    """后续赛季开始后再填写；留空表示尚未配置。"""

    __ui_label__ = "S4+ 赛季日期"
    __ui_icon__ = "calendar-range"
    __ui_order__ = 3

    s4_start_date: str = Field(
        default="",
        description="S4 赛季第 1 天的日期；尚未开始时留空。",
        json_schema_extra={
            "label": "S4 赛季开始日期",
            "placeholder": "YYYY-MM-DD",
        },
    )
    s5_start_date: str = Field(
        default="",
        description="S5 赛季第 1 天的日期；尚未开始时留空。",
        json_schema_extra={
            "label": "S5 赛季开始日期",
            "placeholder": "YYYY-MM-DD",
        },
    )
    s6_start_date: str = Field(
        default="",
        description="S6 赛季第 1 天的日期；尚未开始时留空。",
        json_schema_extra={
            "label": "S6 赛季开始日期",
            "placeholder": "YYYY-MM-DD",
        },
    )


class ScheduleConfig(PluginConfigBase):
    """设置每天执行提醒检查的时间。"""

    __ui_label__ = "每日调度"
    __ui_icon__ = "clock"
    __ui_order__ = 4

    daily_check_time: str = Field(
        default="09:00",
        description="每天几点检查并发送当天提醒，格式为 HH:MM。",
        json_schema_extra={
            "label": "每日检查时间",
            "placeholder": "09:00",
        },
    )
    timezone: str = Field(
        default="Asia/Shanghai",
        description="日期和每日检查时间所使用的时区。",
        json_schema_extra={
            "label": "时区",
            "placeholder": "Asia/Shanghai",
        },
    )


class ReminderTimesConfig(PluginConfigBase):
    """不同类型内容可以分别设置提前提醒天数。"""

    __ui_label__ = "提醒时间"
    __ui_icon__ = "bell"
    __ui_order__ = 5

    dungeon_remind_days: list[int] = Field(
        default_factory=lambda: [1],
        description="新副本开放前多少天提醒，用于提前准备体力。",
        json_schema_extra={"label": "副本提前提醒天数"},
    )
    secret_treasure_remind_days: list[int] = Field(
        default_factory=lambda: [2, 1],
        description="秘宝大作战开始前多少天提醒。",
        json_schema_extra={"label": "秘宝大作战提前提醒天数"},
    )
    bingo_remind_days: list[int] = Field(
        default_factory=lambda: [4],
        description="宾果抽抽乐开始前多少天提醒，用于提前积攒果子。",
        json_schema_extra={"label": "宾果抽抽乐提前提醒天数"},
    )
    scratch_remind_days: list[int] = Field(
        default_factory=lambda: [2, 1],
        description="幸运刮刮乐开始前多少天提醒。",
        json_schema_extra={"label": "幸运刮刮乐提前提醒天数"},
    )
    fenek_remind_days: list[int] = Field(
        default_factory=lambda: [2, 1],
        description="菲涅克的谜题开始前多少天提醒。",
        json_schema_extra={"label": "菲涅克的谜题提前提醒天数"},
    )
    event_remind_days: list[int] = Field(
        default_factory=lambda: [2, 1],
        description="遗物池、赛季节点及其他重要事件前多少天提醒。",
        json_schema_extra={"label": "遗物池及重要事件提前提醒天数"},
    )


class ZjcsGuildNotifierConfig(PluginConfigBase):
    plugin: PluginSectionConfig = Field(default_factory=PluginSectionConfig)
    target: TargetConfig = Field(default_factory=TargetConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    season_dates: SeasonAnchorConfig = Field(default_factory=SeasonAnchorConfig)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    reminders: ReminderTimesConfig = Field(default_factory=ReminderTimesConfig)


@dataclass(frozen=True)
class ResolvedGroupStream:
    stream_id: str
    has_account_id: bool
    has_scope: bool


class ZjcsGuildNotifier(MaiBotPlugin):
    """《杖剑传说》公会时间线的确定性每日通知。"""

    config_model = ZjcsGuildNotifierConfig

    def __init__(self) -> None:
        super().__init__()
        self._daily_task: asyncio.Task[None] | None = None
        self._logger = logging.getLogger(PLUGIN_ID)

    def normalize_plugin_config(
        self, config_data: Mapping[str, object] | None
    ) -> tuple[dict[str, object], bool]:
        """把 V1 的赛季锚点和非默认统一提醒策略迁移到 V1.1 字段。"""

        migrated = (
            deepcopy(dict(config_data)) if isinstance(config_data, Mapping) else {}
        )
        legacy_config = _v1_config_for_migration(migrated)
        changed = (
            _migrate_v1_config(migrated, legacy_config)
            if legacy_config is not None
            else False
        )
        normalized, normalized_changed = super().normalize_plugin_config(migrated)
        return normalized, changed or normalized_changed

    async def on_load(self) -> None:
        self._start_daily_task()

    async def on_unload(self) -> None:
        await self._stop_daily_task()

    async def on_config_update(
        self,
        scope: str,
        config_data: dict[str, object],
        version: str,
    ) -> None:
        del scope, config_data, version
        await self._stop_daily_task()
        self._start_daily_task()

    @Command(
        "preview",
        description="预览今天按当前配置生成的合并提醒，不写入通知状态。",
        pattern=r"^/zjcs_preview\s*$",
        permission="operator",
    )
    async def handle_preview(self, stream_id: str = "", **kwargs: object):
        del kwargs
        if not stream_id:
            return False, "缺少命令来源 stream_id", True
        try:
            timezone, _ = self._validated_schedule()
            reminders, _ = self._build_configured_reminders(
                today=datetime.now(timezone).date()
            )
            message = format_daily_reminders(reminders, preview=True)
            result = await self.ctx.send.text(
                message,
                stream_id,
                return_details=True,
            )
        except Exception as exc:
            self._logger.error("今日提醒预览失败：%s", exc)
            return False, "今日提醒预览失败", True
        succeeded = _send_succeeded(result)
        return (
            succeeded,
            "今日提醒预览已生成" if succeeded else "今日提醒预览发送失败",
            True,
        )

    @Command(
        "test_send",
        description="向配置的目标 QQ 群发送一条明确标注的链路测试消息。",
        pattern=r"^/zjcs_test\s*$",
        permission="operator",
    )
    async def handle_test_send(self, **kwargs: object):
        del kwargs
        try:
            group_id = self.config.target.group_id.strip()
        except RuntimeError:
            group_id = ""
        if not group_id:
            return False, "尚未配置目标 QQ 群号", True
        succeeded = await self._send_text_with_retry(TEST_MESSAGE, group_id)
        return succeeded, "测试消息发送成功" if succeeded else "测试消息发送失败", True

    def _start_daily_task(self) -> None:
        if not self._is_enabled():
            return
        try:
            self._validated_schedule()
        except ValueError as exc:
            self._logger.error("插件调度配置无效，暂不启动每日任务：%s", exc)
            return
        if self._daily_task is None or self._daily_task.done():
            self._daily_task = asyncio.create_task(self._daily_schedule_loop())

    async def _stop_daily_task(self) -> None:
        task = self._daily_task
        self._daily_task = None
        if task is None:
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    async def _daily_schedule_loop(self) -> None:
        timezone, check_time = self._validated_schedule()
        next_run: datetime | None = None

        while True:
            now = datetime.now(timezone)
            due_date = _choose_due_check_date(now, check_time, next_run)
            if due_date is not None:
                await self._run_daily_check(today=due_date)
                next_run = datetime.combine(
                    due_date + timedelta(days=1),
                    check_time,
                    tzinfo=timezone,
                )
                continue

            if next_run is None:
                next_run = datetime.combine(
                    now.date(),
                    check_time,
                    tzinfo=timezone,
                )
            delay = max((next_run - now).total_seconds(), 0.1)
            await asyncio.sleep(delay)

    async def _run_daily_check(self, *, today: date) -> None:
        try:
            config = self.config
            if not config.plugin.enabled:
                return
            reminders, current_server_day = self._build_configured_reminders(
                today=today
            )
        except (OSError, TypeError, ValueError, RuntimeError) as exc:
            self._logger.error("每日时间线检查失败：%s", exc)
            return

        group_id = config.target.group_id.strip()
        if not group_id:
            self._logger.warning("插件已启用，但尚未配置目标 QQ 群号")
            return

        self._logger.info(
            "每日检查：date=%s server_day=%s reminders=%d",
            today.isoformat(),
            current_server_day,
            len(reminders),
        )

        state = NotificationState(
            Path(self.ctx.paths.data_dir) / NotificationState.FILE_NAME
        )
        try:
            state.load()
        except StateFileError as exc:
            self._logger.error("通知状态读取失败，本次跳过发送：%s", exc)
            return

        pending = [
            reminder
            for reminder in reminders
            if not state.contains(
                make_notification_key(
                    reminder.event_id,
                    reminder.event_date,
                    reminder.remind_days_before,
                )
            )
        ]
        if not pending:
            self._logger.info("每日检查去重完成：pending=0")
            return

        keys = [
            make_notification_key(
                reminder.event_id,
                reminder.event_date,
                reminder.remind_days_before,
            )
            for reminder in pending
        ]
        self._logger.info(
            "每日检查去重完成：pending=%d merged_reminders=%d",
            len(pending),
            len(pending),
        )
        message = format_daily_reminders(pending)
        if not await self._send_text_with_retry(message, group_id):
            return

        try:
            state.mark_sent_many(keys)
        except StateFileError as exc:
            self._logger.error("合并通知已发送但状态批量写入失败：%s", exc)
            return
        self._logger.info("合并通知发送成功并写入 notification_keys=%d", len(keys))

    def _build_configured_reminders(self, *, today: date) -> tuple[list[Reminder], int]:
        config = self.config
        if not config.server.open_date.strip():
            raise ValueError("开服日期不能为空")

        open_date = parse_iso_date(config.server.open_date, "server.open_date")
        season_anchor_dates = {
            season: parse_iso_date(anchor, f"season_dates.{season.lower()}_start_date")
            for season, anchor in {
                "S4": config.season_dates.s4_start_date,
                "S5": config.season_dates.s5_start_date,
                "S6": config.season_dates.s6_start_date,
            }.items()
            if anchor.strip()
        }
        reminder_policy = ReminderPolicy(
            dungeon=validate_remind_days(
                config.reminders.dungeon_remind_days, "dungeon_remind_days"
            ),
            secret_treasure=validate_remind_days(
                config.reminders.secret_treasure_remind_days,
                "secret_treasure_remind_days",
            ),
            bingo=validate_remind_days(
                config.reminders.bingo_remind_days, "bingo_remind_days"
            ),
            scratch=validate_remind_days(
                config.reminders.scratch_remind_days, "scratch_remind_days"
            ),
            fenek=validate_remind_days(
                config.reminders.fenek_remind_days, "fenek_remind_days"
            ),
            event=validate_remind_days(
                config.reminders.event_remind_days, "event_remind_days"
            ),
        )
        current_server_day = calculate_server_day(today, open_date)
        reminders = build_reminders(
            load_timeline(TIMELINE_PATH),
            today=today,
            open_date=open_date,
            season_anchor_dates=season_anchor_dates,
            reminder_policy=reminder_policy,
        )
        return reminders, current_server_day

    async def _send_text_with_retry(self, message: str, group_id: str) -> bool:
        """有限重试一条消息，并在每次 retry 前重新解析目标群 stream。"""

        total_attempts = len(SEND_RETRY_DELAYS_SECONDS) + 1
        previous_stream_id: str | None = None
        for attempt in range(total_attempts):
            if attempt:
                await asyncio.sleep(SEND_RETRY_DELAYS_SECONDS[attempt - 1])

            try:
                target = await self._resolve_group_stream(group_id)
            except Exception as exc:
                self._logger.warning(
                    "发送第 %d/%d 次尝试解析目标群失败：%s",
                    attempt + 1,
                    total_attempts,
                    exc,
                )
                continue

            if (
                previous_stream_id is not None
                and target.stream_id != previous_stream_id
            ):
                self._logger.info(
                    "发送 retry 重新选择 stream：previous=%s current=%s",
                    previous_stream_id,
                    target.stream_id,
                )
            previous_stream_id = target.stream_id
            self._logger.info(
                "发送尝试：attempt=%d/%d stream_id=%s account_id_present=%s "
                "scope_present=%s",
                attempt + 1,
                total_attempts,
                target.stream_id,
                target.has_account_id,
                target.has_scope,
            )
            try:
                result = await self.ctx.send.text(
                    message,
                    target.stream_id,
                    return_details=True,
                )
            except Exception as exc:
                if attempt + 1 < total_attempts:
                    self._logger.warning(
                        "通知第 %d 次发送失败，将在 %.1f 秒后重试：%s",
                        attempt + 1,
                        SEND_RETRY_DELAYS_SECONDS[attempt],
                        exc,
                    )
                else:
                    self._logger.error(
                        "通知发送失败，已耗尽 %d 次尝试，未记录为已完成：%s",
                        total_attempts,
                        exc,
                    )
                continue

            if _send_succeeded(result):
                self._logger.info(
                    "消息发送成功：attempt=%d/%d stream_id=%s",
                    attempt + 1,
                    total_attempts,
                    target.stream_id,
                )
                return True

            if attempt + 1 < total_attempts:
                self._logger.warning(
                    "通知第 %d 次发送未确认成功，将在 %.1f 秒后重试",
                    attempt + 1,
                    SEND_RETRY_DELAYS_SECONDS[attempt],
                )
            else:
                self._logger.warning(
                    "通知发送未确认成功，已耗尽 %d 次尝试，未记录为已完成",
                    total_attempts,
                )

        return False

    async def _resolve_group_stream(self, group_id: str) -> ResolvedGroupStream:
        streams_result = await self.ctx.chat.get_group_streams(platform="qq")
        streams = _extract_group_streams(streams_result)
        if target := _select_group_stream(streams, group_id):
            return target

        result = await self.ctx.chat.open_session(
            platform="qq",
            chat_type="group",
            group_id=group_id,
        )
        if not isinstance(result, Mapping):
            raise RuntimeError("chat.open_session 未返回对象")

        stream_id = result.get("stream_id")
        if not isinstance(stream_id, str) or not stream_id:
            stream = result.get("stream")
            if isinstance(stream, Mapping):
                stream_id = stream.get("stream_id")
        if not isinstance(stream_id, str) or not stream_id:
            raise RuntimeError("chat.open_session 返回结果中缺少 stream_id")
        return ResolvedGroupStream(
            stream_id=stream_id,
            has_account_id=False,
            has_scope=False,
        )

    def _validated_schedule(self) -> tuple[ZoneInfo, time]:
        config = self.config.schedule
        try:
            timezone = ZoneInfo(config.timezone)
        except Exception as exc:
            raise ValueError(f"无效时区：{config.timezone}") from exc

        try:
            hour_text, minute_text = config.daily_check_time.split(":", maxsplit=1)
            check_time = time(int(hour_text), int(minute_text))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"daily_check_time 必须是 HH:MM，当前为 {config.daily_check_time}"
            ) from exc
        return timezone, check_time

    def _is_enabled(self) -> bool:
        try:
            return bool(self.config.plugin.enabled)
        except RuntimeError:
            return False


def _choose_due_check_date(
    now: datetime,
    check_time: time,
    scheduled_for: datetime | None,
) -> date | None:
    """返回应检查的日期；错过调度时只检查今天，不补发过去日期。"""

    if scheduled_for is None:
        today_check = datetime.combine(now.date(), check_time, tzinfo=now.tzinfo)
        return now.date() if now >= today_check else None
    if now < scheduled_for:
        return None
    return max(scheduled_for.date(), now.date())


def _v1_config_for_migration(
    config_for_normalize: Mapping[str, object],
) -> dict[str, object] | None:
    """取得 V1 原配置；Runner 升级重建后从插件自身配置文件补取旧键。"""

    if _config_version(config_for_normalize) == "1.0.0":
        return deepcopy(dict(config_for_normalize))
    if not CONFIG_PATH.is_file():
        return None
    try:
        with CONFIG_PATH.open("rb") as handle:
            disk_config = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        logging.getLogger(PLUGIN_ID).warning(
            "无法读取磁盘配置以尝试 V1→V1.1 迁移，将按 Host 已提供配置继续：%s",
            exc,
        )
        return None
    return disk_config if _config_version(disk_config) == "1.0.0" else None


def _config_version(config: Mapping[str, object]) -> str:
    plugin_section = config.get("plugin")
    if not isinstance(plugin_section, Mapping):
        return ""
    value = plugin_section.get("config_version")
    return value.strip() if isinstance(value, str) else ""


def _migrate_v1_config(
    config: dict[str, object], legacy_config: Mapping[str, object]
) -> bool:
    """把 V1 旧值写入 Runner 已重建的 V1.1 字段。"""

    changed = False
    legacy_server = legacy_config.get("server")
    season_dates = config.get("season_dates")
    if isinstance(legacy_server, Mapping) and isinstance(season_dates, dict):
        legacy_anchors = legacy_server.get("season_anchor_dates")
        if isinstance(legacy_anchors, Mapping):
            for season, field_name in {
                "S4": "s4_start_date",
                "S5": "s5_start_date",
                "S6": "s6_start_date",
            }.items():
                current_value = season_dates.get(field_name)
                legacy_value = legacy_anchors.get(season)
                if legacy_value is None:
                    legacy_value = legacy_anchors.get(season.lower())
                if (
                    (not isinstance(current_value, str) or not current_value.strip())
                    and isinstance(legacy_value, str)
                    and legacy_value.strip()
                ):
                    season_dates[field_name] = legacy_value.strip()
                    changed = True

    legacy_schedule = legacy_config.get("schedule")
    reminders = config.get("reminders")
    if isinstance(legacy_schedule, Mapping) and isinstance(reminders, dict):
        legacy_values = legacy_schedule.get("remind_days_before")
        if isinstance(legacy_values, (list, tuple)):
            try:
                legacy_days = validate_remind_days(legacy_values)
            except ValueError:
                legacy_days = ()
        else:
            legacy_days = ()
        new_fields_are_defaults = all(
            isinstance(value := reminders.get(field_name), (list, tuple))
            and tuple(value) == default_days
            for field_name, default_days in _REMINDER_FIELD_DEFAULTS.items()
        )
        if (
            legacy_days
            and legacy_days != LEGACY_REMIND_DAYS_DEFAULT
            and new_fields_are_defaults
        ):
            for field_name in _REMINDER_FIELD_DEFAULTS:
                reminders[field_name] = list(legacy_days)
            changed = True

    return changed


def _send_succeeded(result: object) -> bool:
    if result is True:
        return True
    return isinstance(result, Mapping) and result.get("sent") is True


def _extract_group_streams(result: object) -> list[Mapping[str, object]]:
    """读取 chat.get_group_streams 的当前 SDK 返回值。"""

    if isinstance(result, Mapping):
        if result.get("success") is False:
            raise RuntimeError(
                f"chat.get_group_streams 执行失败：{result.get('error', '未知错误')}"
            )
        raw_streams = result.get("streams")
    else:
        raw_streams = result

    if not isinstance(raw_streams, list):
        raise RuntimeError("chat.get_group_streams 未返回 streams 列表")
    return [stream for stream in raw_streams if isinstance(stream, Mapping)]


def _select_group_stream(
    streams: list[Mapping[str, object]], group_id: str
) -> ResolvedGroupStream | None:
    """按路由元数据优先级选择目标群已有 stream。"""

    normalized_group_id = group_id.strip()
    candidates: list[tuple[int, str, ResolvedGroupStream]] = []
    for stream in streams:
        if str(stream.get("group_id") or "").strip() != normalized_group_id:
            continue

        stream_id = _first_nonempty_stream_value(stream, "stream_id", "session_id")
        if stream_id is None:
            continue

        account_id = _stream_metadata_value(stream, "account_id")
        scope = _stream_metadata_value(stream, "scope")
        if account_id and scope:
            priority = 3
        elif account_id:
            priority = 2
        elif scope:
            priority = 1
        else:
            priority = 0
        candidates.append(
            (
                priority,
                stream_id,
                ResolvedGroupStream(
                    stream_id=stream_id,
                    has_account_id=bool(account_id),
                    has_scope=bool(scope),
                ),
            )
        )

    if not candidates:
        return None

    # 同一优先级不使用 SDK 返回顺序或非路由字段猜测，采用稳定的 stream_id tie-break。
    candidates.sort(key=lambda candidate: (-candidate[0], candidate[1]))
    return candidates[0][2]


def _select_group_stream_id(
    streams: list[Mapping[str, object]], group_id: str
) -> str | None:
    target = _select_group_stream(streams, group_id)
    return target.stream_id if target is not None else None


def _first_nonempty_stream_value(
    stream: Mapping[str, object], *keys: str
) -> str | None:
    for key in keys:
        value = str(stream.get(key) or "").strip()
        if value:
            return value
    return None


def _stream_metadata_value(stream: Mapping[str, object], key: str) -> str:
    return str(stream.get(key) or "").strip()


def create_plugin() -> ZjcsGuildNotifier:
    return ZjcsGuildNotifier()
