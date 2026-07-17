"""系统设置页（Phase 1 占位）。

Phase 6：阈值配置 / 模型选择 / 串口配置 / 摄像头配置 / 用户偏好。
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel

from app.core import labels


class SettingsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("subPage")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch(1)
        text = QLabel(
            labels.PAGE_PLACEHOLDER_TEMPLATE.format(
                name="系统设置",
                desc="阈值 / 模型 / 设备 / 用户偏好",
                phase=labels.PAGE_PHASE_SETTINGS,
            )
        )
        text.setObjectName("subPagePlaceholder")
        text.setAlignment(Qt.AlignCenter)
        text.setWordWrap(True)
        layout.addWidget(text, 0, Qt.AlignCenter)
        layout.addStretch(1)
