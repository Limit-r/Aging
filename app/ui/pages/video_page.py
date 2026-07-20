"""视频检测页（Phase 1 占位）。

Phase 4：72 路视频流网格 + OpenCV 采集 + OpenVINO 推理。
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel

from app.core import config, labels


class VideoDetectionPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("subPage")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch(1)
        text = QLabel(
            labels.PAGE_PLACEHOLDER_TEMPLATE.format(
                name="视频检测",
                desc=f"{config.GRID_ROWS * config.GRID_COLS} 路视频流采集 + AI 视觉识别（OpenVINO 模型）",
                phase=labels.PAGE_PHASE_VIDEO,
            )
        )
        text.setObjectName("subPagePlaceholder")
        text.setAlignment(Qt.AlignCenter)
        text.setWordWrap(True)
        layout.addWidget(text, 0, Qt.AlignCenter)
        layout.addStretch(1)
