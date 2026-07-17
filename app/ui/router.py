"""页面路由（v3.0）。

薄壳：包裹 QStackedWidget + key→widget 映射。
- register(key, widget)：注册页面（顺序与 NAV_ITEMS 保持一致）
- navigate(key)：切换到 key 对应页面
- current_key：当前页面 key
- 首次 register 自动跳到第一页
"""

from __future__ import annotations

from typing import Dict, Optional

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QStackedWidget, QWidget

from app.observability import get_logger


_log = get_logger("app.ui.router")


class PageRouter(QStackedWidget):
    """nav key → QStackedWidget index 的薄包装。"""

    page_changed = pyqtSignal(str)  # 参数：nav key

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._key_to_index: Dict[str, int] = {}
        self._index_to_key: Dict[int, str] = {}
        self._current_key: Optional[str] = None
        self.currentChanged.connect(self._on_current_changed)

    def register(self, key: str, widget: QWidget) -> None:
        """注册一个页面。key 不可重复。"""
        if key in self._key_to_index:
            _log.warning("register: key=%s already registered, ignored", key)
            return
        idx = self.addWidget(widget)
        self._key_to_index[key] = idx
        self._index_to_key[idx] = key
        _log.info("register page: key=%s index=%d widget=%s",
                  key, idx, type(widget).__name__)
        if self._current_key is None:
            self._current_key = key
            self.setCurrentIndex(idx)

    def navigate(self, key: str) -> None:
        """切换到 key 对应页面；key 不存在则 noop。"""
        idx = self._key_to_index.get(key)
        if idx is None:
            _log.warning("navigate: key=%s not registered, ignored", key)
            return
        if self.currentIndex() != idx:
            self.setCurrentIndex(idx)

    @property
    def current_key(self) -> Optional[str]:
        return self._current_key

    def _on_current_changed(self, idx: int) -> None:
        key = self._index_to_key.get(idx)
        if key is not None and key != self._current_key:
            self._current_key = key
            self.page_changed.emit(key)
