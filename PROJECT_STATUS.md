# Project Status

更新时间：2026-09-06

## 当前阶段

**V1.2 已完成生产部署与 WebUI 验收，当前正式生产版本为 0.1.2。**

V1、V1.1、V1.2 三个版本均已完成生产验收。当前没有正在进行的施工任务。

## 生产版本事实

- production code commit：`4d067f50f47f53758dd8b3102bdd6a619343aecb`
- plugin version：`0.1.2`（显示名「杖剑助手」，plugin id `zjcs.guild-notifier`）
- config version：`1.2.0`
- notification state version：`2`

## V1.2 能力摘要

- 多目标 QQ 群（`target.group_ids`），旧单群 `group_id` 配置已自动迁移；
- 每日合并提醒：同一天命中的提醒合并为一条消息，向每个需要的群各发送一条；
- 按群独立去重与部分失败补齐：某群发送失败不影响其他群，重启后只补发失败群缺失的内容；
- 六类内容各自使用单整数提前提醒天数，`0` 表示关闭该类提醒；
- 旧列表提醒配置自动迁移为取最大有效正整数；
- 中文 WebUI 配置 Schema（多群列表输入、`YYYY-MM-DD` 占位符、时区隐藏）；
- `/zjcs_preview` 与 `/zjcs_test` 诊断命令。

详细能力与配置说明见 [README](README.md)。

## 生产迁移与验收记录（2026-09-06）

以下事实已在真实生产环境完成并验收：

- 配置已从 V1.1 自动迁移至 V1.2 结构，旧字段无残留，目标群未丢失，插件保持 enabled；
- notification state 已从 V1 全局结构迁移为 V2 按群结构（state schema 升级在生产完成）；
- V1 历史已发送 key 完整保留，全部归属迁移时的旧目标群，未复制给其他群，未被清空；
- WebUI 已实际打开验收：显示名、版本、多群列表控件、日期占位符、时区隐藏、六个单整数提醒字段均符合预期；
- Core 容器 recreate 后 healthy，NapCat 未受影响；插件加载成功，启动每日检查无异常。

部署事实、目录结构与操作规则见 [DEPLOYMENT.md](DEPLOYMENT.md)。

## 服务器进度

- `open_date` 为 `2026-06-19`；
- 当前仍属于早中期赛季数据使用阶段，S1～S3 数据较完整即可支撑当前使用，S4/S5/S6 依赖赛季锚点字段，不阻塞当前开发。

## 数据现状

- S1～S3：副本时间和战力数据较完整；
- S4～S5：已整理较多结构化数据，绝对开服天数需要考虑赛季偏移；
- S6：只整理了部分可靠信息，仍存在 `pending` 数据；
- 秘宝大作战：前 16 期重点大奖已经结构化，第 17 期起使用确认过的规则级回退；
- 周期活动和部分重要赛季事件已录入。

数据维护规则见 [DATA_GUIDE.md](DATA_GUIDE.md)。

## 项目资产

- 长期规则：`AGENTS.md`
- 项目背景：`PROJECT_BRIEF.md`
- 设计决策：`DESIGN_DECISIONS.md`
- 部署事实：`DEPLOYMENT.md`
- 数据规则：`DATA_GUIDE.md`
- SDK/参考：`MAIBOT_REFERENCES.md`
- 历史任务：`docs/archive/`
- 源码与测试：`plugin.py`、`timeline.py`、`state.py`、`timeline_v1.json`、`tests/`
