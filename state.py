from __future__ import annotations

import json
from pathlib import Path
from collections.abc import Iterable
from typing import Any


class StateFileError(ValueError):
    """持久化状态不可安全读取或写入。"""


class NotificationState:
    """使用插件数据目录按目标群分别保存已发送通知键。

    已发送状态必须区分 group_id：一次合并通知只对发送成功的群写入，
    发送失败或状态写入失败的群保持未记录，重启后仅对未记录的群重试。
    """

    VERSION = 2
    _LEGACY_VERSION = 1
    FILE_NAME = "notification_state.json"

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._groups: dict[str, set[str]] = {}

    def load(self) -> NotificationState:
        if not self.path.exists():
            self._groups = {}
            return self

        raw = self._read_payload_from(self.path)

        version = raw.get("version")
        if version == self._LEGACY_VERSION:
            raise StateFileError(
                "通知状态仍为 V1 全局格式，尚未完成按群迁移，拒绝读取以免跨群误判"
            )
        if version != self.VERSION:
            raise StateFileError("通知状态版本不受支持")

        groups_raw = raw.get("groups")
        if not isinstance(groups_raw, dict):
            raise StateFileError("通知状态中的 groups 必须是对象")

        groups: dict[str, set[str]] = {}
        for group_id, sent in groups_raw.items():
            if not isinstance(group_id, str) or not group_id:
                raise StateFileError("通知状态中的群号必须是非空字符串")
            if not isinstance(sent, list) or not all(
                isinstance(item, str) and item for item in sent
            ):
                raise StateFileError("通知状态中的已发送键必须是非空字符串列表")
            groups[group_id] = set(sent)

        self._groups = groups
        return self

    def contains(self, group_id: str, key: str) -> bool:
        return key in self._groups.get(group_id, set())

    def mark_sent(self, group_id: str, key: str) -> None:
        self.mark_sent_many(group_id, [key])

    def mark_sent_many(self, group_id: str, keys: Iterable[str]) -> None:
        if not isinstance(group_id, str) or not group_id:
            raise ValueError("群号必须是非空字符串")
        candidate_keys = list(keys)
        if not candidate_keys or any(
            not isinstance(key, str) or not key for key in candidate_keys
        ):
            raise ValueError("通知键必须是非空字符串")

        previous = self._groups.get(group_id, set())
        updated = previous | set(candidate_keys)
        if updated == previous:
            return

        self._write(group_id, updated)
        self._groups[group_id] = updated

    def keys(self, group_id: str) -> frozenset[str]:
        return frozenset(self._groups.get(group_id, set()))

    @classmethod
    def migrate_v1_file(cls, path: Path, legacy_group_id: str | None) -> bool:
        """把磁盘上的 V1 全局 sent 状态一次性迁移为指定旧目标群的 V2 分群状态。

        返回是否发生了迁移；文件缺失或已是 V2 时不做任何修改。
        新加入的其他群不会继承旧群的已发送状态。
        """

        state_path = Path(path)
        if not state_path.is_file():
            return False

        raw = cls._read_payload_from(state_path)
        version = raw.get("version")
        if version == cls.VERSION:
            return False
        if version != cls._LEGACY_VERSION:
            raise StateFileError("通知状态版本不受支持，拒绝迁移")
        if not isinstance(legacy_group_id, str) or not legacy_group_id.strip():
            raise StateFileError("缺少旧版目标群号，无法迁移 V1 通知状态")

        sent = raw.get("sent")
        if not isinstance(sent, list) or not all(
            isinstance(item, str) and item for item in sent
        ):
            raise StateFileError("通知状态中的 sent 必须是非空字符串列表")

        payload: dict[str, Any] = {
            "version": cls.VERSION,
            "groups": {legacy_group_id.strip(): sorted(set(sent))},
        }
        cls._write_payload(state_path, payload)
        return True

    @staticmethod
    def _read_payload_from(state_path: Path) -> dict[str, Any]:
        try:
            raw = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StateFileError(f"无法读取通知状态：{state_path}") from exc
        if not isinstance(raw, dict):
            raise StateFileError("通知状态根节点必须是对象")
        return raw

    def _write(self, group_id: str, sent: set[str]) -> None:
        groups = {gid: sorted(keys) for gid, keys in self._groups.items()}
        groups[group_id] = sorted(sent)
        payload: dict[str, Any] = {
            "version": self.VERSION,
            "groups": {gid: groups[gid] for gid in sorted(groups)},
        }
        self._write_payload(self.path, payload)

    @staticmethod
    def _write_payload(state_path: Path, payload: dict[str, Any]) -> None:
        temporary_path = state_path.with_name(f".{NotificationState.FILE_NAME}.tmp")

        try:
            state_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary_path.replace(state_path)
        except OSError as exc:
            raise StateFileError(f"无法写入通知状态：{state_path}") from exc
