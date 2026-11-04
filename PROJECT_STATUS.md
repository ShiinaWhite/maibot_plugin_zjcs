# Project Status

更新时间：2026-11-04

## 当前阶段

**main 已收口为 0.3.1 Release Candidate（S3 校准内容经外部 Review 后合入，plugin version 升为 `0.3.1`），等待外部 RC Review；当前生产仍为 0.3.0，尚未部署 0.3.1。**

0.3.1 RC 的来源：已通过外部 Review 的 DEV 最终提交 `a6fd295c4b7281b3e7baec4be0cac84f155297f8`（含三个 Review 通过的 commit：S3 校准 `4911a74`、生产状态文档修正与深渊 fail-closed `ee0768d`、深渊载体一致性 `a6fd295`）经独立 merge commit 合入 main，未 squash / rebase / amend。收口时仅做版本号（manifest `0.3.0 → 0.3.1`）与 RC 文档变化，runtime 业务代码与已 Review 的 DEV 完全一致。本轮没有 config / state schema migration：config 保持 `1.5.0`，state 保持 `2`，plugin id 仍为 `zjcs.guild-notifier`。

2026-11-04 校准轮：以运营者提供的 4 张本服『杖剑工具·赛季时间线』截图（开服第 139 天）为第一事实来源，修正战渊堡垒炼狱 4600 万（原 5200 万）、净化之庭炼狱 7500 万（原 8600 万）、君临之巢 1.25/1.45/1.8/2.5 亿（原 1.3/1.5/1.9/3.1 亿）+ 深渊 3.5 亿（副本开启 7 天后、开服第 204 天解锁）；羽2遗物池校准为「天穹圣约」、羽3遗物池校准为「苍辉古律」、奇迹幻兽校准为「奇迹幻兽-虹彩星灵」（event id 保持不变）；第 20～29 期秘宝（除第 22 期截图缺失保持 fallback，不猜）写入显式奖励，多奖励期新增 `featured_rewards` 结构；补录 S3 巡礼之证五期与 Day207 预计联通双倍 BUFF（`estimated` 状态，不参与自动提醒、日程与进度查询）。每周轮换规则经截图验证 S3 第 21～30 周无偏移，未改动。历史已发送的 5200 万战渊堡垒提醒不在本轮处理范围。

延迟深渊模型：`deep_abyss_server_day` / `deep_abyss_season_day` 与副本本体日期模型同载体表达；深渊门槛不混入副本开放日普通 requirements，单独以「深渊：X（日期 · 副本开启 N 天后解锁）」展示。runtime 与 integrity audit 均 fail closed：两种载体不得混写、载体必须与副本日期模型一致、字段非法、不晚于副本开放 day 的配置一律 broken——隐藏不可靠深渊信息，不猜测；合法 S3 君临之巢与 S5 起源之门行为保持。详细语义见 [DATA_GUIDE](DATA_GUIDE.md) 与 [0.3.1 RC 验收记录](docs/RC_0.3.1_VALIDATION.md)。

历史背景：0.3.0 的 DEV 主体提交 `d6344a5665fea5b8349611d5f85836ddd16ac15e` 经外部 Review 后由独立 merge commit `f241c96b61fcf1b702e543f60bf646d9e7f9a46d` 合入 main（`db97e8f` 为其文档收口提交），并已于 2026-10-02 部署到生产。该版本新增按本服确认 datetime 调度的赛季前 36 小时准备提醒，并完善既有 `zjcs_query / next_dungeon` 的副本战力口语描述；不引入关键词路由或第二套战力计算。

config 自 0.3.0 起为 `1.5.0`，默认 `season_preparation.start_times=[]`，旧设置保留；state 保持 `2`，不迁移或清空历史 keys。升级本身不会产生赛季准备提醒；生产部署后仍须操作者填写本服已确认的 datetime 才会实际触发。不能将 08:00 作为所有赛季的固定规则。

准备窗口为 `[season_start - 36h, season_start)`，按真实 elapsed 36h 计算；与每日 09:00 检查共用单一串行任务。窗口前和全部工作可靠落盘后长等待，只有窗口内失败群 / 落盘失败工作需要补齐，赛季开始后停止。每群独立去重；发送后、落盘前崩溃仍可能跨重启重复，不声称 exactly-once。Tool / 命令仍以自然日事实为主，精确 datetime 当前仅服务准备提醒。

DEV 分支保留。0.3.1 RC 未创建 GitHub Release 或 tag，未连接生产 QQ，未部署；MaiBot Core 只读。0.3.1 的事实依据与验证见 [0.3.1 RC 验收记录](docs/RC_0.3.1_VALIDATION.md)，0.3.0 的记录见 [0.3.0 RC 验收记录](docs/RC_0.3.0_VALIDATION.md)；受控验收不等于真实生产 QQ 全覆盖。

## 生产版本事实

当前生产基线（2026-10-02 部署，技术验收完成）：

- production commit：`db97e8f75275894ea4aad0ade0c57b0c513291c6`
- plugin version：`0.3.0`，plugin id `zjcs.guild-notifier`
- config version：`1.5.0`（部署时由 1.4.0 自动迁移）
- notification state version：`2`（无 state migration，历史 keys 完整）

当前 main 为 **0.3.1 RC**（merge commit 之后含版本号与 RC 文档收口），包含尚未部署的 S3 时间线校准与延迟深渊模型；在通过外部 RC Review 并获得明确部署授权前不得切换生产。本轮没有 config / state migration，部署时 config 与 state 均无结构变化。

更早的 0.1.x / 0.2.0 / 0.3.0 RC 文档保留为历史记录，不作为当前状态。

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

- S1～S3：副本时间和战力数据较完整；S3 后半段（Day141～207）已按 2026-11-04 本服截图完成校准；
- S4～S5：已整理较多结构化数据，绝对开服天数需要考虑赛季偏移；
- S6：只整理了部分可靠信息，仍存在 `pending` 数据；
- 秘宝大作战：前 16 期与第 20、21、23～29 期重点大奖已结构化（第 20/24/26/28 期为双奖励），第 17～19、22 期使用确认过的规则级回退；
- 周期活动和部分重要赛季事件已录入；S3 巡礼之证五期已按截图补录为显式事件。

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
