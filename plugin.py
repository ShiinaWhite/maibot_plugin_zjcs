from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping
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
        validate_remind_day,
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
        validate_remind_day,
    )


PLUGIN_ID = "zjcs.guild-notifier"
TIMELINE_PATH = Path(__file__).with_name("timeline_v1.json")
CONFIG_PATH = Path(__file__).with_name("config.toml")
SEND_RETRY_DELAYS_SECONDS = (1.0, 3.0, 5.0)
LEGACY_REMIND_DAYS_DEFAULT = (2, 1)
LEGACY_CONFIG_VERSIONS = frozenset({"1.0.0", "1.1.0"})
PREVIOUS_CONFIG_VERSIONS = frozenset({"1.2.0"})
CURRENT_CONFIG_VERSION = "1.3.0"
COMMAND_PATTERN = r"^/(?:杖剑传说|zjcs)(?:\s+(?P<sub>\S+))?\s*$"
COMMAND_DENIED_MESSAGE = "你没有权限使用杖剑助手指令。"
COMMAND_HELP_MESSAGE = """【杖剑助手 · 指令帮助】

/杖剑传说 预览
查看今天按当前配置会生成的提醒，不影响提醒状态。

/杖剑传说 测试
向已配置的通知群实际发送一条链路测试消息。

缩写：/zjcs 预览、/zjcs 测试；发送 /杖剑传说 或 /zjcs 可随时查看本帮助。"""
TEST_MESSAGE = """【杖剑助手 · 测试消息】

如果你看到这条消息，说明插件到 QQ 群的发送链路正常。

这不是游戏活动提醒。"""

_REMINDER_FIELD_DEFAULTS = {
    "dungeon_remind_day": 1,
    "secret_treasure_remind_day": 2,
    "bingo_remind_day": 4,
    "scratch_remind_day": 2,
    "fenek_remind_day": 2,
    "event_remind_day": 2,
}
_REMINDER_FIELD_RENAMES = {
    f"{field.removesuffix('_remind_day')}_remind_days": field
    for field in _REMINDER_FIELD_DEFAULTS
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
        default=CURRENT_CONFIG_VERSION,
        description="插件内部配置结构版本。",
        json_schema_extra={
            "label": "配置版本",
            "hidden": True,
        },
    )


class TargetConfig(PluginConfigBase):
    """设置每日提醒发送到哪些 QQ 群。"""

    __ui_label__ = "通知目标"
    __ui_icon__ = "users"
    __ui_order__ = 1

    group_ids: list[str] = Field(
        default_factory=list,
        description=(
            "杖剑助手会向这里配置的所有 QQ 群发送提醒，可添加多个群。"
            "每个元素都是一个 QQ 群号。"
        ),
        json_schema_extra={
            "label": "目标 QQ 群号",
            "placeholder": "123456789",
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
            "placeholder": "YYYY-MM-DD",
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
            "hidden": True,
        },
    )


class ReminderTimesConfig(PluginConfigBase):
    """不同类型内容可以分别设置提前提醒天数；0 表示关闭该类别。"""

    __ui_label__ = "提醒时间"
    __ui_icon__ = "bell"
    __ui_order__ = 5

    dungeon_remind_day: int = Field(
        default=1,
        ge=0,
        description="新副本开放前多少天提醒，用于提前准备体力；填写 0 可关闭此类提醒。",
        json_schema_extra={"label": "副本提前提醒天数"},
    )
    secret_treasure_remind_day: int = Field(
        default=2,
        ge=0,
        description="秘宝大作战开始前多少天提醒；填写 0 可关闭此类提醒。",
        json_schema_extra={"label": "秘宝大作战提前提醒天数"},
    )
    bingo_remind_day: int = Field(
        default=4,
        ge=0,
        description="宾果抽抽乐开始前多少天提醒，用于提前积攒果子；填写 0 可关闭此类提醒。",
        json_schema_extra={"label": "宾果抽抽乐提前提醒天数"},
    )
    scratch_remind_day: int = Field(
        default=2,
        ge=0,
        description="幸运刮刮乐开始前多少天提醒；填写 0 可关闭此类提醒。",
        json_schema_extra={"label": "幸运刮刮乐提前提醒天数"},
    )
    fenek_remind_day: int = Field(
        default=2,
        ge=0,
        description="菲涅克的谜题开始前多少天提醒；填写 0 可关闭此类提醒。",
        json_schema_extra={"label": "菲涅克的谜题提前提醒天数"},
    )
    event_remind_day: int = Field(
        default=2,
        ge=0,
        description="遗物池、赛季节点及其他重要事件前多少天提醒；填写 0 可关闭此类提醒。",
        json_schema_extra={"label": "遗物池及重要事件提前提醒天数"},
    )


