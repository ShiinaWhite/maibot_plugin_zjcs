from __future__ import annotations

import json
from pathlib import Path
from collections.abc import Iterable
from typing import Any


class StateFileError(ValueError):
    """持久化状态不可安全读取或写入。"""


class NotificationState:
    """使用插件数据目录保存已发送通知键。"""

    VERSION = 1
    FILE_NAME = "notification_state.json"

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._sent: set[str] = set()

    def load(self) -> NotificationState:
        if not self.path.exists():
            self._sent = set()
            return self

        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StateFileError(f"无法读取通知状态：{self.path}") from exc

        if not isinstance(raw, dict) or raw.get("version") != self.VERSION:
            raise StateFileError("通知状态版本不受支持")

        sent = raw.get("sent")
        if not isinstance(sent, list) or not all(
            isinstance(item, str) and item for item in sent
        ):
            raise StateFileError("通知状态中的 sent 必须是非空字符串列表")

        self._sent = set(sent)
        return self

    def contains(self, key: str) -> bool:
        return key in self._sent

    def mark_sent(self, key: str) -> None:
        self.mark_sent_many([key])

    def mark_sent_many(self, keys: Iterable[str]) -> None:
        candidate_keys = list(keys)
        if not candidate_keys or any(
            not isinstance(key, str) or not key for key in candidate_keys
        ):
            raise ValueError("通知键必须是非空字符串")
        normalized = set(candidate_keys)

        updated = self._sent | normalized
        if updated == self._sent:
            return

        self._write(updated)
        self._sent = updated

    def keys(self) -> frozenset[str]:
        return frozenset(self._sent)

    def _write(self, sent: set[str]) -> None:
        payload: dict[str, Any] = {
            "version": self.VERSION,
            "sent": sorted(sent),
        }
        temporary_path = self.path.with_name(f".{self.FILE_NAME}.tmp")

        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary_path.replace(self.path)
        except OSError as exc:
            raise StateFileError(f"无法写入通知状态：{self.path}") from exc
