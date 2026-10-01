# 0.3.0 Release Candidate 验收记录

更新时间：2026-10-02。

合并前已核对 origin/main 为 `d2bf4d480b5911cac43faeb91edad59ddb1a62df`、origin/DEV 为 `d6344a5665fea5b8349611d5f85836ddd16ac15e`，没有漂移。已通过外部 Review 的主体实现 `ccb27513dba4250a24c7c264a84a7119487fce44` 和调度优化 `d6344a5665fea5b8349611d5f85836ddd16ac15e` 经 merge commit `f241c96b61fcf1b702e543f60bf646d9e7f9a46d` 合入 main，未 squash / rebase / amend，DEV 保留。

main 当前为 **0.3.0 RC / config 1.5.0 / state 2**，plugin id 仍为 `zjcs.guild-notifier`；RC 是候选状态，manifest version 为 `0.3.0`。本轮仅合并并收口文档，runtime 与已 Review 的 DEV 完全一致，未继续开发业务功能。等待外部 RC Review，未部署、未创建 GitHub Release 或 tag。

当前生产仍为 **0.2.0 / `d2bf4d480b5911cac43faeb91edad59ddb1a62df` / config 1.4.0 / state 2**，依据操作者提供的基线；本轮未访问或修改生产。

## 事实精度与边界

现有时间线提供赛季日期。操作者截图中 S3 的日期与倒计时支持该次切换约为 08:00，但截图不是所有赛季和服务器的通用时刻规则。

