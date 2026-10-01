from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from maibot_sdk.config import generate_plugin_config_schema, rebuild_plugin_config_data
import pytest

import plugin
from plugin import ZjcsGuildNotifier
from state import NotificationState, StateFileError
from test_plugin import make_config, make_context
from timeline import (
    SeasonPreparation,
    build_season_preparations,
    format_season_preparation,
    load_timeline,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")
START = datetime(2026, 10, 10, 8, tzinfo=SHANGHAI)
DUE = START - timedelta(hours=36)
OPEN = date(2026, 6, 19)


def preparations(*, raw=START.isoformat(), timeline=None, anchors=None):
    return build_season_preparations(
        load_timeline("timeline_v1.json") if timeline is None else timeline,
        open_date=OPEN,
        season_anchor_dates=anchors or {},
        start_datetimes={"S3": raw},
        calendar_timezone=SHANGHAI,
    )


def test_exact_36_hours_and_half_open_catchup_window():
    item = preparations()[0]
    assert item.remind_at.astimezone(SHANGHAI) == DUE
    assert DUE.isoformat() == "2026-10-08T20:00:00+08:00"
    assert not item.is_due(DUE - timedelta(microseconds=1))
    assert item.is_due(DUE)
    assert item.is_due(START - timedelta(microseconds=1))
    assert not item.is_due(START)
    assert not item.is_due(START + timedelta(days=1))
    with pytest.raises(ValueError):
        item.is_due(DUE.replace(tzinfo=None))


def test_equivalent_offsets_have_same_key_and_date_is_local():
    item = preparations()[0]
    utc = preparations(raw="2026-10-10T00:00:00Z")[0]
    assert item.notification_key == utc.notification_key
    assert item.remind_at == datetime(2026, 10, 8, 12, tzinfo=timezone.utc)
    # UTC date differs, but Shanghai date agrees with the timeline.
    shifted = preparations(raw="2026-10-09T23:00:00Z")[0]
    assert shifted.starts_at.hour == 7
    assert shifted.notification_key != item.notification_key


def test_elapsed_36_hours_across_dst():
    start = datetime(2026, 11, 1, 8, tzinfo=ZoneInfo("America/New_York"))
    item = SeasonPreparation("test", "S4", start)
    assert start.timestamp() - item.remind_at.timestamp() == 36 * 3600
    assert item.remind_at.astimezone(start.tzinfo).hour == 21
    assert item.is_due(item.remind_at.astimezone(start.tzinfo))


@pytest.mark.parametrize(
    "raw", ["", "bad", "2026-10-10", "2026-10-10T08:00:00", "2026-10-11T08:00:00+08:00"]
)
def test_unconfirmed_or_conflicting_time_fails_closed(raw):
    assert preparations(raw=raw) == []


@pytest.mark.parametrize(
    "change",
    [{"status": "pending"}, {"server_day": None}, {"event_date": "2026-10-10"}],
)
def test_unreliable_or_ambiguous_date_fails_closed(change):
    timeline = load_timeline("timeline_v1.json")
    event = next(e for e in timeline["events"] if e["id"] == "season_s3_start")
    event.update(change)
    assert preparations(timeline=timeline) == []


def test_duplicate_season_and_unknown_later_anchor_fail_closed():
    timeline = load_timeline("timeline_v1.json")
    event = next(e for e in timeline["events"] if e["id"] == "season_s3_start")
    timeline["events"].append(deepcopy(event))
    assert preparations(timeline=timeline) == []
    data = load_timeline("timeline_v1.json")
    kwargs = dict(
        timeline=data,
        open_date=OPEN,
        calendar_timezone=SHANGHAI,
        start_datetimes={"S4": "2026-12-01T10:30:00+08:00"},
    )
    assert build_season_preparations(**kwargs, season_anchor_dates={}) == []
    items = build_season_preparations(
        **kwargs, season_anchor_dates={"S4": date(2026, 12, 1)}
    )
    assert len(items) == 1
    assert items[0].starts_at.hour == 10  # No universal 08:00 rule.


def test_advisory_text_accounts_for_delayed_receipt():
    item = preparations()[0]
    exact = format_season_preparation(item, now=DUE)
    late = format_season_preparation(item, now=START - timedelta(hours=2))
    assert "约 36.0 小时" in exact
    assert "如果本赛季当前目标已经完成，可以考虑" in exact
    assert "小床经验" in exact
    assert "约 2.0 小时" in late
    assert "延迟收到时可预留时间会缩短" in late
    assert "先推" not in exact and "必须" not in exact


def frozen_clock(monkeypatch, initial=DUE):
    class Clock(datetime):
        current = initial

        @classmethod
        def now(cls, tz=None):
            return cls.current.astimezone(tz)

    monkeypatch.setattr(plugin, "datetime", Clock)
    return Clock


def instance_for(tmp_path, *, groups=None, send_result=None):
    config = make_config()
    config["server"]["open_date"] = OPEN.isoformat()
    if groups:
        config["target"]["group_ids"] = groups
    config["season_preparation"] = {
        "enabled": True,
        "start_times": [{"season": "S3", "start_datetime": START.isoformat()}],
    }
    instance = ZjcsGuildNotifier()
    instance._ctx = make_context(
        tmp_path, send_result={"sent": True} if send_result is None else send_result
    )
    instance.set_plugin_config(config)
    return instance


def test_sdk_schema_and_1_4_migration_preserve_configuration():
    raw = make_config()
    old = deepcopy(raw)
    normalized, changed = ZjcsGuildNotifier().normalize_plugin_config(raw)
    assert changed
    rebuilt = rebuild_plugin_config_data(
        ZjcsGuildNotifier().get_default_config(), normalized
    )
    for section, values in old.items():
        if section != "plugin":
            assert rebuilt[section] == values
    assert rebuilt["plugin"] == {"enabled": True, "config_version": "1.5.0"}
    assert rebuilt["season_preparation"] == {"enabled": True, "start_times": []}
    raw["season_preparation"] = {
        "enabled": False,
        "start_times": [
            {"season": "S3", "start_datetime": START.isoformat()},
            {"season": "S4", "start_datetime": "2026-12-01T10:30:00+08:00"},
        ],
    }
    normalized, _ = ZjcsGuildNotifier().normalize_plugin_config(raw)
    assert (
        rebuild_plugin_config_data(
            ZjcsGuildNotifier().get_default_config(), normalized
        )["season_preparation"]
        == raw["season_preparation"]
    )
    field = generate_plugin_config_schema(plugin.ZjcsGuildNotifierConfig)["sections"][
        "season_preparation"
    ]["fields"]["start_times"]
    assert field["type"] == "array" and field["item_type"] == "object"
    normalized_again, changed_again = ZjcsGuildNotifier().normalize_plugin_config(
        normalized
    )
    assert normalized_again == normalized and not changed_again


def test_duplicate_config_records_and_conflicting_anchor_do_not_schedule(tmp_path):
    instance = instance_for(tmp_path)
    config = instance.config.model_dump()
    config["season_preparation"]["start_times"] *= 2
    instance.set_plugin_config(config)
    assert instance._configured_season_preparations() == []
    config["season_preparation"]["start_times"] = [
        {"season": "S4", "start_datetime": "2026-12-01T08:00:00+08:00"}
    ]
    config["season_dates"]["s4_start_date"] = "2026-12-02"
    instance.set_plugin_config(config)
    assert instance._configured_season_preparations() == []


@pytest.mark.asyncio
async def test_restart_dedupe_and_history_preserved(tmp_path, monkeypatch):
    frozen_clock(monkeypatch)
    state = NotificationState(tmp_path / NotificationState.FILE_NAME).load()
    state.mark_sent_many("123456", ["old:dungeon:key", "old:event:key"])
    first = instance_for(tmp_path)
    await first._run_season_preparation_check()
    await first._run_season_preparation_check()
    assert len(first.ctx.send.calls) == 1
    restarted = instance_for(tmp_path)
    await restarted._run_season_preparation_check()
    assert restarted.ctx.send.calls == []
    state.load()
    assert state.keys("123456") == {
        "old:dungeon:key",
        "old:event:key",
        preparations()[0].notification_key,
    }
    assert NotificationState.VERSION == 2


@pytest.mark.asyncio
async def test_partial_failure_retries_only_unsent_group(tmp_path, monkeypatch):
    frozen_clock(monkeypatch)

    async def no_wait(_):
        pass

    monkeypatch.setattr(plugin.asyncio, "sleep", no_wait)
    instance = instance_for(
        tmp_path,
        groups=["1", "2"],
        send_result=[{"sent": True}] + [{"sent": False}] * 4,
    )
    await instance._run_season_preparation_check()
    state = NotificationState(tmp_path / NotificationState.FILE_NAME).load()
    key = preparations()[0].notification_key
    assert state.contains("1", key) and not state.contains("2", key)
    assert len(instance.ctx.send.calls) == 5
    restarted = instance_for(tmp_path, groups=["1", "2"])
    await restarted._run_season_preparation_check()
    assert len(restarted.ctx.send.calls) == 1
    assert restarted.ctx.chat.calls[0]["group_id"] == "2"
    assert state.load().contains("2", key)


@pytest.mark.asyncio
async def test_state_write_retry_does_not_resend_in_same_process(tmp_path, monkeypatch):
    frozen_clock(monkeypatch)
    instance = instance_for(tmp_path)
    original = NotificationState.mark_sent_many

    def fail(*args):
        raise StateFileError("disk unavailable")

    monkeypatch.setattr(NotificationState, "mark_sent_many", fail)
    await instance._run_season_preparation_check()
    await instance._run_season_preparation_check()
    assert len(instance.ctx.send.calls) == 1
    monkeypatch.setattr(NotificationState, "mark_sent_many", original)
    await instance._run_season_preparation_check()
    assert len(instance.ctx.send.calls) == 1
    assert (
        NotificationState(tmp_path / NotificationState.FILE_NAME)
        .load()
        .contains("123456", preparations()[0].notification_key)
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "when", [DUE - timedelta(seconds=1), START, START + timedelta(days=2)]
)
async def test_before_window_and_expired_do_not_send_or_write(
    tmp_path, monkeypatch, when
):
    frozen_clock(monkeypatch, when)
    instance = instance_for(tmp_path)
    await instance._run_season_preparation_check()
    assert instance.ctx.send.calls == []
    assert not (tmp_path / NotificationState.FILE_NAME).exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "section,field,value",
    [
        ("plugin", "enabled", False),
        ("season_preparation", "enabled", False),
        ("season_preparation", "start_times", []),
    ],
)
async def test_disabled_or_unconfigured_no_generation(
    tmp_path, monkeypatch, section, field, value
):
    frozen_clock(monkeypatch)
    instance = instance_for(tmp_path)
    data = instance.config.model_dump()
    data[section][field] = value
    instance.set_plugin_config(data)
    assert instance._configured_season_preparations() == []
    await instance._run_season_preparation_check()
    assert instance.ctx.send.calls == []
    assert not (tmp_path / NotificationState.FILE_NAME).exists()


