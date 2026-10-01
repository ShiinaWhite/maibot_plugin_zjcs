"""Opt-in RC acceptance: real Core/Runner IPC and optional live LLM tool loop.

Run with MaiBot's Python environment. Core is exported from its Git HEAD to a
private temporary directory; its canonical config/data/source are never loaded.
No production connection or message gateway is configured; reminder targets are empty.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile

PLUGIN_ID = "zjcs.guild-notifier"
RELEASE_FILES = (
    "_manifest.json",
    "plugin.py",
    "timeline.py",
    "state.py",
    "timeline_v1.json",
)


def prepare(args: argparse.Namespace) -> int:
    core = args.core_root.resolve()
    workspace = Path(__file__).resolve().parents[1]
    root = Path(tempfile.mkdtemp(prefix="zjcs-rc020-"))
    revision = subprocess.check_output(
        ["git", "-C", str(core), "rev-parse", "HEAD"], text=True
    ).strip()
    archive = subprocess.check_output(
        [
            "git",
            "-C",
            str(core),
            "archive",
            "HEAD",
            "src",
            "prompts",
            "locales",
            "depends-data",
            "pyproject.toml",
        ]
    )
    with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
        bundle.extractall(root, filter="data")
    plugin_dir = root / "plugins" / "zjcs_guild_notifier"
    plugin_dir.mkdir(parents=True)
    hashes = {}
    for name in RELEASE_FILES:
        source = workspace / name
        shutil.copyfile(source, plugin_dir / name)
        hashes[name] = hashlib.sha256(source.read_bytes()).hexdigest()
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    open_date = today - timedelta(days=87)
    (plugin_dir / "config.toml").write_text(
        '[plugin]\nenabled = true\nconfig_version = "1.4.0"\n'
        f'[server]\nopen_date = "{open_date.isoformat()}"\n[target]\ngroup_ids = []\n',
        encoding="utf-8",
    )
    report = {
        "core_commit": revision,
        "sdk_version": importlib.metadata.version("maibot-plugin-sdk"),
        "plugin_version": json.loads(
            (plugin_dir / "_manifest.json").read_text(encoding="utf-8")
        )["version"],
        "plugin_sha256": hashes,
        "test_date": today.isoformat(),
        "test_open_date": open_date.isoformat(),
        "runner": "pending",
        "rpc": [],
        "llm": [],
    }
    (root / "acceptance.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    env = os.environ.copy()
    env.update(
        PYTHONPATH=str(root), PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8"
    )
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker-root",
        str(root),
    ]
    if args.llm:
        command.append("--llm")
    if args.model_name:
        command.extend(["--model-name", args.model_name])
    print(f"Isolated acceptance directory: {root}", flush=True)
    # Detailed framework output stays local; only the curated JSON is reported.
    try:
        if args.model_config:
            (root / "config").mkdir()
            # Credentials stay in the user's private temp directory, never in
            # Git, command arguments, result reports or model prompts.
            shutil.copyfile(args.model_config, root / "config" / "model_config.toml")
        with (root / "acceptance-process.log").open("w", encoding="utf-8") as log:
            process = subprocess.run(command, cwd=root, env=env, stdout=log, stderr=log)
    finally:
        if args.model_config:
            (root / "config" / "model_config.toml").unlink(missing_ok=True)
    result = json.loads((root / "acceptance.json").read_text(encoding="utf-8"))
    print(
        json.dumps(
            {
                "runner": result["runner"],
                "status": result.get("status"),
                "rpc_passed": len(result["rpc"]),
                "llm_passed": sum(item["status"] == "passed" for item in result["llm"]),
                "llm_model": result.get("llm_model"),
                "error_type": result.get("error_type"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )
    print(f"Report: {root / 'acceptance.json'}", flush=True)
    return process.returncode


async def validate(root: Path, live_llm: bool, selected_model: str | None) -> None:
    # Imported only inside the isolated source export.
    from src.config.config import config_manager
    from src.core.tooling import (
        ToolAvailabilityContext,
        ToolExecutionContext,
        ToolInvocation,
        ToolRegistry,
    )
    from src.plugin_runtime.host.supervisor import PluginRunnerSupervisor
    from src.plugin_runtime.integration import get_plugin_runtime_manager
    from src.plugin_runtime.tool_provider import PluginToolProvider

    report_path = root / "acceptance.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))

    def save() -> None:
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    supervisor = PluginRunnerSupervisor(
        plugin_dirs=[root / "plugins"],
        plugin_type_filter="not_adapter",
        health_check_interval_sec=60,
        runner_spawn_timeout_sec=30,
    )
    manager = get_plugin_runtime_manager()
    # Bind the real test Supervisor to Core's normal component lookup. The
    # full bot Manager is not started (no Platform IO or other plugins).
    manager._third_party_supervisor = supervisor
    registry = ToolRegistry()
    registry.register_provider(PluginToolProvider())
    context = ToolExecutionContext(
        session_id="rc-query-test",
        stream_id="rc-query-test",
        is_group_chat=True,
        group_id="rc-test-group",
        user_id="rc-test-user",
        platform="qq",
    )
    try:
        await supervisor.start()
        assert supervisor.get_loaded_plugin_versions().get(PLUGIN_ID) == "0.2.0"
        specs = await registry.list_tools(
            ToolAvailabilityContext(
                session_id=context.session_id,
                is_group_chat=True,
                group_id=context.group_id,
                platform="qq",
            )
        )
        spec = next(item for item in specs if item.name == "zjcs_query")
        assert spec.metadata["visibility"] == "visible"
        assert spec.parameters_schema["required"] == ["query"]
        report.update(
            runner="passed",
            core_tool_visible=True,
            registered_tool=spec.to_llm_definition(),
        )
        save()
        today = date.fromisoformat(report["test_date"])
        dungeon_date = (today + timedelta(days=11)).isoformat()
        season_date = (today + timedelta(days=26)).isoformat()
        queries = [
            ({"query": "next_dungeon"}, dungeon_date),
            ({"query": "next_weekly_activity", "activity": "宾果抽抽乐"}, dungeon_date),
            ({"query": "next_season"}, season_date),
        ]
        for arguments, expected_date in queries:
            result = await registry.invoke(
                ToolInvocation(tool_name="zjcs_query", arguments=arguments), context
            )
            assert result.success
            facts = result.structured_content["facts"]
            assert facts["as_of"] == report["test_date"]
            assert facts["data"]["event_date"] == expected_date
            assert json.loads(result.get_history_content()) == facts
            report["rpc"].append(
                {"arguments": arguments, "status": "passed", "facts": facts}
            )
            save()
        if live_llm:
            from src.llm_models.utils_model import LLMOrchestrator
            from src.llm_models.payload_content.context_item import (
                ContextItemBuilder,
                ContextItemMeta,
                RoleType,
                bind_output_items_to_turn,
            )

            def message(role, text):
                return (
                    ContextItemBuilder().set_role(role).add_text_content(text).build()
                )

            llm = LLMOrchestrator(
                task_name="planner", request_type="rc_query_acceptance"
            )
            model_name = (
                selected_model
                or (
                    config_manager.get_model_config().model_task_config.planner.model_list[
                        0
                    ]
                )
            )
            report["llm_model"] = model_name
            prompts = [
                ("下一个副本什么时候？", "next_dungeon", None, dungeon_date),
                (
                    "下一次宾果什么时候？",
                    "next_weekly_activity",
                    "宾果抽抽乐",
                    dungeon_date,
                ),
                ("赛季什么时候更新？", "next_season", None, season_date),
            ]
            for prompt, topic, activity, expected in prompts:
                item = {"prompt": prompt, "status": "pending"}
                report["llm"].append(item)
                save()
                history = [
                    message(
                        RoleType.System,
                        "你是《杖剑传说》公会助手。对游戏日期和进度问题，先查询可靠事实，"
                        "不得猜测；拿到事实后用中文回答，并包含实际日期和距离天数。"
                        f"未知就说明不知道。本测试当前日期为{today.isoformat()}。",
                    ),
                    message(RoleType.User, prompt),
                ]
                first = await asyncio.wait_for(
                    llm.generate_response_with_context_async(
                        lambda *args, **kwargs: history,
                        tools=[spec.to_llm_definition()],
                        max_tokens=2048,
                        model_name=model_name,
                        session_id=context.session_id,
                    ),
                    timeout=90,
                )
                calls = first.tool_calls or []
                assert calls, "LLM did not select a tool"
                turn_id = f"rc-{topic}"
                history.extend(bind_output_items_to_turn(first.output_items, turn_id))
                recorded = []
                for call in calls:
                    assert call.func_name == "zjcs_query"
                    assert call.args.get("query") == topic
                    assert call.args.get("activity") == activity
                    result = await registry.invoke(
                        ToolInvocation(
                            tool_name=call.func_name,
                            arguments=call.args,
                            call_id=call.call_id,
                        ),
                        context,
                    )
                    assert result.success
                    assert (
                        result.structured_content["facts"]["data"]["event_date"]
                        == expected
                    )
                    recorded.append({"name": call.func_name, "arguments": call.args})
                    history.append(
                        ContextItemBuilder()
                        .set_meta(ContextItemMeta.create(logical_turn_id=turn_id))
                        .set_role(RoleType.Tool)
                        .set_tool_call_id(call.call_id)
                        .set_tool_name(call.func_name)
                        .add_text_content(result.get_history_content())
                        .build()
                    )
                second = await asyncio.wait_for(
                    llm.generate_response_with_context_async(
                        lambda *args, **kwargs: history,
                        tools=[spec.to_llm_definition()],
                        max_tokens=2048,
                        model_name=model_name,
                        session_id=context.session_id,
                    ),
                    timeout=90,
                )
                assert not second.tool_calls
                assert second.response
                # Require the tool's date in the answer; do not grade style.
                expected_day = date.fromisoformat(expected)
                date_text = f"{expected_day.month}月{expected_day.day}"
                assert (
                    expected in second.response
                    or date_text in second.response.replace(" ", "")
                )
                days_text = f"{(expected_day - today).days}天"
                assert days_text in second.response.replace(" ", "").replace("**", "")
                item.update(status="passed", calls=recorded, answer=second.response)
                save()
        assert not list((root / "data").rglob("notification_state.json"))
        assert (root / "plugins" / "zjcs_guild_notifier" / "config.toml").read_text(
            encoding="utf-8"
        ).find("enabled = true") >= 0
        report["notification_state_created"] = False
        report["status"] = "passed"
        save()
    except Exception as exc:
        # Error class only: framework exceptions can contain provider endpoints.
        report.update(status="failed", error_type=type(exc).__name__)
        save()
        raise
    finally:
        await supervisor.stop()
        manager._third_party_supervisor = None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core-root", type=Path)
    parser.add_argument("--model-config", type=Path)
    parser.add_argument("--llm", action="store_true")
    parser.add_argument(
        "--model-name", help="Existing configured model; defaults to planner"
    )
    parser.add_argument("--worker-root", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker_root:
        asyncio.run(validate(args.worker_root.resolve(), args.llm, args.model_name))
        return 0
    if args.core_root is None or (args.llm and args.model_config is None):
        parser.error(
            "--core-root required; live LLM also requires a private --model-config"
        )
    return prepare(args)


if __name__ == "__main__":
    raise SystemExit(main())
