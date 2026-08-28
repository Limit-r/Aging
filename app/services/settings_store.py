"""会话设置持久化存储（JSON 文件，gitignore 不入库）。

仅保存"需要跨重启保留"的设置项：系统设置密码 + 老化默认倒计时。
- 文件位置：<项目根>/data/settings.json
- 启动时懒加载到内存；每次修改立即落盘（临时文件 + 原子替换）。
- 与「纯会话内存」设置并存：设备绑定等仍为会话级，不落盘。
- 纯业务模块，不依赖 GUI；供 settings_access / aging_settings 复用。
"""
from __future__ import annotations

import json
import os
import tempfile
from typing import Any, Optional

from app.observability import get_logger

_log = get_logger("app.services.settings_store")


# <项目根>/data/settings.json
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(_PROJECT_ROOT, "data")
STORE_PATH = os.path.join(DATA_DIR, "settings.json")


class SettingsStore:
    """读写 <data/settings.json> 的最小持久化层。"""

    def __init__(self, path: str = STORE_PATH) -> None:
        self._path = path
        self._data: dict[str, Any] = {}

    # -- 读写 ----------------------------------------------------------------
    def load(self) -> None:
        """从磁盘加载（缺失/损坏回退空字典，不抛错）。"""
        try:
            with open(self._path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            if isinstance(raw, dict):
                self._data = raw
            _log.debug("settings store loaded: path=%s", self._path)
        except FileNotFoundError:
            _log.debug("settings store not found (first run): path=%s", self._path)
        except (ValueError, OSError) as e:
            _log.warning("settings store load failed, use empty: %r", e)

    def save(self) -> None:
        """原子写盘（临时文件 + os.replace，避免半写损坏）。

        临时文件与目标同目录，确保 os.replace 同盘原子替换（跨盘会失败）。
        """
        target_dir = os.path.dirname(self._path) or "."
        try:
            os.makedirs(target_dir, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=target_dir, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(self._data, fh, ensure_ascii=False, indent=2)
                os.replace(tmp, self._path)
            except BaseException:
                if os.path.exists(tmp):
                    os.remove(tmp)
                raise
            _log.debug("settings store saved: path=%s", self._path)
        except OSError as e:
            _log.warning("settings store save failed: %r", e)

    # -- 密码 ------------------------------------------------------------------
    def get_password(self) -> Optional[str]:
        return self._data.get("password")

    def set_password(self, password: str) -> None:
        self._data["password"] = password
        self.save()

    # -- 老化默认时长（秒）-----------------------------------------------------
    def get_aging_seconds(self) -> Optional[int]:
        return self._data.get("aging_seconds")

    def set_aging_seconds(self, seconds: Optional[int]) -> None:
        if seconds is None:
            self._data.pop("aging_seconds", None)
        else:
            self._data["aging_seconds"] = int(seconds)
        self.save()


# 会话级单例
_STORE_SESSION: "SettingsStore | None" = None


def get_settings_store() -> SettingsStore:
    """会话级单例访问器（首次调用时懒加载磁盘）。"""
    global _STORE_SESSION
    if _STORE_SESSION is None:
        _STORE_SESSION = SettingsStore()
        _STORE_SESSION.load()
    return _STORE_SESSION