@pytest.mark.asyncio
async def test_corrupt_state_fails_closed(tmp_path, monkeypatch):
    frozen_clock(monkeypatch)
    path = tmp_path / NotificationState.FILE_NAME
    path.write_text("corrupt", encoding="utf-8")
    instance = instance_for(tmp_path)
    await instance._run_season_preparation_check()
    assert instance.ctx.send.calls == []
    assert path.read_text() == "corrupt"


@pytest.mark.asyncio
async def test_retry_expiry_prevents_late_send(tmp_path, monkeypatch):
    clock = frozen_clock(monkeypatch, START - timedelta(seconds=1))

    async def advance(_):
        clock.current = START

    monkeypatch.setattr(plugin.asyncio, "sleep", advance)
    instance = instance_for(tmp_path, send_result={"sent": False})
    await instance._run_season_preparation_check()
    assert len(instance.ctx.send.calls) == 1
    assert not (tmp_path / NotificationState.FILE_NAME).exists()


@pytest.mark.asyncio
async def test_stream_resolution_crossing_expiry_prevents_send(tmp_path, monkeypatch):
    clock = frozen_clock(monkeypatch, START - timedelta(seconds=1))
    instance = instance_for(tmp_path)
    original = instance._resolve_group_stream

    async def slow(group):
        result = await original(group)
        clock.current = START
        return result

    monkeypatch.setattr(instance, "_resolve_group_stream", slow)
    await instance._run_season_preparation_check()
    assert instance.ctx.send.calls == []


