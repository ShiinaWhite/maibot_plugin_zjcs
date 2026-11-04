# 0.3.1 Release Candidate 验收记录

更新时间：2026-11-04。

## 来源与合并

已通过外部 Review 的 DEV 最终提交 `a6fd295c4b7281b3e7baec4be0cac84f155297f8` 经独立 merge commit `580a932910b664f47052fe6225e92ba07416e8bf`（`merge: integrate S3 timeline calibration`）合入 main，未 squash / rebase / amend，DEV 分支保留。合入的三个 Review 通过 commit：

- `4911a74`：S3 时间线截图校准（数据 + 延迟深渊模型 + 多奖励秘宝）；
- `ee0768d`：deep abyss runtime fail-closed + 生产状态文档修正；
- `a6fd295`：deep abyss 载体与副本日期模型一致性。

合并前核对 origin/main = `db97e8f75275894ea4aad0ade0c57b0c513291c6`、origin/DEV = `a6fd295c…`，无漂移。

## 版本与兼容契约

- plugin version：`0.3.0 → 0.3.1`，仅修改 `_manifest.json` 的 version 字段与 `tests/test_release_candidate.py` 的对应断言；
- plugin id 保持 `zjcs.guild-notifier`；
- config schema 保持 `1.5.0`，state schema 保持 `2`，本轮无任何 config / state migration；
- 提醒提前量、per-group dedupe、发送 retry、36 小时赛季准备提醒、`zjcs_query` 行为与 Tool schema 均与已 Review 的 DEV 完全一致。

## 0.3.1 内容摘要

### S3 数据校准（第一事实来源：2026-11-04 本服时间线截图，开服第 139 天）

- 战渊堡垒（Day141）炼狱：5200 万 → **4600 万**；
- 净化之庭（Day155）炼狱：8600 万 → **7500 万**；
- 君临之巢（Day197）：普通 1.25 亿 / 困难 1.45 亿 / 噩梦 1.8 亿 / 炼狱 2.5 亿（原 1.3/1.5/1.9/3.1 亿为旧口径）；深渊 3.5 亿在副本开启 7 天后（开服第 204 天，2027-01-08）解锁；SSS 装备评级要求 1红4金（备注）；
- 羽2遗物池（Day144）→「天穹圣约」、羽3遗物池（Day174）→「苍辉古律」、奇迹幻兽（Day159）→「奇迹幻兽-虹彩星灵」，稳定 event id 不变；
- S3 巡礼之证五期（Day141/155/169/183/197）显式录入；
- 第 20/21/23～29 期秘宝显式奖励；多奖励期新增 `featured_rewards`（运行时 payload 兼容携带 `featured_reward`）；第 22 期截图缺失，保持规则级 fallback，不猜；
- Day207 联通助力双倍 BUFF 保持 `estimated` 状态，不参与自动提醒、日程与进度查询；
- 每周轮换规则经截图验证 S3 第 21～30 周无偏移，未改动。

### 延迟深渊模型

- `deep_abyss_server_day`（服务器进度模型）/ `deep_abyss_season_day`（赛季进度模型）与副本本体日期载体一致表达；
- 深渊门槛不混入副本开放日普通 requirements，单独以「深渊：X（日期 · 副本开启 N 天后解锁）」展示；
- runtime 与 integrity audit 均 fail closed：两种载体不得混写；载体必须与副本本体日期模型一致；字段非法、不晚于副本开放 day 时判 broken——隐藏不可靠深渊信息，不猜测，绝不能退化成「深渊与普通难度同日开放」；
- 合法 S3 君临之巢与 S5 起源之门行为保持。

## Runtime 验证边界

本轮收口相对已 Review 的 DEV 只发生 merge、版本字段与 RC 文档变化；`timeline.py`、`timeline_v1.json`、`plugin.py`、`state.py` 的业务逻辑与 `a6fd295c…` 逐字节一致（`git diff a6fd295c… HEAD -- timeline.py timeline_v1.json plugin.py state.py` 为空，manifest version 字段除外）。因此本轮不重新执行 LLM / Runner 集成测试；0.3.0 时期的受控 Runner / LLM 结果见 [0.3.0 RC 验收记录](RC_0.3.0_VALIDATION.md)。

## 质量门结果（2026-11-04，main @ 0.3.1 RC 收口 commit）

- 完整 pytest：**344 passed**；
- `ruff check .`：通过；
- `ruff format --check .`：通过；
- `git diff --check`：通过。

未部署生产、未创建 GitHub Release、未打 tag、未连接生产 QQ、未发送真实消息。等待外部 0.3.1 RC Review。
