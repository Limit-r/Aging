"""数据中心页（Phase 1 占位）。

Phase 6：历史数据查询 / 趋势图 / 数据导出 / 报表生成。
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel

from app.core import labels


class DataCenterPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("subPage")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch(1)
        text = QLabel(
            labels.PAGE_PLACEHOLDER_TEMPLATE.format(
                name="数据中心",
                desc="历史数据 / 趋势 / 报表 / 导出",
                phase=labels.PAGE_PHASE_DATA,
            )
        )
        text.setObjectName("subPagePlaceholder")
        text.setAlignment(Qt.AlignCenter)
        text.setWordWrap(True)
        layout.addWidget(text, 0, Qt.AlignCenter)
        layout.addStretch(1)
