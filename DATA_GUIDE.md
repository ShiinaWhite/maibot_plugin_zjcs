# 时间线数据说明

## 数据文件

当前运行数据：

- `timeline_v1.json`

核心原则：

**游戏数据与代码分离。**

副本、战力、活动、奖励和重要事件发生变化时，优先更新数据文件，而不是修改业务代码。

## 数据可信度

当前数据中可能出现以下状态：

### `confirmed`

可以作为确定信息正常通知。

### `confirmed_partial`

只确认了部分字段。

通知时只展示已有字段，不补猜缺失内容。

### `confirmed_with_version_risk`

公开来源已经确认，但该内容历史上存在频繁调整。

可以使用当前值，但实现必须允许以后方便修改数据。

### `pending_formal_power` / 其他 pending

只确认事件或副本存在，但尚未获得足够可靠的正式服完整数据。

不得把缺失字段当确定信息通知。

### `estimated`

来源自身标注【预计】/预测时间（例如工具预测的联通助力双倍 BUFF），未正式确认。

`estimated` 条目不参与任何自动提醒、日程与进度查询；人工确认后才能升级为 `confirmed`。

## 数据优先级

维护数据时优先级建议：

1. 正式服游戏内实测 / 官方公告；
2. 近期正式服攻略或正式服图鉴；
3. 多个独立来源交叉一致；
4. 社区时间线；
5. 先遣服 / 测试服 / 预测。

测试服和预测不能覆盖已经确认的正式服数据。

对本公会当前生产服务器：运营者提供的本服当前时间线截图（如 `prod_timeline_screenshots_20261104`，2026-11-04，开服第 139 天）属于该服务器的第一事实来源；仓库旧数据、旧攻略或社区时间线与之冲突时以截图为准。

## 日期模型

### Day 1

所有日期计算必须统一“开服当天 = Day 1”。

若 `open_date` 为开服当天，则：

```text
server_day = (today - open_date).days + 1
```

反向计算某个 `server_day` 的实际日期时：

```text
event_date = open_date + (server_day - 1) 天
```

实现和测试必须覆盖这个 off-by-one 边界。

### S1～S3

当前公开资料中绝对 `server_day` 相对稳定，可以直接使用。

仍建议代码保留统一时间计算入口，不要把日期公式散落在各功能中。

### S4 及以后

已经观察到不同服务器可能因为位面流通、合区等产生整体时间偏移。

因此后期赛季优先支持：

```text
season_anchor_date + season_day
```

而不是假设所有服务器都永久遵循社区整理的绝对开服 Day。

当前只有一个公会服务器，不需要做多服务器管理平台，但数据模型不应把后续赛季永久锁死到唯一绝对 Day。

### 绝对日历事件

全服同一自然日开启的联动、节日、限时活动，使用绝对日期字段：

```text
event_date = YYYY-MM-DD
```

`event_date` 与 `open_date` 无关，任何服务器都得到同一日期；计算优先级高于 `season_day` / `server_day`。

这类事件不得换算成某个服务器的 `server_day` 再写成全局规则；`server_day` 只表示真正随服务器开服进度变化的内容。

## 时间线数据不变量 / Integrity Contract

`timeline_v1.json` 由仓库测试 `audit_timeline_integrity()` 在发布前自动审计，以下不变量必须成立：

1. dungeon / event 的日期模型三选一：`event_date`（绝对日历）、`server_day`（服务器进度）、`season + season_day`（赛季进度）；
2. `event_date` / `server_day` / `season_day` 不得混写；混写即歧义，运行时 fail closed（该条目被跳过，不猜测）；
3. `event_date` 必须是合法 `YYYY-MM-DD`；`server_day` / `season_day` 必须是正整数；
4. `season` 单独出现只是元数据，可与 `server_day` 共存；
5. dungeon / event 的 `id` 全局唯一，且不得使用系统保留前缀（`secret_treasure_`、`weekly_side_activity_`）；
6. 引用的 source key 必须已在 `sources` registry 注册；
7. 秘宝 `known_phases` 的 phase 号唯一，显式 `server_day`（override）不得重复；
8. 显式 `server_day` 是 override，优先于公式；歧义数据运行时不猜；
9. 延迟解锁深渊字段 `deep_abyss_server_day` / `deep_abyss_season_day` 二选一、必须为正整数且晚于副本自身开放 day；存在时 `深渊` 门槛不进入常规 requirements 展示；
10. 秘宝单期 `featured_reward` 与 `featured_rewards` 不得混写；`featured_rewards` 必须是非空数组，且每个条目都需非空 name 与可通知 status，否则整期 fail closed。

