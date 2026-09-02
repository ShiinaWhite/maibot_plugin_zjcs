# Project Status

更新时间：2026-09-02

## 当前阶段

**V1 插件源码实现与本地单元验证完成，尚待部署到本地 MaiBot 做真实运行验证。**

项目已经完成需求讨论、V1 范围确定、初步数据收集、MaiBot 参考实现筛选、施工计划确认以及第一版源码实现。

## 当前服务器进度

公会当前服务器大约处于：

- S2
- 开服第 73 天
- 龙之国 · 青云观

因此第一版无需为了远期赛季追求 100% 数据完整度，只要当前和近期内容可靠可用即可。

## 已准备资产

- `AGENTS.md`
- `PROJECT_BRIEF.md`
- `PROJECT_STATUS.md`
- `CURRENT_TASK_V1.md`
- `DATA_GUIDE.md`
- `MAIBOT_REFERENCES.md`
- `DESIGN_DECISIONS.md`
- `config.example.toml`
- `plugin.py`
- `state.py`
- `tests/`
- `timeline.py`
- `timeline_v1.json`

## 数据现状

- S1～S3：副本时间和战力数据较完整；
- S4～S5：已整理较多数据，但绝对开服天数需要考虑赛季偏移；
- S6：只整理了部分可靠信息，仍存在 `pending` 数据；
- 秘宝大作战：前 16 期重点大奖已经结构化；
- 周期活动和部分重要赛季事件已录入。

第一版不要求为了补齐 S6 而阻塞开发。

## 当前 V1 实现资产

插件源码、时间线数据、配置和测试位于当前 workspace；部署目录为：

E:\AI Bot\MaiM-with-u\MaiBot\plugins\zjcs_guild_notifier

## 当前下一步

部署当前 workspace 中的插件文件到本地 MaiBot 的
`plugins\zjcs_guild_notifier`，配置目标群和服务器开服日期后，进行真实 MaiBot
运行、目标群解析和主动发送验证。第一轮代码 push 后暂停，等待外部 GPT
基于 GitHub 中的真实源码和 commit diff 进行 Review。

## 本文件更新规则

只在明显阶段节点更新，例如：

- V1 实现完成；
- 公会实际运行验证完成；
- 开始下一阶段功能；
- 数据模型或项目架构发生长期变化。

不要把它变成逐提交或逐日开发日志。