@pytest.mark.asyncio
async def test_second_group_not_sent_after_first_delivery_crosses_start(
    tmp_path, monkeypatch
):
    clock = frozen_clock(monkeypatch, START - timedelta(seconds=1))
    instance = instance_for(tmp_path, groups=["1", "2"])
    original = instance.ctx.send.text

    async def slow(*args, **kwargs):
        result = await original(*args, **kwargs)
        clock.current = START
        return result

    monkeypatch.setattr(instance.ctx.send, "text", slow)
    await instance._run_season_preparation_check()
    assert len(instance.ctx.send.calls) == 1
    state = NotificationState(tmp_path / NotificationState.FILE_NAME).load()
    assert state.contains("1", preparations()[0].notification_key)
    assert not state.contains("2", preparations()[0].notification_key)


@pytest.mark.asyncio
async def test_unload_cancels_precise_retry_without_recording(tmp_path, monkeypatch):
    import asyncio

    frozen_clock(monkeypatch)
    instance = instance_for(tmp_path)
    entered = asyncio.Event()

    async def blocked(*args, **kwargs):
        entered.set()
        await asyncio.Future()

    monkeypatch.setattr(instance, "_send_text_with_retry", blocked)
    instance._start_daily_task()
    await asyncio.wait_for(entered.wait(), timeout=1)
    await instance.on_unload()
    assert instance._daily_task is None
    assert not (tmp_path / NotificationState.FILE_NAME).exists()