class CommandConfig(PluginConfigBase):
    """控制谁可以使用杖剑助手的聊天指令。"""

    __ui_label__ = "指令设置"
    __ui_icon__ = "terminal"
    __ui_order__ = 6

    admin_qq: str = Field(
        default="",
        description="填写后仅该 QQ 账号可以使用杖剑助手指令；留空则所有人都可以使用。",
        json_schema_extra={
            "label": "管理员 QQ 号",
            "placeholder": "123456789",
        },
    )


class ZjcsGuildNotifierConfig(PluginConfigBase):
    plugin: PluginSectionConfig = Field(default_factory=PluginSectionConfig)
    target: TargetConfig = Field(default_factory=TargetConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    season_dates: SeasonAnchorConfig = Field(default_factory=SeasonAnchorConfig)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    reminders: ReminderTimesConfig = Field(default_factory=ReminderTimesConfig)
    command: CommandConfig = Field(default_factory=CommandConfig)


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
        self._legacy_state_group_id: str | None = None

    def normalize_plugin_config(
        self, config_data: Mapping[str, object] | None
    ) -> tuple[dict[str, object], bool]:
        """把旧版本配置迁移到当前版本字段。

        V1.0：赛季锚点和统一提醒策略；V1.1：单目标群和列表提醒天数；
        V1.2 → V1.3：新增指令设置（command.admin_qq），仅更新版本号。
        """

        migrated = (
            deepcopy(dict(config_data)) if isinstance(config_data, Mapping) else {}
        )
        legacy_config = _legacy_config_for_migration(migrated)
        changed = False
        if legacy_config is not None:
            legacy_group_id = _legacy_target_group_id(legacy_config)
            if legacy_group_id:
                self._legacy_state_group_id = legacy_group_id
            if _config_version(legacy_config) == "1.0.0":
                changed = _migrate_v1_config(migrated, legacy_config)
            changed = _migrate_v1_1_config(migrated, legacy_config) or changed
        changed = _migrate_config_version(migrated) or changed
        normalized, normalized_changed = super().normalize_plugin_config(migrated)
        return normalized, changed or normalized_changed

    async def on_load(self) -> None:
        self._migrate_notification_state()
        self._start_daily_task()

    async def on_unload(self) -> None:
        await self._stop_daily_task()

    def _migrate_notification_state(self) -> None:
        """插件加载时把 V1 全局通知状态一次性迁移为按群状态。

        旧版已发送键优先归属配置迁移时识别出的旧目标群；识别不到时，
        仅在当前配置规范化后恰好只有一个目标群时使用该群兜底恢复，
        0 个或多个群时保持原文件不动，后续发送按失败关闭处理。
        """

        legacy_group_id = self._legacy_state_group_id
        if not legacy_group_id:
            legacy_group_id = self._sole_configured_group_id()
        state_path = Path(self.ctx.paths.data_dir) / NotificationState.FILE_NAME
        try:
            migrated = NotificationState.migrate_v1_file(state_path, legacy_group_id)
        except StateFileError as exc:
            self._logger.error("通知状态迁移失败，发送前将按失败关闭处理：%s", exc)
            return
        if migrated:
            self._logger.info(
                "通知状态已从 V1 迁移为分群状态：group_id=%s", legacy_group_id
            )

    def _sole_configured_group_id(self) -> str | None:
        """当前配置规范化后恰好只有一个目标群时返回该群号，否则返回 None。"""

        try:
            group_ids = _normalized_group_ids(self.config.target.group_ids)
        except RuntimeError:
            return None
        return group_ids[0] if len(group_ids) == 1 else None

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
        "zjcs_command",
        description="杖剑助手指令入口：帮助、预览、测试。",
        pattern=COMMAND_PATTERN,
    )
    async def handle_zjcs_command(
        self,
        stream_id: str = "",
        user_id: str = "",
        matched_groups: Mapping[str, object] | None = None,
        **kwargs: object,
    ):
        del kwargs
        if not self._is_command_allowed(user_id):
            return False, COMMAND_DENIED_MESSAGE, True

        subcommand = ""
        if isinstance(matched_groups, Mapping):
            subcommand = str(matched_groups.get("sub") or "").strip()
        if subcommand == "预览":
            return await self._run_preview(stream_id)
        if subcommand == "测试":
            return await self._run_test_send()
        # 帮助、无参数与未知子命令统一返回帮助。
        return await self._send_command_help(stream_id)

    def _is_command_allowed(self, sender_qq: object) -> bool:
        """统一指令授权：未配置管理员时所有人可用，配置后仅该 QQ 账号可用。"""

        try:
            admin_qq = str(self.config.command.admin_qq or "").strip()
        except RuntimeError:
            return False
        if not admin_qq:
            return True
        return str(sender_qq or "").strip() == admin_qq

    async def _send_command_help(self, stream_id: str):
        if not stream_id:
            return False, "缺少命令来源 stream_id", True
        try:
            result = await self.ctx.send.text(
                COMMAND_HELP_MESSAGE,
                stream_id,
                return_details=True,
            )
        except (OSError, RuntimeError) as exc:
            # send.text 经 Host RPC 转发，失败以 OSError/RuntimeError 族抛出。
            self._logger.error("指令帮助发送失败：%s", exc)
            return False, "指令帮助发送失败", True
        succeeded = _send_succeeded(result)
        return (
            succeeded,
            "指令帮助已发送" if succeeded else "指令帮助发送失败",
            True,
        )

    async def _run_preview(self, stream_id: str):
        if not stream_id:
            return False, "缺少命令来源 stream_id", True
        try:
            timezone, _ = self._validated_schedule()
            today = datetime.now(timezone).date()
            reminders, _ = self._build_configured_reminders(today=today)
            message = format_daily_reminders(reminders, today=today, preview=True)
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

    async def _run_test_send(self):
        group_ids = self._configured_group_ids()
        if not group_ids:
            return False, "尚未配置目标 QQ 群号", True

        succeeded_groups: list[str] = []
        for group_id in group_ids:
            if await self._send_text_with_retry(TEST_MESSAGE, group_id):
                succeeded_groups.append(group_id)
            # 每个群独立重试，单个群失败不影响其他群的测试发送。

        total = len(group_ids)
        if len(succeeded_groups) == total:
            return True, f"测试消息发送成功（{total}/{total} 个群）", True
        if not succeeded_groups:
            return False, f"测试消息发送失败（0/{total} 个群成功）", True
        return (
            False,
            f"测试消息部分成功（{len(succeeded_groups)}/{total} 个群成功）",
            True,
        )

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

        group_ids = _normalized_group_ids(config.target.group_ids)
        if not group_ids:
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

        keys = [
            make_notification_key(
                reminder.event_id,
                reminder.event_date,
                reminder.remind_days_before,
            )
            for reminder in reminders
        ]
        reminders_with_keys = list(zip(reminders, keys))
        # reminders 与 keys 只构造一次；每个群按自己的已发送状态
        # 计算各自的待发集合，正文只包含该群尚未收到过的提醒。
        group_plans: list[tuple[str, list[Reminder], list[str]]] = []
        for group_id in group_ids:
            group_pending = [
                (reminder, key)
                for reminder, key in reminders_with_keys
                if not state.contains(group_id, key)
            ]
            if group_pending:
                group_plans.append(
                    (
                        group_id,
                        [reminder for reminder, _ in group_pending],
                        [key for _, key in group_pending],
                    )
                )

        if not group_plans:
            self._logger.info("每日检查去重完成：pending=0")
            return

        self._logger.info(
            "每日检查去重完成：pending=%d merged_groups=%d",
            sum(len(group_keys) for _, _, group_keys in group_plans),
            len(group_plans),
        )

        for group_id, group_pending, group_keys in group_plans:
            # 同一群在一轮 daily check 中仍只收到一条合并消息。
            message = format_daily_reminders(group_pending, today=today)
            if not await self._send_text_with_retry(message, group_id):
                self._logger.warning(
                    "目标群通知未发送成功，不记录为已完成：group_id=%s", group_id
                )
                continue

            try:
                state.mark_sent_many(group_id, group_keys)
            except StateFileError as exc:
                self._logger.error(
                    "合并通知已发送但状态批量写入失败，不声称该群完成：%s keys=%d",
                    exc,
                    len(group_keys),
                )
                continue
            self._logger.info(
                "合并通知发送成功并写入 notification_keys=%d group_id=%s",
                len(group_keys),
                group_id,
            )

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
            dungeon=validate_remind_day(
                config.reminders.dungeon_remind_day, "dungeon_remind_day"
            ),
            secret_treasure=validate_remind_day(
                config.reminders.secret_treasure_remind_day,
                "secret_treasure_remind_day",
            ),
            bingo=validate_remind_day(
                config.reminders.bingo_remind_day, "bingo_remind_day"
            ),
            scratch=validate_remind_day(
                config.reminders.scratch_remind_day, "scratch_remind_day"
            ),
            fenek=validate_remind_day(
                config.reminders.fenek_remind_day, "fenek_remind_day"
            ),
            event=validate_remind_day(
                config.reminders.event_remind_day, "event_remind_day"
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

    def _configured_group_ids(self) -> list[str]:
        """读取并规范化配置的目标群列表：去空、去重、保持顺序。"""

        try:
            raw_group_ids = self.config.target.group_ids
        except RuntimeError:
            return []
        return _normalized_group_ids(raw_group_ids)

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


def _legacy_config_for_migration(
    config_for_normalize: Mapping[str, object],
) -> dict[str, object] | None:
    """取得旧版本（V1.0/V1.1）原配置；Runner 升级重建后从插件自身配置文件补取旧键。"""

    if _config_version(config_for_normalize) in LEGACY_CONFIG_VERSIONS:
        return deepcopy(dict(config_for_normalize))
    if not CONFIG_PATH.is_file():
        return None
    try:
        with CONFIG_PATH.open("rb") as handle:
            disk_config = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        logging.getLogger(PLUGIN_ID).warning(
            "无法读取磁盘配置以尝试旧版配置迁移，将按 Host 已提供配置继续：%s",
            exc,
        )
        return None
    return (
        disk_config if _config_version(disk_config) in LEGACY_CONFIG_VERSIONS else None
    )


def _legacy_target_group_id(legacy_config: Mapping[str, object]) -> str:
    """读取旧版配置中的单一目标群号；新版 group_ids 不在此列。"""

    target = legacy_config.get("target")
    if not isinstance(target, Mapping):
        return ""
    value = target.get("group_id")
    return value.strip() if isinstance(value, str) else ""


def _legacy_remind_days_tuple(values: object) -> tuple[int, ...]:
    """把旧版提醒天数列表规范化为去重后的正整数元组；无效项忽略。"""

    if not isinstance(values, (list, tuple)):
        return ()
    days = {
        value
        for value in values
        if isinstance(value, int) and not isinstance(value, bool) and value > 0
    }
    return tuple(sorted(days, reverse=True))


def _config_version(config: Mapping[str, object]) -> str:
    plugin_section = config.get("plugin")
    if not isinstance(plugin_section, Mapping):
        return ""
    value = plugin_section.get("config_version")
    return value.strip() if isinstance(value, str) else ""


def _migrate_config_version(config: dict[str, object]) -> bool:
    """把上一版本配置升级到当前版本：保留全部字段，只更新版本号。

    1.2.0 → 1.3.0 仅新增 command 配置节（默认空管理员），不改动
    群目标、开服日期、调度、提醒天数与赛季锚点；重复执行不再变更。
    """

    if _config_version(config) not in PREVIOUS_CONFIG_VERSIONS:
        return False
    plugin_section = config.get("plugin")
    if not isinstance(plugin_section, dict):
        return False
    plugin_section["config_version"] = CURRENT_CONFIG_VERSION
    return True


def _migrate_v1_config(
    config: dict[str, object], legacy_config: Mapping[str, object]
) -> bool:
    """把 V1 旧值写入重建后的 V1.1+ 字段。"""

    changed = False
    legacy_server = legacy_config.get("server")
    season_dates = config.get("season_dates")
    if not isinstance(season_dates, dict):
        season_dates = {}
        config["season_dates"] = season_dates
    if isinstance(legacy_server, Mapping):
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
    if not isinstance(reminders, dict):
        reminders = {}
        config["reminders"] = reminders
    if isinstance(legacy_schedule, Mapping):
        legacy_days = _legacy_remind_days_tuple(
            legacy_schedule.get("remind_days_before")
        )
        legacy_day = max(legacy_days) if legacy_days else 0
        new_fields_are_defaults = all(
            reminders.get(field_name, default) == default
            for field_name, default in _REMINDER_FIELD_DEFAULTS.items()
        )
        if (
            legacy_day
            and legacy_days != LEGACY_REMIND_DAYS_DEFAULT
            and new_fields_are_defaults
        ):
            for field_name in _REMINDER_FIELD_DEFAULTS:
                reminders[field_name] = legacy_day
            changed = True

    return changed


def _migrate_v1_1_config(
    config: dict[str, object], legacy_config: Mapping[str, object]
) -> bool:
    """把 V1.1 单目标群与列表提醒天数迁移为 V1.2 多群与单整数配置。

    旧列表表示多次提醒，新版每类别只提醒一次，取旧列表中最大的有效
    正整数以保留较早的那次提醒；无有效正整数时迁移为 0（关闭）。
    """

    changed = False

    target = config.get("target")
    if not isinstance(target, dict):
        target = {}
        config["target"] = target
    legacy_group_id = _legacy_target_group_id(legacy_config)
    if legacy_group_id:
        current_group_ids = target.get("group_ids")
        has_group_ids = isinstance(current_group_ids, list) and any(
            isinstance(item, str) and item.strip() for item in current_group_ids
        )
        if not has_group_ids:
            target["group_ids"] = [legacy_group_id]
            changed = True
    if target.pop("group_id", None) is not None:
        changed = True

    legacy_reminders = legacy_config.get("reminders")
    reminders = config.get("reminders")
    if not isinstance(reminders, dict):
        reminders = {}
        config["reminders"] = reminders
    for old_field, new_field in _REMINDER_FIELD_RENAMES.items():
        source_values = reminders.get(old_field)
        if not isinstance(source_values, (list, tuple)) and isinstance(
            legacy_reminders, Mapping
        ):
            source_values = legacy_reminders.get(old_field)
        if not isinstance(source_values, (list, tuple)):
            continue
        reminders.pop(old_field, None)
        default_day = _REMINDER_FIELD_DEFAULTS[new_field]
        if reminders.get(new_field, default_day) != default_day:
            # 新字段已有用户设置时不重复覆盖。
            continue
        legacy_days = _legacy_remind_days_tuple(source_values)
        legacy_day = max(legacy_days) if legacy_days else 0
        if reminders.get(new_field) != legacy_day:
            reminders[new_field] = legacy_day
            changed = True

    return changed


def _send_succeeded(result: object) -> bool:
    if result is True:
        return True
    return isinstance(result, Mapping) and result.get("sent") is True


def _normalized_group_ids(values: Iterable[str]) -> list[str]:
    """去空、去重并保持确定性顺序；群号保持字符串，不转数值。"""

    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        group_id = value.strip()
        if group_id and group_id not in seen:
            seen.add(group_id)
            normalized.append(group_id)
    return normalized


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
