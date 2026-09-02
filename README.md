# 《杖剑传说》MaiBot 插件项目启动包

整理日期：2026-09-02

这套文件用于把当前已经确定的项目设计、数据和施工约束交给 Codex，并放入项目目录长期保存。

## 文件职责

- `AGENTS.md`
  - 项目长期开发规则。
  - 跨 V1 / V2 / V3 持续有效。
  - 不记录某个版本的临时功能清单。

- `PROJECT_BRIEF.md`
  - 项目是什么、为什么存在、长期方向是什么。
  - 给后来进入项目的开发者快速恢复背景。

- `PROJECT_STATUS.md`
  - 当前项目做到哪里。
  - 只在阶段节点更新，不作为逐提交开发日志。

- `CURRENT_TASK_V1.md`
  - 当前第一次施工的任务范围、实现方向和验收条件。
  - V1 完成后可以归档，由下一阶段任务文件接替。

- `DATA_GUIDE.md`
  - `timeline_v1.json` 的数据语义、可信度规则、日期/赛季计算注意事项。
  - 游戏数据相关实现应先读此文件。

- `MAIBOT_REFERENCES.md`
  - 已经提前筛选好的 MaiBot 定时任务、主动群推送参考实现。
  - 目的是减少 Codex 现场搜索和额度消耗。

- `DESIGN_DECISIONS.md`
  - 当前已经定下来的关键设计决策和原因。
  - 只保存有效决策，不记录已经否决的分支。

- `timeline_v1.json`
  - 当前静态游戏时间线数据集。
  - 包含副本、准入战力、秘宝重点奖励、活动和重要事件等。

## 建议放置方式

如果当前目录就是该插件项目根目录：

- `AGENTS.md`
- `PROJECT_BRIEF.md`
- `PROJECT_STATUS.md`

建议保留在项目根目录。

其余设计/任务文档可以先同样放在根目录，等项目结构稳定后再决定是否移动到 `docs/`。

`timeline_v1.json` 应随插件一起部署到本地 MaiBot 插件目录；核心要求是游戏数据与业务逻辑分离。

## 公开仓库配置约定

`config.example.toml` 只提供公开的配置结构和安全默认值。实际运行时复制为
`config.toml`，填写目标群和服务器信息；`config.toml` 不提交到公开仓库。

`timeline_v1.json` 应随插件一起部署到本地 MaiBot 插件目录；运行时状态不会写入源码目录，
而是由 MaiBot 的 `ctx.paths.data_dir` 提供位置。

## V1 当前实现布局

当前 workspace 作为插件源码和测试根目录，文件职责如下：

- `_manifest.json`、`config.example.toml`：MaiBot 插件清单和公开配置模板；
- `plugin.py`：MaiBot 生命周期、每日调度、目标群解析和固定文本发送；
- `timeline.py`：时间线读取、服务器 Day / 赛季锚点日期计算、状态筛选和消息格式化；
- `state.py`：使用 MaiBot 授予的插件数据目录保存跨重启去重状态；
- `tests/`：时间线、状态持久化和 MaiBot 能力调用的单元测试。

部署到本地 MaiBot 时，插件目录应为：

E:\AI Bot\MaiM-with-u\MaiBot\plugins\zjcs_guild_notifier

本 workspace 的 `timeline_v1.json` 应随插件一起部署；运行时状态不会写入源码目录，
而是由 MaiBot 的 `ctx.paths.data_dir` 提供位置。

## 项目管理方式

这个项目采用三层信息结构：

1. `AGENTS.md`：长期规则；
2. `PROJECT_BRIEF.md`：长期项目背景；
3. `PROJECT_STATUS.md`：当前阶段状态。

具体版本施工范围放在任务文件中，不把 V1 / V2 / V3 的临时范围写进长期项目规则。

当前聊天承担项目总设计和阶段决策；日常函数级施工留在 Codex 会话。
明显施工阶段完成后，通过公开 GitHub 的 commit 和 diff 交给人工或外部 GPT Review。