@pytest.mark.asyncio
async def test_daily_09_and_precise_20_coexist_in_one_loop(tmp_path, monkeypatch):
    clock = frozen_clock(monkeypatch, DUE.replace(hour=8, minute=59))
    instance = instance_for(tmp_path)
    daily = []
    sleeps = []

    async def run_daily(*, today):
        daily.append((today, clock.current))

    async def advance(seconds):
        sleeps.append(seconds)
        clock.current += timedelta(seconds=seconds)
        if clock.current >= DUE + timedelta(minutes=1):
            raise plugin.asyncio.CancelledError

    monkeypatch.setattr(instance, "_run_daily_check", run_daily)
    monkeypatch.setattr(plugin.asyncio, "sleep", advance)
    with pytest.raises(plugin.asyncio.CancelledError):
        await instance._daily_schedule_loop()
    assert daily == [(DUE.date(), DUE.replace(hour=9))]
    assert len(instance.ctx.send.calls) == 1
    assert "36.0 小时" in instance.ctx.send.calls[0][0]
    assert sleeps == [60, 11 * 3600, 13 * 3600]


@pytest.mark.asyncio
async def test_wakes_at_exact_second_not_next_minute(tmp_path, monkeypatch):
    clock = frozen_clock(monkeypatch, DUE - timedelta(seconds=17))
    instance = instance_for(tmp_path)
    sleeps = []

    async def advance(seconds):
        sleeps.append(seconds)
        clock.current += timedelta(seconds=seconds)
        if len(sleeps) == 2:
            raise plugin.asyncio.CancelledError

    async def no_daily(**kwargs):
        pass

    monkeypatch.setattr(instance, "_run_daily_check", no_daily)
    monkeypatch.setattr(plugin.asyncio, "sleep", advance)
    with pytest.raises(plugin.asyncio.CancelledError):
        await instance._daily_schedule_loop()
    assert sleeps[0] == 17
    assert sleeps[1] == 13 * 3600  # Persisted success needs no minute polling.
    assert len(instance.ctx.send.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "initial,expected_wake",
    [
        (DUE - timedelta(days=2), DUE.replace(hour=9) - timedelta(days=1)),
        (DUE.replace(hour=9), DUE),
    ],
)
async def test_before_window_waits_for_earlier_daily_or_precise_node(
    tmp_path, monkeypatch, initial, expected_wake
):
    frozen_clock(monkeypatch, initial)
    instance = instance_for(tmp_path)
    sleeps = []

    async def no_daily(**kwargs):
        pass

    async def stop(seconds):
        sleeps.append(seconds)
        raise plugin.asyncio.CancelledError

    monkeypatch.setattr(instance, "_run_daily_check", no_daily)
    monkeypatch.setattr(plugin.asyncio, "sleep", stop)
    with pytest.raises(plugin.asyncio.CancelledError):
        await instance._daily_schedule_loop()
    assert sleeps == [(expected_wake - initial).total_seconds()]
    assert sleeps[0] > 60
    assert instance.ctx.send.calls == []


@pytest.mark.asyncio
async def test_partial_failure_ticks_once_then_returns_to_long_wait(
    tmp_path, monkeypatch
):
    clock = frozen_clock(monkeypatch)
    instance = instance_for(
        tmp_path,
        groups=["1", "2"],
        send_result=[{"sent": True}] + [{"sent": False}] * 4 + [{"sent": True}],
    )
    sleeps = []

    async def no_daily(**kwargs):
        pass

    async def advance(seconds):
        sleeps.append(seconds)
        if seconds > 60:
            raise plugin.asyncio.CancelledError
        clock.current += timedelta(seconds=seconds)

    monkeypatch.setattr(instance, "_run_daily_check", no_daily)
    monkeypatch.setattr(plugin.asyncio, "sleep", advance)
    with pytest.raises(plugin.asyncio.CancelledError):
        await instance._daily_schedule_loop()
    assert sleeps[:4] == [1, 3, 5, 60]
    assert len(sleeps) == 5 and sleeps[-1] > 60
    assert len(instance.ctx.send.calls) == 6
    assert [call["group_id"] for call in instance.ctx.chat.calls] == ["1"] + ["2"] * 5
    state = NotificationState(tmp_path / NotificationState.FILE_NAME).load()
    assert all(
        state.contains(group, preparations()[0].notification_key)
        for group in ["1", "2"]
    )