[QY Maple 的赛季切换攻略](https://www.taptap.cn/moment/753518974301376497) 在 S2 的具体说明中提及早上 8 点以及小床 36 小时准备。[池鱼的 S2 准备攻略](https://www.taptap.cn/moment/693119946313434944) 讨论了按当前赛季目标决定是否囤经验。这些是社区作者经验资料，可支持保守的准备建议，不能作为官方全局固定时刻的证据。

因此不修改 `timeline_v1.json` 或推算所有赛季开启小时。采用操作者确认的本服时刻列表 `season_preparation.start_times`，每项 `{season, start_datetime}`。默认空；确认时刻转换到配置时区后的日期必须等于原时间线 / 赛季锚点计算日期。无日期、无偏移、冲突、未确认或重复赛季均不生成。此处测试中的 08:00 是显式 fixture。

精确节点是 UTC 瞬间减 36 小时：`2026-10-10T08:00:00+08:00` 对应 `2026-10-08T20:00:00+08:00`。通知仅建议在当前目标已完成时考虑停止领取小床经验；不加入先推完新地图才能领取的断言。

## 调度、状态与兼容

- 每日任务仍在原配置时间检查原六类提醒；同一任务串行检查精确节点，避免两个状态写入者。
- 窗口前只等待下一每日检查或精确节点中较早者，不每分钟刷新；仅窗口内未完成的发送 / 状态落盘工作才以 60 秒或剩余窗口中较小者重试。全部持久化后恢复长等待，配置更新通过原生命周期重新判断。节点无需等到次日 09:00。
- 准备窗口 `[start - 36h, start)`；重启和失败群允许在窗口内补齐，开始后不新发起发送。每次尝试及流解析完成后均检查过期，远端已接收的请求不能撤回。
- 各群分别沿用 1/3/5 秒重试、流解析和肯定发送成功判定。新命名空间 key 包含事件 ID / UTC 开启瞬间 / 36h；成功群不重发，失败群可继续补齐。只改配置的偏移表示而保持相同瞬间，不会产生新 key。
- state 继续为 2。所有历史 keys 保留，不新增迁移；文件坏数据时停止发送。磁盘写入失败时，本进程缓存肯定成功身份，并在后续窗口检查补写状态；持久化之前崩溃仍有重复风险，未引入投递事务。
- config 1.4.0 → 1.5.0 通过既有 normalizer / SDK 重建补入默认 `start_times=[]` 和独立开关；原群、管理员、日期、每日时间及六类提醒值保持。对象列表经真实 SDK rebuild 验证保留，重复 normalize 幂等。升级本身不会自动产生赛季准备提醒；正式部署后，必须由操作者配置本服已确认的赛季 datetime，功能才会实际触发。
- Tool 和命令仍只读查询，日期语义仍为自然日。没有新增 query type，副本门槛口语复用 `next_dungeon` 已有 requirements。未知 / 缺失难度不猜。

## 单元测试与质量检查

完整回归覆盖旧命令、六类每日提醒、多群去重、重试、旧配置迁移、state 历史与时间线 integrity gate。新增精确提醒测试覆盖 36h、跨日 / UTC 偏移 / DST、窗口边界、空配置 / 关闭 / 日期冲突 / 重复、重启与部分失败、磁盘失败补写、过期重试和慢流解析、群发送跨过开始时刻、09:00 与 20:00 共存、精确秒唤醒、卸载取消、Tool 只读。

最终结果：**316 项全部通过**；Ruff check / format check 全部通过（12 个 Python 文件），`git diff --check` 通过；包含既有时间线 integrity gate。命令为 MaiBot `.venv` 的 `python -m pytest -q`、`ruff check .`、`ruff format --check .`，以及 `git diff --check`。

## 真实 Core / Runner / LLM 受控验收

主体实现阶段使用仓库 `scripts/validate_query_runtime.py`，将本地 Core Git HEAD 导出到私有临时目录，复制当时工作区的插件五文件，启动真实第三方 Runner 与 Core ToolRegistry / PluginToolProvider；不启动完整 Bot Manager 或 Platform IO。通知目标空，无真实 QQ 发送。Core 源码不修改。保留的 JSON 是主体实现 `ccb27513dba4250a24c7c264a84a7119487fce44` 阶段的历史证据，不是本轮重新运行的结果。

环境：Core 1.2.2，commit `41406c8edf5a2b9f8041652835b236ed40aba513`；SDK 2.8.0。LLM 使用现有本地配置模型 `bailian-v4f-0731`，不改本地或生产模型配置。临时凭据副本在结束后删除，仓库证据仅保留脱离环境的事实、schema 和验收结果。

验收命令（路径由本机安装位置填写；不包含凭据）：

```text
python scripts/validate_query_runtime.py --core-root <local-core> --llm --power-queries --model-name bailian-v4f-0731 --model-config <private-local-model-config>
```

实际结果：**Runner / 六类 RPC / 8 个 LLM 闭环均通过**。Runner 加载 0.3.0；Core 可见 Tool，必填 query schema 正常；六类 RPC 返回真实插件事实；config 1.4.0 通过 Runner 自动迁移为 1.5.0，显式时刻列表保留；没有创建 notification state。

LLM 不强制 Tool choice：给出插件 schema 和禁止猜测的公会助手提示，模型自行选 Tool → 经真实 IPC 获取 facts → 回填 provider 工具历史 → 模型组织回复。原三问为副本时间、宾果时间、赛季更新；新增五问为门槛、要多少战力、需求战力、几战力能进、战力要求。日期回答校验实际日期和天数，战力回答校验全部已确认难度及数值。结果见 [受控验收 JSON](evidence/dev_query_runtime.json)。这证明该模型、该提示和本地当前架构的闭环，不等同生产 QQ 下所有表达或模型都会调用 Tool。

## 调度效率优化复验

针对基线 `ccb27513dba4250a24c7c264a84a7119487fce44` 的非阻塞效率问题，仅优化窗口前和工作完成后的等待。新增 6 项测试并强化 2 项既有断言，覆盖长等待取较早节点、精确秒唤醒、部分群失败补齐、状态写入失败不重发、完成后停止轮询、窗口截止和配置更新新增群；完整回归 316 项通过。plugin 0.3.0 / config 1.5.0 / state 2 不变。

调度优化提交为 `d6344a5665fea5b8349611d5f85836ddd16ac15e`，已通过外部 Review。上述 Runner / LLM JSON 为优化前主体实现的受控验收证据；优化没有修改 Tool，其调度变化由完整回归及新增 scheduler 测试验证。

## main RC 收口验证

合并及文档收口后重新执行完整 pytest、`ruff check .`、`ruff format --check .` 和 `git diff --check`。同时逐文件比较 Git blob 与已 Review 的 `d6344a5665fea5b8349611d5f85836ddd16ac15e`，确认发布五文件、配置示例、runtime 验收脚本及全部测试文件未被收口修改。版本仍为 plugin 0.3.0 / config 1.5.0 / state 2，plugin id 不变。

本轮没有修改 Tool/runtime，无需重复 Runner / LLM 集成测试；既有证据及适用范围保留。没有实际生产 QQ 验收，不声称 exactly-once。

## Review 重点

精确 datetime 的输入可靠性与日期冲突判定；串行调度是否保留旧每日语义；过期发送边界与状态写入失败窗口；配置列表经过 SDK 重建的保留能力；Tool 描述对战力意图的覆盖与缺失数据语义。本轮没有实际 QQ 验收或生产部署。
