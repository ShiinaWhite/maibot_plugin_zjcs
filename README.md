# 杖剑助手

《杖剑传说》MaiBot 公会助手插件。

`杖剑助手` 是一个运行在 [MaiBot](https://github.com/MaiM-with-u/MaiBot) 上的插件（plugin id：`zjcs.guild-notifier`，当前版本 `0.1.3`），基于 MaiBot Plugin SDK 实现。它根据本地维护的《杖剑传说》时间线数据，每天定时检查服务器进度，提前向公会 QQ 群发送副本、活动和重要事件通知。

项目从公会真实需求出发，当前核心能力是服务器进度 / 活动 / 副本通知；未来会按公会实际使用需求继续扩展其他实用功能，不会永久限定为通知插件。

## 当前能力（0.1.3）

- **每日定时检查**：每天在配置的时间点（默认 09:00，Asia/Shanghai）检查一次本地时间线，不依赖 LLM，不使用外部接口；
- **合并通知**：同一天命中的多个提醒合并为一条消息发给每个群；一次每日检查中，同一群最多发送一条正式合并提醒；
- **多目标 QQ 群**：`group_ids` 支持配置多个群，向所有已配置群发送；
- **按群独立去重**：每个群有独立的已发送记录；一个群发送失败不影响其他群，重启后只补发失败的群；
- **部分失败补齐**：发送成功才记录状态；某群失败时其缺失的提醒在下轮检查中重试，且该群收到的正文只包含它缺失的内容；
- **六类独立提前提醒**：副本、秘宝大作战、宾果抽抽乐、幸运刮刮乐、菲涅克的谜题、遗物池及重要事件，各自使用一个提前提醒天数；
- **0 关闭类别**：某类内容填 `0` 即完全关闭该类提醒；
- **副本准入战力**：副本通知附带时间线中已确认的各难度准入战力，缺失难度不补猜；
- **副本准备建议**：副本提醒除开放时间和准入战力外，还会按副本开放日期提示何时开始攒副本次数（准备日期为副本开放前 1 天），文案使用「今天 / 明天 / 后天 / N天后」相对时间，例如 `准备建议：明天开始攒副本次数。`；
- **秘宝重点奖励**：秘宝大作战通知附带当期已确认的重点奖励；
- **宾果准备建议**：宾果抽抽乐提醒附带 `准备建议：现在开始攒果子，活动开始前至少留20个。` 提示；幸运刮刮乐、菲涅克的谜题当前没有额外准备建议；
- **中文 WebUI 配置**：全部配置项通过 MaiBot 插件配置页管理；
- **S4/S5/S6 赛季锚点**：后期赛季使用独立赛季开始日期计算进度，未开始时留空；
- **`/杖剑传说` / `/zjcs`**：查看中文指令帮助；
- **`/杖剑传说 预览`**（缩写 `/zjcs 预览`）：预览今天按当前配置会生成的提醒，不影响提醒状态；
- **`/杖剑传说 测试`**（缩写 `/zjcs 测试`）：向所有已配置通知群各实际发送一条链路测试消息，逐群独立重试，不写入业务状态；
- **指令权限**：`command.admin_qq` 留空时所有人都可以使用指令；填写后仅该 QQ 账号可以使用全部指令；
- **确定性通知**：所有通知文本由数据直接生成，不调用 LLM。

## 配置概览

复制 `config.example.toml` 为 `config.toml` 后填写（`config.toml` 不提交到仓库）。日常配置建议直接在 MaiBot WebUI 的插件管理页修改。

```toml
[plugin]
enabled = true

[target]
# 支持配置多个 QQ 群，每个元素是一个群号
group_ids = []

[server]
# 服务器开服日期，用于计算当前是开服第几天
open_date = ""

[schedule]
daily_check_time = "09:00"

[reminders]
# 每类内容一个提前提醒天数；0 表示关闭该类提醒
dungeon_remind_day = 1
secret_treasure_remind_day = 2
bingo_remind_day = 4
scratch_remind_day = 2
fenek_remind_day = 2
event_remind_day = 2

[command]
# 管理员 QQ 号；留空则所有人都可以使用指令
admin_qq = ""
```

说明：

- `target.group_ids` 是列表，可添加多个 QQ 群号（字符串，不转数值）；
- `server.open_date` 是服务器开服当天，格式 `YYYY-MM-DD`，“开服第 1 天”即当天；
- 每类提醒使用单个整数提前天数，`0` 表示关闭；
- `command.admin_qq` 只填普通 QQ 号；留空则所有人可用指令，填写后仅该账号可用；
- 时区内部固定使用 `Asia/Shanghai`，WebUI 中隐藏，无需修改；
- `season_dates.s4/s5/s6_start_date` 在对应赛季开始前留空即可。

## 数据来源原则

通知内容来自仓库内的本地数据文件 `timeline_v1.json`，数据维护规则见 [DATA_GUIDE.md](DATA_GUIDE.md)：

- 运行时只读本地时间线，不依赖第三方接口；
- 正式服确认数据优先，测试服 / 预测数据不作为确定事实通知；
- `pending` 或未确认内容不通知，缺失数据不猜测。

## 开发文档导航

| 文档 | 内容 |
| --- | --- |
| [AGENTS.md](AGENTS.md) | 长期项目规则：开发边界、多 Agent 协作纪律、生产运维红线 |
| [PROJECT_BRIEF.md](PROJECT_BRIEF.md) | 项目背景与长期产品方向 |
| [PROJECT_STATUS.md](PROJECT_STATUS.md) | 当前阶段状态与生产版本事实 |
| [DESIGN_DECISIONS.md](DESIGN_DECISIONS.md) | 已生效的设计决策及理由 |
| [DATA_GUIDE.md](DATA_GUIDE.md) | 时间线数据语义、可信度规则、日期/赛季计算 |
| [MAIBOT_REFERENCES.md](MAIBOT_REFERENCES.md) | 已验证的 MaiBot / SDK 能力与外部参考 |
| [DEPLOYMENT.md](DEPLOYMENT.md) | 生产部署事实、部署安全规则与回滚原则 |

## 开发 / 测试

- 插件源码：`plugin.py`、`timeline.py`、`state.py`；游戏数据：`timeline_v1.json`；单元测试：`tests/`。
- 运行测试：在装有 MaiBot / `maibot_sdk` 的环境中执行 `python -m pytest`。
- 代码质量：提交前运行 `ruff check` 与 `ruff format --check`。
- 原则：游戏内容变化优先改 `timeline_v1.json`，不改业务逻辑；插件数据写入 MaiBot 提供的插件数据目录，不写入源码目录。

## 技术边界

**MaiBot Core 是只读依赖。** 本项目的全部功能通过 MaiBot 插件机制与当前 Plugin SDK 实现；如果某需求不改 Core 无法实现，则明确暴露限制，而不是修改宿主。