## 副本战力

副本的 `requirements` 是动态难度映射，例如：

```json
{
  "普通": 6200000,
  "困难": 7700000,
  "噩梦": 9800000
}
```

不要假定所有副本永远只有三个难度。

后期可能存在：

- 炼狱；
- 深渊；
- 其他新增难度。

通知时只遍历数据中实际存在的字段。

### 延迟解锁的深渊难度

部分最终副本（如 S3 君临之巢、S5 起源之门）的深渊难度在副本开启若干天后才解锁，不能写成 `requirements` 里的普通门槛——那会误导为开放日即可进入。

延迟解锁使用独立字段，与副本日期模型同载体：

```json
{
  "server_day": 197,
  "requirements": { "普通": 125000000, "深渊": 350000000 },
  "deep_abyss_server_day": 204
}
```

- `deep_abyss_server_day`（服务器进度模型）或 `deep_abyss_season_day`（赛季进度模型）二选一，混写即歧义，运行时 fail closed；
- 存在延迟字段时，`深渊` 门槛自动从常规 `requirements` 展示中剥离，单独以「深渊：X（日期 · 副本开启 N 天后解锁）」表达；
- 完整性审计要求延迟字段合法且晚于副本自身开放 day。

## 秘宝大作战

已确认基本规律：

- 开服第 8 天开始第一期；
- 每 7 天一期。

前 16 期重点大奖已经显式写入数据；2026-11-04 本服截图校准后，第 20、21、23、24、25、26、27、28、29 期也已显式写入。第 17～19 期与第 22 期暂无可靠显式数据（第 22 期截图被裁切），保持规则级 fallback，不猜具体大奖。

第 17 期后，特殊遗物箱内容开始扩充，因此不要把最初四种具体单品无限循环硬编码。

部分期数截图明确列出两个重点大奖（如第 20 期「原初宝石-宝石 ｜ 贤者之石-石块」）。多奖励期使用 `featured_rewards` 数组（单奖励期继续使用 `featured_reward`，两者不得混写）：

```json
{
  "phase": 20,
  "featured_rewards": [
    { "name": "原初宝石-宝石", "category": "special_relic", "status": "confirmed" },
    { "name": "贤者之石-石块", "category": "special_relic", "status": "confirmed" }
  ]
}
```

运行时 payload 始终同时携带 `featured_reward`（首个重点奖励）以兼容既有展示路径；多奖励期额外携带 `featured_rewards` 完整列表。任一奖励条目不可靠时整期 fail closed，不部分展示。

优先级：

1. 存在显式 phase 奖励数据时，直接使用；
2. 缺少显式数据时，只使用足够可靠的规则级信息；
3. 不自行猜测某一期具体大奖。

## 当前覆盖

当前数据主要用于支撑现阶段公会使用：

- S1～S3：较完整；
- S4～S5：已有大量结构化数据；
- S6：部分字段仍待正式服可靠数据补齐。

当前服务器仍处于早中期赛季，因此不要求为了补齐所有远期赛季而阻塞当前开发。

## 当前数据来源结论

调研过多个社区时间线、TapTap 攻略/图鉴、玩家工具和公开数据项目。

目前没有发现适合直接依赖的稳定、公开、官方国服通用 API。

因此当前采用本地数据集。

未来如果找到可靠 API，可新增数据同步层，但核心时间线/通知逻辑不应直接耦合到某个不稳定第三方接口。
