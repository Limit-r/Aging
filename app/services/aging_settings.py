"""老化倒计时全局设置（会话内存，不落盘，重启即恢复默认）。

业务语义（来自用户澄清）：
- 全局默认老化时长 **2 小时**，用户可在设置页修改倒计时时长。
- 仅会话内存生效，重启恢复默认 2h。

设计：
- 纯业务，可脱离 GUI 单测；会话内单例（`get_aging_settings()`）。
- 只保存用户覆盖值（override）；未覆盖时返回默认，满足最小改动。
- `changed` 信号供设置页/其它页面在会话内联动刷新。
"""
from __future__ import annotations

from PyQt5.QtCore import QObject, pyqtSignal

# 默认老化时长（秒）：2 小时
DEFAULT_AGING_SECONDS = 2 * 60 * 60
# 允许的最小倒计时（秒）
MIN_AGING_SECONDS = 60
# 允许的最大倒计时（秒）
MAX_AGING_SECONDS = 24 * 60 * 60

# 会话级单例
_AGING_SESSION: "AgingSettings | None" = None


class AgingSettings(QObject):
    """会话级老化倒计时全局设置。"""

    changed = pyqtSignal()

    def __init__(self, parent: "QObject | None" = None) -> None:
        super().__init__(parent)
        self._override_seconds: "int | None" = None

    # -- 读写 ----------------------------------------------------------------
    @property
    def aging_seconds(self) -> int:
        return self._override_seconds or DEFAULT_AGING_SECONDS

    def set_aging_seconds(self, seconds: int) -> None:
        """设置老化时长（秒）。空/越界回退默认值；不变则不发信号。"""
        seconds = int(seconds)
        if seconds is None or not (MIN_AGING_SECONDS <= seconds <= MAX_AGING_SECONDS):
            seconds = DEFAULT_AGING_SECONDS
        if self.aging_seconds != seconds:
            self._override_seconds = seconds
            self._emit_change()

    def reset(self) -> None:
        if self._override_seconds is not None:
            self._override_seconds = None
            self._emit_change()

    # -- 便捷格式化 ----------------------------------------------------------
    def aging_hours(self) -> float:
        return self.aging_seconds / 3600.0

    # -- 内部 ---------------------------------------------------------------
    def _emit_change(self) -> None:
        try:
            self.changed.emit()
        except RuntimeError:
            pass  # 退出阶段控件可能已销毁


def get_aging_settings(parent: "QObject | None" = None) -> AgingSettings:
    """会话级单例访问器（懒加载）。"""
    global _AGING_SESSION
    if _AGING_SESSION is None:
        _AGING_SESSION = AgingSettings(parent)
    return _AGING_SESSION