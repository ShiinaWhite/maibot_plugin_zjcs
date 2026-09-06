# Deployment

本文记录《杖剑助手》（`zjcs.guild-notifier`）当前生产部署的长期有效事实与操作规则。

不记录 secret、一次性凭据、临时容器 ID 或一次性备份时间戳；敏感值只存在于生产服务器的受控私有文件中。

## 当前部署模式（plugins-persistent）

当前生产使用 **plugins 根目录持久化 bind**：

```text
Host:      /srv/maibot/plugins  →  Container: /MaiMBot/plugins
```

杖剑助手的 live 目录：

```text
/srv/maibot/plugins/zjcs_guild_notifier
```

注意纠正旧认知：

- 当前 compose **没有** zjcs 独立的 commit-specific runtime bind；
- 当前 compose **没有** zjcs 独立的私有 config bind；
- live 目录中的 `config.toml` 就是插件实际加载的生产配置（插件从自身目录读取 `config.toml`）；
- live 目录不是 immutable：`config.toml`、`config_back/`、`__pycache__` 等运行产物就在其中。

NapCat Adapter 与其他插件同样位于 plugins 根目录之下。

## Release / Runtime 语义

服务器上为每个已部署 commit 保留归档：

```text
/srv/maibot/plugin-releases/zjcs_guild_notifier/<commit>/
/srv/maibot/plugin-runtime/zjcs_guild_notifier/<commit>/
```

用途：

- 发布归档与 commit 审计；
- 逐文件 hash / git blob 校验基准；
- 回滚素材。

这些目录是只读参照物。**当前容器不是从 commit runtime path 直接挂载运行**——生产实际运行的是 live copy `/srv/maibot/plugins/zjcs_guild_notifier`。因此每次部署都必须在服务器上验证：

```text
live production files == target Git commit bytes
```

校验方式：对每个发布文件计算 git blob sha1（`blob <size>\0` + 内容），与 `git ls-tree <commit>` 的 blob 值逐一比对；不能只比较文件是否存在。

## 部署文件范围

插件发布仅包含：

```text
_manifest.json
plugin.py
state.py
timeline.py
timeline_v1.json
```

`config.example.toml`、测试与文档不进入生产 release/runtime。

## 生产持久化

- live 插件代码与生产配置：live plugin dir（`/srv/maibot/plugins/zjcs_guild_notifier/`），生产 `config.toml` 不提交 Git；
- 通知状态（notification state）：MaiBot 插件数据目录，host 路径
  `/srv/maibot/data/plugin-data/zjcs.guild-notifier/notification_state.json`；
- 配置升级 / state schema 升级前必须先备份 live `config.toml` 与 state 文件；
- 插件自身的 WebUI 配置保存会在 `config_back/` 留有时间戳备份，这是插件目录内的机制，不替代部署前备份。

## 部署安全规则

1. 确认目标 commit 已通过独立 Review；
2. 用**原始 Git blob 字节**导出发布文件，避免 CRLF / autocrlf 改变发布字节（见下文经验）；
3. 建立 release / runtime 归档目录；
4. 备份 live `config.toml`、notification state 与 compose 文件，记录 hashes；
5. 将目标 commit 文件同步到 live plugin dir（不触碰其中的 `config.toml` 与运行产物）；
6. 在服务器上逐文件做 hash / git blob 校验；
7. `docker compose config -q` 校验通过；
8. 只 recreate Core（`docker compose up -d --no-deps --force-recreate core`）；
9. 不 recreate NapCat；
10. 不 build / pull 镜像，除非另有明确升级任务；
11. 验证 Core healthy、插件 Runner healthy、插件加载成功；
12. 验证配置迁移与 state 迁移结果（旧字段无残留、历史 key 完整）；
13. 不为了验收清空 dedupe 状态，不伪造日期或重发历史正式通知。

## 导出字节经验（Windows 工作区）

在 Windows 工作区使用 `git archive` 导出时，可能因工作树换行配置 / 导出属性转换得到与 Git blob 不同的字节（例如 LF 被转换为 CRLF），文件“看起来一样”但 blob 校验失败。

生产发布以 **Git blob 内容为事实来源**：应使用能保证原始 blob 字节的导出方式（如 `git cat-file blob <commit>:<path>`），导出后先在本地用 `git hash-object --no-filters` 核对，再在服务器上用相同算法二次核验。

## 回滚原则

- 部署前必须保留 live config / state / compose 的完整备份；
- 每个 commit 的 release 归档必须保留；
- 回滚 = 将 live plugin dir 恢复为旧 commit 文件 + 恢复兼容的 config/state，然后只 recreate Core；
- 若版本变化改变了持久化数据，仅切回旧文件不算完整回滚，必须恢复数据兼容状态；
- 不操作 NapCat，除非事故与 NapCat 本身有关且获得单独授权。
