"""v3.0 视频检测·总览页（位置标记视图）。

本页只做**位点标记**：以 9×8 网格展示全部检测位点（CH-01 … CH-72），
**不显示检测结果**。双击某位点 → 发出 `open_stream_requested(cid)`，
由 HomePage 路由跳转到该通道的视频流检测页（video_stream）。

布局参考电流检测页的 9×8 网格，但每个单元仅是位置标签。
"""
from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget,
)

from app.core import config, labels
from app.core.tokens import DEFAULT_TOKENS
from app.observability import get_logger, narrative

_S = DEFAULT_TOKENS.sizing
_log = get_logger("app.ui.pages.video_page")


class VideoMarkCell(QFrame):
    """位点标记单元：CH-XX + 位点序号 + 双击进入提示。"""
    opened = pyqtSignal(int)  # 双击 → 打开该通道视频流检测页

    def __init__(self, cid: int, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.cell_id = cid
        self.setObjectName("videoCell")
        self.setMinimumSize(_S.VIDEO_CELL_MIN_W, _S.VIDEO_CELL_MIN_H)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(labels.CELL_OPEN_HINT)
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.setSpacing(4)

        head = QHBoxLayout()
        head.setSpacing(6)
        header = QLabel(labels.CELL_HEADER_TEMPLATE.format(cid=self.cell_id))
        header.setObjectName("videoCellHeader")
        head.addWidget(header)
        head.addStretch(1)
        outer.addLayout(head)

        mark = QLabel(labels.CELL_MARK_TEMPLATE.format(cid=self.cell_id))
        mark.setObjectName("videoCellMark")
        mark.setAlignment(Qt.AlignCenter)
        outer.addWidget(mark, 1)

        hint = QLabel(labels.CELL_OPEN_HINT)
        hint.setObjectName("videoCellHint")
        hint.setAlignment(Qt.AlignCenter)
        outer.addWidget(hint)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            _log.info("video mark dblclick: open stream cid=%d", self.cell_id)
            self.opened.emit(self.cell_id)
            return
        super().mouseDoubleClickEvent(event)


class VideoOverviewPage(QWidget):
    """视频总览：位点标记网格。"""
    open_stream_requested = pyqtSignal(int)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("videoPage")
        self._total = config.GRID_ROWS * config.GRID_COLS
        self._build_ui()
        narrative.event(
            "video_overview_init",
            note="v3.0 视频总览：位点标记网格（双击进入视频流检测）")

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # 顶部信息条
        bar = QFrame(self)
        bar.setObjectName("videoToolbar")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(12, 0, 12, 0)
        bl.setSpacing(10)
        title = QLabel(labels.VIDEO_OVERVIEW_TITLE)
        title.setObjectName("videoTitle")
        bl.addWidget(title)
        subtitle = QLabel(labels.VIDEO_OVERVIEW_SUBTITLE_TEMPLATE.format(
            rows=config.GRID_ROWS, cols=config.GRID_COLS,
            total=self._total))
        subtitle.setObjectName("videoInfo")
        bl.addWidget(subtitle)
        bl.addStretch(1)
        hint = QLabel(labels.VIDEO_OVERVIEW_HINT)
        hint.setObjectName("videoInfo")
        bl.addWidget(hint)
        outer.addWidget(bar)

        # 位点网格
        grid = QGridLayout()
        grid.setContentsMargins(_S.VIDEO_GRID_MARGIN, _S.VIDEO_GRID_MARGIN,
                                _S.VIDEO_GRID_MARGIN, _S.VIDEO_GRID_MARGIN)
        grid.setHorizontalSpacing(_S.VIDEO_GRID_SPACING)
        grid.setVerticalSpacing(_S.VIDEO_GRID_SPACING)
        for c in range(config.GRID_COLS):
            grid.setColumnStretch(c, 1)
        for r in range(config.GRID_ROWS):
            grid.setRowStretch(r, 1)

        for cid in range(1, self._total + 1):
            cell = VideoMarkCell(cid, self)
            cell.opened.connect(self.open_stream_requested.emit)
            row = (cid - 1) // config.GRID_COLS
            col = (cid - 1) % config.GRID_COLS
            grid.addWidget(cell, row, col)

        outer.addLayout(grid, 1)