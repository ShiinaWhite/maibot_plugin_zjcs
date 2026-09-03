# Project Status

更新时间：2026-09-03

## 当前阶段

**V1 已完成生产真实发送验收；当前版本线为 V1.1。**

V1.1 在保持现有时间线数据和通知键不变的前提下，增加每日合并提醒、分类提醒时间、中文 WebUI 配置、诊断预览和测试发送入口。

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

## 当前实现资产

插件源码、时间线数据、配置和测试位于当前 workspace；部署目录为：

E:\AI Bot\MaiM-with-u\MaiBot\plugins\zjcs_guild_notifier

## 当前版本

- 插件版本：`0.1.1`
- 配置版本：`1.1.0`
- V1.1 范围：每日合并提醒、分类提醒策略、中文配置 Schema、今日预览和测试发送。

## 本文件更新规则

只在明显阶段节点更新，例如：

- V1 实现完成；
- 公会实际运行验证完成；
- 开始下一阶段功能；
- 数据模型或项目架构发生长期变化。

不要把它变成逐提交或逐日开发日志。
