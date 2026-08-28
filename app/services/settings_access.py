"""系统设置页访问门禁：密码验证（每次进入均需验证）。

业务语义：
- 进入系统设置每次都要验证密码；默认密码 `admin123`，可在设置页内修改。
- **无会话解锁态**：不保存"已验证过"的状态，每次导航到设置页都重新弹密码框，
  避免首次进入后本会话内免密直达的安全隐患。
- 密码持久化到本地文件（settings_store），重启保留。
- 修改密码的校验规则（长度/二次确认）以业务错误码返回，由 UI 层映射到 labels。
"""
from __future__ import annotations

from PyQt5.QtCore import QObject, pyqtSignal

from app.observability import get_logger
from app.services.settings_store import get_settings_store

_log = get_logger("app.services.settings_access")

# 默认密码（首登可用，进入设置后建议修改）
DEFAULT_PASSWORD = "admin123"
# 新密码最短长度
MIN_PASSWORD_LEN = 6

# 修改密码返回的错误码（空串 = 成功）
ERR_WRONG_CURRENT = "wrong_current"
ERR_TOO_SHORT = "too_short"
ERR_MISMATCH = "mismatch"

# 会话级单例
_ACCESS_SESSION: "SettingsAccess | None" = None


class SettingsAccess(QObject):
    """设置页密码门禁服务（会话级单例，无免密解锁态）。"""

    password_changed = pyqtSignal()       # 密码被修改/重置

    def __init__(self, parent: "QObject | None" = None) -> None:
        super().__init__(parent)
        self._store = get_settings_store()
        # 从持久化读取；无记录则回退默认密码
        self._password = self._store.get_password() or DEFAULT_PASSWORD

    # -- 查询 ----------------------------------------------------------------
    def is_default_password(self) -> bool:
        return self._password == DEFAULT_PASSWORD

    @property
    def default_password(self) -> str:
        return DEFAULT_PASSWORD

    def verify(self, password: str) -> bool:
        return password == self._password

    # -- 修改 / 恢复 ---------------------------------------------------------
    def change_password(self, current: str, new: str, confirm: str) -> str:
        """修改密码：校验当前密码 + 新密码规则。

        返回空串表示成功；否则返回业务错误码（ERR_*）。
        """
        if not self.verify(current):
            return ERR_WRONG_CURRENT
        if len(new) < MIN_PASSWORD_LEN:
            return ERR_TOO_SHORT
        if new != confirm:
            return ERR_MISMATCH
        self._password = new
        self._store.set_password(new)
        self.password_changed.emit()
        _log.info("settings password changed")
        return ""

    def reset_password(self) -> None:
        """恢复为默认密码（同步落盘）。"""
        self._password = DEFAULT_PASSWORD
        self._store.set_password(DEFAULT_PASSWORD)
        self.password_changed.emit()
        _log.info("settings password reset to default")


def get_settings_access(parent: "QObject | None" = None) -> SettingsAccess:
    """会话级单例访问器（懒加载）。"""
    global _ACCESS_SESSION
    if _ACCESS_SESSION is None:
        _ACCESS_SESSION = SettingsAccess(parent)
    return _ACCESS_SESSION
