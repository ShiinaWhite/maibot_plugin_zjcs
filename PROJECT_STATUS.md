# Project Status

更新时间：2026-09-10

## 当前阶段

**0.1.4 已完成生产部署，并完成管理员帮助入口与当前群测试指令的真实 QQ 验收；当前正式生产版本为 0.1.4。**

当前 0.1.x 版本线已完成至 0.1.4 的生产部署与验收。当前没有正在进行的施工任务。

## 生产版本事实

- production code commit：`7b0b8773e1243087fad78265179ca1e4f97ae36a`
- plugin version：`0.1.4`（显示名「杖剑助手」，plugin id `zjcs.guild-notifier`）
- config version：`1.4.0`
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

## 0.1.3 增量能力摘要

- 正式合并通知标题从「每日提醒」调整为「近期提醒」（operator preview 标题保持「今日提醒预览」，两者语义不同）；
- 副本提醒增加准备建议：副本开放前 1 天开始攒副本次数；
- 准备时间以「今天 / 明天 / 后天 / N天后」的相对语义展示，不使用绝对日期；
- 宾果抽抽乐提醒增加「现在开始攒果子，活动开始前至少留20个」；幸运刮刮乐、菲涅克的谜题当前没有准备建议；
- `/zjcs_preview` 复用同一提醒格式化逻辑，可看到准备建议。

## 0.1.4 增量能力摘要

- 新增统一中文指令入口 `/杖剑传说` 与 `/zjcs`；无参数或「帮助」显示完整中文帮助；
- Preview 新入口：`/杖剑传说 预览`、`/zjcs 预览`；
- 测试新入口：`/杖剑传说 测试`、`/zjcs 测试`；
- 旧 `/zjcs_preview`、`/zjcs_test` 不再注册为插件 Command；
- 指令权限改为插件内管理：`command.admin_qqs`；列表为空时所有人可使用指令，非空时仅列表中的 QQ 账号可使用，支持多个管理员 QQ；
- 指令只作用于发起指令的当前聊天，不会因为 `target.group_ids` 配置多个群而跨群广播；`target.group_ids` 仅用于每日自动提醒投递；
- `/杖剑传说 测试` 只测试当前 QQ 群的发送链路；当前群即使不在 `target.group_ids` 中，也不会触发其他群；
- config schema 从 1.2.0 升级到 1.4.0（1.3.0 仅为开发阶段中间 schema，未作为生产版本发布）；
- notification state schema 仍为 2，没有变化。

## 生产迁移与验收记录（2026-09-06）

以下事实已在真实生产环境完成并验收：

- 配置已从 V1.1 自动迁移至 V1.2 结构，旧字段无残留，目标群未丢失，插件保持 enabled；
- notification state 已从 V1 全局结构迁移为 V2 按群结构（state schema 升级在生产完成）；
- V1 历史已发送 key 完整保留，全部归属迁移时的旧目标群，未复制给其他群，未被清空；
- WebUI 已实际打开验收：显示名、版本、多群列表控件、日期占位符、时区隐藏、六个单整数提醒字段均符合预期；
- Core 容器 recreate 后 healthy，NapCat 未受影响；插件加载成功，启动每日检查无异常。

部署事实、目录结构与操作规则见 [DEPLOYMENT.md](DEPLOYMENT.md)。

## 生产部署与验收记录（2026-09-10，0.1.3）

以下事实已在真实生产环境完成并验收：

- 0.1.3 已实际部署：发布文件以 Git 原始 blob 字节导出，live 目录与目标 commit 逐文件校验一致，目标 commit 此前已通过独立 Review；
- Core 容器 recreate 后 healthy，Extension Runner healthy，插件 v0.1.3 加载成功，NapCat 未受影响（容器身份与重启计数不变）；
- notification state 在升级前后保持不变：state schema 仍为 version 2，历史已发送 key 完整；
- 古剑城历史正式提醒没有因升级重复发送，未产生任何额外正式通知；
- QQ operator 实际执行 `/zjcs_preview` 成功，Preview 中实际看到「准备建议：明天开始攒副本次数。」；
- Preview 未写 notification state，也未触发额外正式提醒。

## 生产部署与验收记录（2026-09-10，0.1.4）

以下事实已在真实生产环境完成并验收：

- 0.1.4 已实际部署到生产：live 五个生产文件与 commit `7b0b8773e1243087fad78265179ca1e4f97ae36a` 字节级一致（Git blob 逐文件校验）；
- Core 与 Extension Runner 最终 healthy，NapCat 未被重启；
- 生产配置由 1.2.0 正式迁移到 1.4.0；
- `admin_qqs` 在新代码生效前已预置为非空管理员列表（来源为旧 Host command_permissions 中旧杖剑指令的放行用户），因此不存在「空列表导致所有用户临时开放」的窗口；
- 迁移后管理员列表成功保留；
- 原 target / server / season / schedule / reminders 配置保持不变；
- notification state 前后 hash 不变，version 2，历史 sent keys 保留；
- 启动后没有历史正式提醒重复发送；
- WebUI 确认仅注册新的 `zjcs_command`，旧 preview/test Command 已移除；
- 真实 QQ 管理员执行 `/杖剑传说` 成功，当前群正确显示中文帮助（含预览、测试条目与 `/zjcs` 缩写说明）；
- 真实 QQ 管理员执行 `/杖剑传说 测试` 成功，只在当前群收到一条测试消息，消息正文明确当前群发送链路正常且非游戏活动提醒；
- 测试没有向其他目标群广播，也没有额外发送第二条成功提示。

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
