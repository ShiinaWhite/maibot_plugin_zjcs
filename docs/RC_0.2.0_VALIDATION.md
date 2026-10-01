# 0.2.0 Release Candidate 验收记录

验收日期：2026-10-01。候选 plugin id：`zjcs.guild-notifier`，版本：`0.2.0`。

## 本轮范围

外部 Review 通过的 feature commit `b722e123739b2c8be286b5f95fcbc161e441aa83` 通过 `--no-ff` merge 合入 main（merge commit `dc16320`），保留原 feature 历史。本轮只更新 manifest 版本与说明、RC 文档、版本断言，并增加可复现的受控运行时验收脚本及事实记录。

没有修改已 Review 的 `plugin.py` / `timeline.py` / `state.py` / `timeline_v1.json` / `config.example.toml`。command、自动提醒、dedupe、config `1.4.0`、notification state `2` 保持兼容，无配置或状态迁移。没有插件 runtime 修复，也没有修改 MaiBot Core。

## 真实 Runner / Core / RPC

使用本地 MaiBot Git HEAD `41406c8edf5a2b9f8041652835b236ed40aba513` 的源码导出与其 Python 环境（SDK `2.8.0`）。源码、默认 bot 配置、运行数据、Runner socket 均在用户私有临时目录内；不加载 canonical Core 的 bot 配置或数据，不启动 Platform IO / QQ 网关或完整聊天服务。

脚本启动真实 `PluginRunnerSupervisor` 与独立 Runner 子进程，经 `plugin.register_components` 注册；将该 Supervisor 接入 Core 现有组件查询，使用 `PluginToolProvider` 与 `ToolRegistry` 查询及调用工具。此处没有 mock Runner、mock RPC 或复制 Tool 实现。

- Runner 加载 `zjcs.guild-notifier 0.2.0` 成功。
- Core 能看到 `zjcs_query`，`visibility=visible`，必填参数为 `query`，枚举与预期一致。
- 三项 `ToolRegistry.invoke → PluginToolProvider → ComponentQueryService → Runner plugin.invoke_tool` 调用成功；返回 `success=true`、结构化 `facts` 与一致的 JSON history content。
- `plugin.enabled=true` 是 Runner 激活与注册的前提；禁用插件时不注册 Tool。测试使用 `target.group_ids=[]`，没有提醒投递目标，未生成 notification state 文件。

使用实际日期 `2026-10-01`（Asia/Shanghai），仅在隔离测试配置中设置合成开服日期 `2026-07-06`（Day 88），未修改系统时钟或生产服务器配置。以下日期是该测试服务器的预期，不表示生产公会服务器的实际日期。

| 查询 | 返回事实 | 剩余天数 |
| --- | --- | --- |
| `next_dungeon` | 仙海云舟，2026-10-12 | 11 |
| `next_weekly_activity` + `宾果抽抽乐` | 宾果抽抽乐，2026-10-12 | 11 |
| `next_season` | S3 羽之国开启，2026-10-27 | 26 |

## 真实 LLM 工具闭环

使用已有本地配置中的 `bailian-v4f-0731`（BaiLian-Responses / `deepseek-v4-flash-0731`），通过当前 Core 的 `LLMOrchestrator` 与实际 provider client 请求模型。提供正常工具定义和要求依据事实的测试 system prompt，没有强制 `tool_choice`；三条问题各自使用独立上下文。

| 自然语言输入 | 模型自主选择 | 根据 RPC 结果作答 |
| --- | --- | --- |
| 下一个副本什么时候？ | `zjcs_query(query=next_dungeon)` | 仙海云舟，2026-10-12，11 天后 |
| 下一次宾果什么时候？ | `zjcs_query(query=next_weekly_activity, activity=宾果抽抽乐)` | 2026-10-12，11 天后 |
| 赛季什么时候更新？ | `zjcs_query(query=next_season)` | S3，2026-10-27，26 天后 |

