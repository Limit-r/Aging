"""顶部导航栏（v3.0 主页）。

视觉（Phase 1.20 UI 升级）：
- 60px 高，顶部 1px 高光 / 底部 1px 描边（"工业面板"感）
- 品牌区："⚡ AGING CONSOLE" 左侧，加 1px 右侧分隔线
- Nav 按钮：选中态加 2px 底部亮青发光条（macOS tab 风格）
- 未选中：透明背景 + 暗色文字
- hover：浅亮蓝透明 + 文字变亮
- 右侧版本号 v3.0

行为：
- 点击任一 nav 按钮 → 发出 nav_requested(key) 信号
- 当前选中的按钮高亮（dynamic property "active"）
- HomePage 收到信号后切换 QStackedWidget
- v3.0 设置为单选：所有 nav 按钮互斥
"""

from __future__ import annotations

from typing import Dict, Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton, QButtonGroup, QSizePolicy,
    QFrame,
)

from app.core import labels
from app.core.tokens import DEFAULT_TOKENS
from app.observability import get_logger


_log = get_logger("app.ui.nav_bar")


# ============================================================================
# 完整 QSS 样式（Phase 1.20 UI 升级）
# ============================================================================
def _build_nav_qss() -> str:
    """返回 TopNavBar + NavButton + 品牌/版本号 完整 QSS。"""
    c = DEFAULT_TOKENS.colors
    f = DEFAULT_TOKENS.fonts
    return f"""
/* ---- 整体 nav 容器：上下细高光 + 暗色背景 ----------------------------- */
QWidget#topNavBar {{
    background-color: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 {c.BG_TITLE_BAR},
        stop:0.5 {c.BG_BASE},
        stop:1 {c.BG_DEEP});
    border-top: 1px solid rgba(0, 191, 255, 60);
    border-bottom: 1px solid {c.BORDER_PRIMARY};
}}

/* ---- 品牌区：左侧大写 + 1px 右侧分隔线 --------------------------------- */
QLabel#navBrand {{
    color: {c.TEXT_NEON_CYAN};
    font-family: {f.FAMILY_TITLE};
    font-size: 14pt;
    font-weight: bold;
    letter-spacing: 3px;
    background: transparent;
    padding: 0 24px 0 8px;
    border-right: 1px solid rgba(0, 191, 255, 50);
}}

QLabel#navVersion {{
    color: {c.TEXT_DIM};
    font-family: {f.FAMILY_MONO};
    font-size: 10pt;
    font-weight: bold;
    letter-spacing: 2px;
    background: transparent;
    padding: 0 16px;
}}

/* ---- Nav 按钮：默认态（透明 + 暗色文字）------------------------------- */
QPushButton#navButton {{
    background-color: transparent;
    color: {c.TEXT_SECONDARY};
    border: none;
    border-bottom: 2px solid transparent;
    border-radius: 0px;
    padding: 0 20px;
    min-height: 50px;
    font-family: {f.FAMILY_MONO};
    font-size: 12pt;
    font-weight: bold;
    letter-spacing: 1px;
    text-align: center;
}}

/* ---- Nav 按钮：hover 态（暗亮蓝背景 + 文字变亮）---------------------- */
QPushButton#navButton:hover {{
    background-color: rgba(0, 191, 255, 25);
    color: {c.TEXT_PRIMARY};
    border-bottom: 2px solid rgba(0, 229, 255, 120);
}}

/* ---- Nav 按钮：active 选中态（顶部到底色加深 + 底部亮青发光条）-------- */
QPushButton#navButton[active="true"] {{
    background-color: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(0, 191, 255, 35),
        stop:1 rgba(0, 191, 255, 8));
    color: {c.TEXT_NEON_CYAN};
    border-bottom: 2px solid {c.TEXT_NEON_CYAN};
}}

QPushButton#navButton[active="true"]:hover {{
    background-color: rgba(0, 191, 255, 60);
    color: {c.TEXT_NEON_CYAN};
    border-bottom: 2px solid {c.TEXT_NEON_CYAN};
}}

/* ---- Nav 按钮：pressed 态（短按下反馈）------------------------------- */
QPushButton#navButton:pressed {{
    background-color: rgba(0, 191, 255, 80);
    color: {c.BG_DEEP};
}}
"""


# ============================================================================
# Nav 按钮
# ============================================================================
class NavButton(QPushButton):
    """Nav 按钮：扁平、动态 active 状态。"""
    def __init__(self, key: str, label: str, tooltip: str, parent: Optional[QWidget] = None):
        super().__init__(label, parent)
        self._key = key
        self.setObjectName("navButton")
        self.setProperty("active", False)
        self.setToolTip(tooltip)
        self.setCursor(Qt.PointingHandCursor)
        self.setCheckable(True)
        # 不写死高度，让 QSS 用最小高度；QSS 通过 #navButton 选择器定义

    @property
    def key(self) -> str:
        return self._key

    def set_active(self, active: bool) -> None:
        if self.property("active") != active:
            self.setProperty("active", active)
            # 主动重绘（避免 QSS 缓存）
            self.style().unpolish(self)
            self.style().polish(self)


# ============================================================================
# 顶部导航栏
# ============================================================================
class TopNavBar(QWidget):
    """顶部导航栏 widget。"""
    nav_requested = pyqtSignal(str)  # 参数：nav key

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("topNavBar")
        self.setFixedHeight(60)
        self._buttons: Dict[str, NavButton] = {}
        self._active_key: Optional[str] = None
        # 应用 QSS
        self.setStyleSheet(_build_nav_qss())
        self._build_ui()
        # 默认激活第一项（home）
        self.set_active("home")

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 品牌区
        brand = QLabel(
            f"{labels.NAV_BRAND_GLYPH}  {labels.NAV_BRAND_TEXT}"
        )
        brand.setObjectName("navBrand")
        brand.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        layout.addWidget(brand)

        # Nav 按钮组（互斥）
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for key, label, tooltip in labels.NAV_ITEMS:
            btn = NavButton(key, label, tooltip, self)
            btn.clicked.connect(
                lambda _checked, k=key: self._on_btn_clicked(k)
            )
            self._group.addButton(btn)
            self._buttons[key] = btn
            layout.addWidget(btn)

        # 右侧弹性
        layout.addStretch(1)

        # 右侧版本号
        version = QLabel("v3.0")
        version.setObjectName("navVersion")
        version.setAlignment(Qt.AlignVCenter | Qt.AlignRight)
        layout.addWidget(version)

    def _on_btn_clicked(self, key: str) -> None:
        _log.info("nav requested: %s", key)
        self.set_active(key)
        self.nav_requested.emit(key)

    def set_active(self, key: str) -> None:
        """设置当前激活的 nav 按钮。"""
        if self._active_key == key:
            return
        for k, btn in self._buttons.items():
            btn.set_active(k == key)
        self._active_key = key
