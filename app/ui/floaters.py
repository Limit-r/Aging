"""v3.0 主页浮窗层组件（3D 全屏 + HUD 浮窗叠加）。

设计目标：
- 3D 机柜视图占满整个 HomeDashboard
- 4 个浮窗 widget 绝对定位在 3D 之上（左信息 / 中央标题 / 右告警 / 右下 HUD）
- 1 个"立即复位"按钮在右上角（不显眼）
- 浮窗默认半透明 + 发光描边，让 3D 透过来
- 不拦截鼠标事件（穿透到下层 GLViewWidget）

依赖：Qt5 / app.core.tokens / app.core.labels
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QFrame, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QSizePolicy,
)

from app.core import config, labels
from app.core.tokens import DEFAULT_TOKENS
from app.observability import get_logger


_log = get_logger("app.ui.floaters")

# 取一次 sizing 引用（避免每个构造里 4 次访问）
_S = DEFAULT_TOKENS.sizing


# ============================================================================
# 右浮窗：最近告警
# ============================================================================
class RightAlertsFloater(QFrame):
    """右上角告警浮窗（最近 3 条）。"""

    def __init__(self, parent: Optional[QFrame] = None):
        super().__init__(parent)
        self.setObjectName("floaterPanel")
        self.setProperty("side", "right")  # QSS 边框色按 side 切换
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setFixedWidth(_S.FLOATER_W)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            _S.FLOATER_MARGIN_H, _S.FLOATER_MARGIN_V,
            _S.FLOATER_MARGIN_H, _S.FLOATER_MARGIN_V,
        )
        layout.setSpacing(_S.FLOATER_SPACING)

        title = QLabel(labels.HUD_ALERTS_TITLE)
        title.setObjectName("floaterTitle")
        layout.addWidget(title)

        self._empty = QLabel(labels.HUD_ALERTS_EMPTY)
        self._empty.setObjectName("floaterBody")
        layout.addWidget(self._empty)
        layout.addStretch(1)

    def set_alerts(self, alerts: List[Tuple[int, str]]) -> None:
        if not alerts:
            self._empty.setText(labels.HUD_ALERTS_EMPTY)
            return
        # 显示最近 3 条
        lines = [
            labels.HUD_ALERT_ITEM_TEMPLATE.format(cid=cid, reason=reason)
            for cid, reason in alerts[:3]
        ]
        self._empty.setText("\n".join(lines))


# ============================================================================
# 右下浮窗：运行 / 暂停 / 停止 计数
# ============================================================================
class BottomRightHUDFloater(QFrame):
    """右下角 HUD 浮窗：系统状态计数。"""

    def __init__(self, parent: Optional[QFrame] = None):
        super().__init__(parent)
        self.setObjectName("floaterPanel")
        self.setProperty("side", "bottomright")  # QSS 边框色按 side 切换
        self.setFixedWidth(_S.FLOATER_W)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            _S.FLOATER_MARGIN_H, _S.FLOATER_MARGIN_V,
            _S.FLOATER_MARGIN_H, _S.FLOATER_MARGIN_V,
        )
        layout.setSpacing(_S.FLOATER_SPACING)

        title = QLabel(labels.HUD_SYSTEM_STATS_TITLE)
        title.setObjectName("floaterTitle")
        layout.addWidget(title)

        total = config.GRID_ROWS * config.GRID_COLS
        self._run_label = QLabel(
            labels.HUD_SYSTEM_STATS_RUNNING_TEMPLATE.format(n=0, total=total)
        )
        self._run_label.setObjectName("floaterBody")
        layout.addWidget(self._run_label)

        self._pause_label = QLabel(
            labels.HUD_SYSTEM_STATS_PAUSED_TEMPLATE.format(n=0, total=total)
        )
        self._pause_label.setObjectName("floaterBody")
        layout.addWidget(self._pause_label)

        self._stop_label = QLabel(
            labels.HUD_SYSTEM_STATS_STOPPED_TEMPLATE.format(n=total, total=total)
        )
        self._stop_label.setObjectName("floaterBody")
        layout.addWidget(self._stop_label)
        layout.addStretch(1)

    def set_counts(self, running: int, paused: int, stopped: int) -> None:
        total = config.GRID_ROWS * config.GRID_COLS
        self._run_label.setText(
            labels.HUD_SYSTEM_STATS_RUNNING_TEMPLATE.format(n=running, total=total)
        )
        self._pause_label.setText(
            labels.HUD_SYSTEM_STATS_PAUSED_TEMPLATE.format(n=paused, total=total)
        )
        self._stop_label.setText(
            labels.HUD_SYSTEM_STATS_STOPPED_TEMPLATE.format(n=stopped, total=total)
        )


# ============================================================================
# 8 行 × 9 列 LED 状态点竖条浮窗（Phase 1.19）
# ============================================================================
class RightLEDStripFloater(QFrame):
    """右侧 8 行 × 9 列 LED 状态点矩阵浮窗。

    视觉：一行 9 个小圆点，对应 9 列；8 行对应 8 row。
    颜色映射：与 Rack3DView.LEDState 一致。
    """

    def __init__(self, parent: Optional[QFrame] = None):
        super().__init__(parent)
        self.setObjectName("floaterPanel")
        self.setProperty("side", "ledstrip")  # QSS 边框色按 side 切换
        self.setFixedWidth(_S.FLOATER_W)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            _S.FLOATER_MARGIN_H, _S.FLOATER_MARGIN_V,
            _S.FLOATER_MARGIN_H, _S.FLOATER_MARGIN_V,
        )
        layout.setSpacing(_S.FLOATER_LED_SPACING)

        # 标题
        title = QLabel("● 状态矩阵  //  STATUS MATRIX")
        title.setObjectName("floaterTitle")
        layout.addWidget(title)

        # 8 行 × 9 列
        self._cell_labels: List[QLabel] = []
        c = DEFAULT_TOKENS.colors
        # LED 状态 → CSS 背景色（rgba）
        self._color_map = {
            "offline": f"rgba({c.LED_OFFLINE[0]}, {c.LED_OFFLINE[1]}, {c.LED_OFFLINE[2]}, 0.6)",
            "running": f"rgba({c.LED_RUNNING[0]}, {c.LED_RUNNING[1]}, {c.LED_RUNNING[2]}, 0.95)",
            "paused":  f"rgba({c.LED_PAUSED[0]}, {c.LED_PAUSED[1]}, {c.LED_PAUSED[2]}, 0.95)",
            "alert":   f"rgba({c.LED_ALERT[0]}, {c.LED_ALERT[1]}, {c.LED_ALERT[2]}, 0.95)",
            "warning": f"rgba({c.LED_WARNING[0]}, {c.LED_WARNING[1]}, {c.LED_WARNING[2]}, 0.95)",
        }

        for row in range(config.GRID_ROWS):
            row_layout = QHBoxLayout()
            row_layout.setSpacing(_S.FLOATER_LED_ROW_SPACING)
            row_layout.setContentsMargins(0, 0, 0, 0)
            # 行号
            row_label = QLabel(f"{row + 1:02d}")
            row_label.setObjectName("floaterBody")
            row_label.setFixedWidth(_S.FLOATER_LED_ROW_LABEL_W)
            row_label.setAlignment(Qt.AlignCenter)
            row_layout.addWidget(row_label)
            # 9 个小圆点
            for col in range(config.GRID_COLS):
                dot = QLabel("●")
                dot.setFixedSize(
                    _S.FLOATER_LED_DOT_SIZE, _S.FLOATER_LED_DOT_SIZE,
                )
                dot.setAlignment(Qt.AlignCenter)
                # 初始：offline 灰
                dot.setStyleSheet(
                    f"color: {self._color_map['offline']}; background: transparent;"
                )
                self._cell_labels.append(dot)
                row_layout.addWidget(dot)
            row_layout.addStretch(1)
            layout.addLayout(row_layout)

        # 默认全部置为 OFFLINE
        self.set_led_state_all("offline")

    def set_led_state(self, cid: int, state: str) -> None:
        """更新单个 LED 状态色（cid 1..72）。"""
        if cid < 1 or cid > len(self._cell_labels):
            return
        color = self._color_map.get(state, self._color_map["offline"])
        self._cell_labels[cid - 1].setStyleSheet(
            f"color: {color}; background: transparent;"
        )

    def set_led_state_all(self, state: str) -> None:
        """批量设置所有点同一状态。"""
        for lbl in self._cell_labels:
            color = self._color_map.get(state, self._color_map["offline"])
            lbl.setStyleSheet(
                f"color: {color}; background: transparent;"
            )

    def set_led_state_batch(self, state_map) -> None:
        """批量设置多个点（state_map: {cid: state}）。"""
        for cid, state in state_map.items():
            self.set_led_state(cid, state)


# ============================================================================
# 右上角"立即复位"按钮（不显眼）
# ============================================================================
class ResetViewButton(QPushButton):
    """右上角"立即复位"按钮：把 3D 相机角度恢复初始 + 暂停自动旋转。"""

    clicked_reset = pyqtSignal()  # HomeDashboard 监听，触发相机复位

    def __init__(self, parent: Optional[QFrame] = None):
        super().__init__("⟲  复位视角", parent)
        self.setObjectName("resetViewButton")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(
            DEFAULT_TOKENS.sizing.RESET_BTN_W,
            DEFAULT_TOKENS.sizing.RESET_BTN_H,
        )
        # QSS 由 templates.reset_view_button() 全局接管
        self.setToolTip("把 3D 视角复位到初始位置（不打断数据）")
        self.clicked.connect(self.clicked_reset.emit)