模型输出保留当前 Core 的 output items / provider replay，使用 Core 的 `bind_output_items_to_turn` 绑定逻辑轮次，并以同一 `call_id` / `logical_turn_id` 回填真实 Tool 结果。第二次模型请求生成回答；日期及剩余天数均与事实一致。完整脱敏后的工具 Schema、RPC 事实和模型回答见 [evidence/rc020-runtime.json](evidence/rc020-runtime.json)。

公开记录取自最终正常退出的重跑：Runner passed、RPC 3/3、LLM 3/3、exit code 0。记录中的插件 SHA-256 是本地受测文件的字节值（Windows 工作区行尾）；后续部署仍须按 Git blob 构建并校验发布文件。

默认 planner 的 `opencode-v4f-thinking` 请求先被外部 provider 以 HTTP 400 / `MissingSessionID` 拒绝（缺少 `x-opencode-session`）。[该服务官方说明](https://opencode.ai/docs/go/#where-can-i-use-it)要求客户端提供会话标识，并面向 coding-agent 流量。没有伪造客户端身份或修改 Core / canonical 配置；本轮改用已有通用模型验收。因此本记录证明当前 Tool 调用架构与所选模型的兼容性，**不声称默认 opencode planner 已通过，也不声称完整 Maisaka 群聊 / QQ / 生产端到端已验收**。

验收脚本自身曾修正 context factory 签名、工具结果轮次 metadata 与 Windows stdout Unicode 输出；这些是脚本适配，不是已 Review 插件的 runtime 修复。

## 生产版本只读核验

通过受控 SSH 对运行中 `maibot-core` 容器仅做版本、manifest 和指定源码 hash 读取；未读取生产秘密，未更新容器、重启服务或写入插件。

- Core 镜像标签：`maibot-local:41406c8edf5a-replytimeout360-r3`。
- Core pyproject 版本：`1.2.2`；SDK 包版本：`2.8.0`。
- live 插件版本仍为 `0.1.12`。
- 下列关键 Core 源码 SHA-256 与本地 Git HEAD 按 LF 归一后的源码逐项一致：

| Core 文件 | SHA-256 |
| --- | --- |
| `src/plugin_runtime/runner/runner_main.py` | `b66c2c81a8c66715326b1f69ae919e1efa8c9ffb817a1ee55a74d442d0c474d6` |
| `src/plugin_runtime/component_query.py` | `dd64bc63488f78300b2938029aedbc1ab23b1ebf2b583416a031f46b29d95b84` |
| `src/plugin_runtime/tool_provider.py` | `67148f5f427aeec2624d7adb125e4208246cf2140aed970835f9db736a15d439` |
| `src/core/tooling.py` | `e691993ff8b930c116fa6ff506effde4c720be045553d408a5495ec75e56dc60` |

SDK 的 `components.py` / `types.py` / `plugin.py` / `config.py` 也逐项与本地 SDK 按 LF 归一后的 hash 一致。此证据覆盖本次注册、Schema、RPC、结果包装的关键 API；不声称生产镜像所有文件或配置与本地完全相同。

## 重跑与质量检查

在仓库根目录用当前 MaiBot `.venv` 的 Python 执行：

```powershell
& '<MaiBot>\.venv\Scripts\python.exe' scripts/validate_query_runtime.py --core-root '<MaiBot>'
# 可选真实模型请求：使用本地受控配置，模型须已配置；会产生少量 API 请求。
& '<MaiBot>\.venv\Scripts\python.exe' scripts/validate_query_runtime.py --core-root '<MaiBot>' --model-config '<private-model-config.toml>' --llm --model-name bailian-v4f-0731
```

脚本只在临时环境复制受控模型配置，结束时删除该副本；配置、详细 Core 日志和请求快照不进入 Git，公开记录不包含密钥、provider 地址或请求头。Runner 在 `finally` 中停止。输出的 `acceptance.json` 保留逐步状态；外部 provider 故障时应依据失败类别判断，不将它当成插件兼容性结论。

完整测试：**277 passed**。Ruff check、Ruff format check、`git diff --check` 均通过。真实 Runner 启动同时通过 manifest 校验与加载。

**本轮未部署生产、未创建正式 Release，0.2.0 RC 等待下一轮外部 Review。**
