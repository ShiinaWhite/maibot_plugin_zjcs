from __future__ import annotations

import asyncio
from collections.abc import Mapping
from contextlib import suppress
from datetime import date, datetime, time, timedelta
import logging
from pathlib import Path
from zoneinfo import ZoneInfo

from maibot_sdk import Field, MaiBotPlugin, PluginConfigBase

try:
    from .state import NotificationState, StateFileError
    from .timeline import (
        build_reminders,
        format_reminder,
        load_timeline,
        make_notification_key,
        parse_iso_date,
        validate_remind_days,
    )
except ImportError:
    from state import NotificationState, StateFileError
    from timeline import (
        build_reminders,
        format_reminder,
        load_timeline,
        make_notification_key,
        parse_iso_date,
        validate_remind_days,
    )


PLUGIN_ID = "zjcs.guild-notifier"
TIMELINE_PATH = Path(__file__).with_name("timeline_v1.json")
SEND_RETRY_DELAYS_SECONDS = (1.0, 3.0, 5.0)


class PluginSectionConfig(PluginConfigBase):
    __ui_label__ = "插件"
    __ui_icon__ = "package"
    __ui_order__ = 0

    enabled: bool = Field(default=False, description="是否启用插件")
    config_version: str = Field(default="1.0.0", description="配置版本")


class TargetConfig(PluginConfigBase):
    __ui_label__ = "通知目标"
    __ui_icon__ = "users"
    __ui_order__ = 1

    group_id: str = Field(default="", description="目标 QQ 群的稳定 group_id")


class ServerConfig(PluginConfigBase):
    __ui_label__ = "服务器"
    __ui_icon__ = "calendar"
    __ui_order__ = 2

    open_date: str = Field(default="", description="服务器开服日期，格式 YYYY-MM-DD")
    season_anchor_dates: dict[str, str] = Field(
        default_factory=dict,
        description="赛季锚点日期，键为 S4、S5 等赛季编号",
    )


class ScheduleConfig(PluginConfigBase):
    __ui_label__ = "调度"
    __ui_icon__ = "clock"
    __ui_order__ = 3

    daily_check_time: str = Field(
        default="09:00", description="每日检查时间，格式 HH:MM"
    )
    timezone: str = Field(default="Asia/Shanghai", description="每日检查使用的时区")
    remind_days_before: list[int] = Field(
        default_factory=lambda: [2, 1],
        description="提前通知天数，例如 [2, 1]",
    )


class ZjcsGuildNotifierConfig(PluginConfigBase):
    plugin: PluginSectionConfig = Field(default_factory=PluginSectionConfig)
    target: TargetConfig = Field(default_factory=TargetConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)


class ZjcsGuildNotifier(MaiBotPlugin):
    """《杖剑传说》公会时间线的确定性每日通知。"""

    config_model = ZjcsGuildNotifierConfig

    def __init__(self) -> None:
        super().__init__()
        self._daily_task: asyncio.Task[None] | None = None
        self._logger = logging.getLogger(PLUGIN_ID)

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

            if not config.server.open_date.strip():
                self._logger.error(
                    "插件配置无效：server.open_date 不能为空；本轮通知已停止"
                )
                return
            try:
                open_date = parse_iso_date(config.server.open_date, "server.open_date")
                remind_days = validate_remind_days(config.schedule.remind_days_before)
                season_anchor_dates = {
                    season: parse_iso_date(
                        anchor, f"server.season_anchor_dates.{season}"
                    )
                    for season, anchor in config.server.season_anchor_dates.items()
                    if anchor
                }
            except (TypeError, ValueError) as exc:
                self._logger.error("插件配置无效：%s；本轮通知已停止", exc)
                return

            group_id = config.target.group_id.strip()
            if not group_id:
                self._logger.warning("插件已启用，但尚未配置 target.group_id")
                return

            timeline = load_timeline(TIMELINE_PATH)
            reminders = build_reminders(
                timeline,
                today=today,
                open_date=open_date,
                season_anchor_dates=season_anchor_dates,
                remind_days_before=remind_days,
            )
        except (OSError, TypeError, ValueError, RuntimeError) as exc:
            self._logger.error("每日时间线检查失败：%s", exc)
            return

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
            return

        try:
            stream_id = await self._resolve_group_stream(group_id)
        except Exception as exc:
            self._logger.error("目标 QQ 群解析失败，本次跳过发送：%s", exc)
            return

        for reminder in pending:
            message = format_reminder(reminder)
            key = make_notification_key(
                reminder.event_id,
                reminder.event_date,
                reminder.remind_days_before,
            )
            if not await self._send_reminder_with_retry(message, stream_id):
                continue

            try:
                state.mark_sent(key)
            except StateFileError as exc:
                self._logger.error(
                    "通知已发送但状态写入失败，将停止本次剩余发送：%s",
                    exc,
                )
                return

    async def _send_reminder_with_retry(self, message: str, stream_id: str) -> bool:
        """在单条提醒内有限重试，直到成功或耗尽短时重试次数。"""

        total_attempts = len(SEND_RETRY_DELAYS_SECONDS) + 1
        for attempt in range(total_attempts):
            if attempt:
                await asyncio.sleep(SEND_RETRY_DELAYS_SECONDS[attempt - 1])

            try:
                result = await self.ctx.send.text(
                    message,
                    stream_id,
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

    async def _resolve_group_stream(self, group_id: str) -> str:
        streams_result = await self.ctx.chat.get_group_streams(platform="qq")
        streams = _extract_group_streams(streams_result)
        if stream_id := _select_group_stream_id(streams, group_id):
            return stream_id

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
        return stream_id

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


def _select_group_stream_id(
    streams: list[Mapping[str, object]], group_id: str
) -> str | None:
    """按路由元数据优先级选择目标群已有 stream。"""

    normalized_group_id = group_id.strip()
    candidates: list[tuple[int, str]] = []
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
        candidates.append((priority, stream_id))

    if not candidates:
        return None

    # 同一优先级不使用 SDK 返回顺序或非路由字段猜测，采用稳定的 stream_id tie-break。
    candidates.sort(key=lambda candidate: (-candidate[0], candidate[1]))
    return candidates[0][1]


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
