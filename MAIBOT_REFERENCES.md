# MaiBot 参考实现

这些参考已经提前筛选，目的是让 Codex 少做无意义搜索。

最终以**当前项目中的 MaiBot / maibot_sdk API** 为事实来源。

## 1. 定时任务与插件生命周期

仓库：

`https://github.com/xhstoyea/maibot-reminder`

重点文件：

- `plugin.py`

重点参考：

- `ReminderScheduler.start()`
- `ReminderScheduler.stop()`
- `ReminderPlugin.on_load()`
- `ReminderPlugin.on_unload()`

适合学习：

- `asyncio` 后台任务怎么启动；
- 插件卸载时怎么取消并等待后台任务；
- 插件重载后如何避免残留任务；
- 持久化提醒如何恢复。

不要照抄：

- 到期后使用 `ctx.maisaka.proactive.trigger()` 交给 AI 表达的逻辑。

本项目的服务器通知应该生成确定性固定文本并直接发送，不经过 LLM。

## 2. 主动向指定 QQ 群推送

仓库：

`https://github.com/SoulString-Dev/Maibot-Hot-News-Subscription-Push-Plugin`

重点文件：

- `app/factory.py`
- `services/stream_resolver.py`
- `services/delivery_service.py`
- `services/scheduler.py`

重点参考：

### 群目标解析

参考：

```text
ctx.chat.open_session(...)
```

关注如何使用：

- `platform="qq"`
- `chat_type="group"`
- `group_id`

将稳定 QQ 群号解析成运行时 `stream_id`。

### 主动发消息

参考：

```text
ctx.send.text(text, stream_id)
```

### 生命周期

参考：

- `on_load()`
- `on_unload()`
- scheduler 的 `start()` / `stop()`
- `asyncio.create_task()` 后台循环

### 稳定身份与 stream_id 分离

QQ `group_id` 是配置中的稳定身份。

`stream_id` 是 MaiBot Host 运行时解析出的聊天流标识。

不要把运行时 `stream_id` 当成唯一长期配置。

## 不要复制 Hot News 的完整架构

当前 V1 不需要：

- 热点抓取；
- 多来源系统；
- 多目标订阅平台；
- 完整 SQLite 多表设计；
- 完整投递日志；
- 通用 cron 多源调度；
- HTTP 数据源体系。

只参考与本项目直接相关的小块。

## 3. 旧接口参考

`https://github.com/HShiDianLu/timed_greeting_plugin`

它在概念上同时实现过：

- 定时执行；
- 主动向群发送。

但它使用旧版 `src.plugin_system` / `send_api` / `chat_api` 路线。

只可用于理解思路，**不得作为当前 API 模板**。

## 事实来源优先级

1. 当前本地 MaiBot 项目；
2. 当前 `maibot_sdk`；
3. 当前官方插件 SDK 文档；
4. 上述近期公开插件；
5. 旧插件和旧文档。