@pytest.mark.asyncio
async def test_state_write_failure_ticks_without_resending_then_stops(
    tmp_path, monkeypatch
):
    clock = frozen_clock(monkeypatch)
    instance = instance_for(tmp_path)
    original = NotificationState.mark_sent_many
    writes = []
    sleeps = []

    def flaky_write(state, group, keys):
        writes.append(clock.current)
        if len(writes) <= 2:
            raise StateFileError("disk unavailable")
        return original(state, group, keys)

    async def no_daily(**kwargs):
        pass

    async def advance(seconds):
        sleeps.append(seconds)
        if seconds > 60:
            raise plugin.asyncio.CancelledError
        clock.current += timedelta(seconds=seconds)

    monkeypatch.setattr(NotificationState, "mark_sent_many", flaky_write)
    monkeypatch.setattr(instance, "_run_daily_check", no_daily)
    monkeypatch.setattr(plugin.asyncio, "sleep", advance)
    with pytest.raises(plugin.asyncio.CancelledError):
        await instance._daily_schedule_loop()
    assert writes == [DUE, DUE + timedelta(seconds=60), DUE + timedelta(seconds=120)]
    assert sleeps == [60, 60, 13 * 3600 - 120]
    assert len(instance.ctx.send.calls) == 1
    state = NotificationState(tmp_path / NotificationState.FILE_NAME).load()
    assert state.contains("123456", preparations()[0].notification_key)


@pytest.mark.asyncio
async def test_pending_retry_wakes_at_expiry_and_stops_all_work(tmp_path, monkeypatch):
    clock = frozen_clock(monkeypatch, START - timedelta(seconds=90))
    instance = instance_for(tmp_path)
    writes = []
    sleeps = []

    def fail(*args):
        writes.append(clock.current)
        raise StateFileError("disk unavailable")

    async def no_daily(**kwargs):
        pass

    async def advance(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 3:
            raise plugin.asyncio.CancelledError
        clock.current += timedelta(seconds=seconds)

    monkeypatch.setattr(NotificationState, "mark_sent_many", fail)
    monkeypatch.setattr(instance, "_run_daily_check", no_daily)
    monkeypatch.setattr(plugin.asyncio, "sleep", advance)
    with pytest.raises(plugin.asyncio.CancelledError):
        await instance._daily_schedule_loop()
    assert sleeps == [60, 30, 3600]
    assert writes == [START - timedelta(seconds=90), START - timedelta(seconds=30)]
    assert clock.current == START
    assert len(instance.ctx.send.calls) == 1


@pytest.mark.asyncio
async def test_config_update_interrupts_long_wait_and_adds_new_group(
    tmp_path, monkeypatch
):
    import asyncio

    frozen_clock(monkeypatch)
    instance = instance_for(tmp_path, groups=["1"])
    sleeping = asyncio.Queue()

    async def no_daily(**kwargs):
        pass

    async def block(seconds):
        sleeping.put_nowait(seconds)
        await asyncio.Future()

    monkeypatch.setattr(instance, "_run_daily_check", no_daily)
    monkeypatch.setattr(plugin.asyncio, "sleep", block)
    instance._start_daily_task()
    try:
        assert await asyncio.wait_for(sleeping.get(), timeout=1) > 60
        first_task = instance._daily_task
        config = instance.config.model_dump()
        config["target"]["group_ids"] = ["1", "2"]
        instance.set_plugin_config(config)
        await instance.on_config_update("self", config, "1.5.0")
        assert await asyncio.wait_for(sleeping.get(), timeout=1) > 60
        assert first_task.cancelled()
        assert instance._daily_task is not first_task
        assert [call["group_id"] for call in instance.ctx.chat.calls] == ["1", "2"]
        state = NotificationState(tmp_path / NotificationState.FILE_NAME).load()
        assert all(
            state.contains(group, preparations()[0].notification_key)
            for group in ["1", "2"]
        )
    finally:
        await instance.on_unload()


@pytest.mark.asyncio
async def test_tool_with_precise_config_remains_read_only(tmp_path, monkeypatch):
    frozen_clock(monkeypatch)
    instance = instance_for(tmp_path)
    state = NotificationState(tmp_path / NotificationState.FILE_NAME).load()
    state.mark_sent("123456", "history")
    before = state.path.read_bytes()
    result = await instance.query_zjcs_facts(query="next_dungeon")
    assert result["success"]
    assert state.path.read_bytes() == before
    assert instance.ctx.send.calls == []
