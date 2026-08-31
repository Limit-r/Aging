"""数据中心 · 历史 / 趋势 / 导出 · 会话回看（电流侧）。

把已落盘的电流会话从 `ml/detection_logs/` 枚举为「设备 → 启动」两级列表，
选中后在右侧用 read_device_log 重建单设备 **I-t 曲线**。
- 有效段（valid=1）连续绘制；空/未上载段（valid=0）跳过留空，避免画成假 0 电流。
- 复用 detail_page 的 PlotWidget 曲线配色与深色背景，保持一致观感。
- 列表样式复用 `QListWidget#dcList`，无需新增 QSS 模板。
"""

import datetime
import math
from pathlib import Path
from typing import List, Optional

import pyqtgraph as pg
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QSizePolicy, QSplitter, QVBoxLayout, QWidget,
)

from app.core import config, labels
from app.core.formatting import format_cid, format_hms
from app.core.tokens import DEFAULT_TOKENS
from app.observability import get_logger, narrative
from app.services.current_recorder import detection_log_root, inspect_device_log, read_device_log

_log = get_logger("app.ui.pages.history_page")

# 4 路电流曲线颜色（复用 detail_page：LED_* RGBA 4 元组）
_CURVE_COLORS = (
    DEFAULT_TOKENS.colors.LED_RUNNING,   # I1
    DEFAULT_TOKENS.colors.LED_PAUSED,    # I2
    DEFAULT_TOKENS.colors.LED_WARNING,   # I3
    DEFAULT_TOKENS.colors.LED_HOVER,     # I4
)


def _format_start(wall_ms: int) -> str:
    return datetime.datetime.fromtimestamp(wall_ms / 1000.0).strftime("%m-%d %H:%M:%S")


class DetectionHistoryPage(QWidget):
    """历史会话回看：两级会话列表 + 单设备 I-t 曲线。"""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._s = DEFAULT_TOKENS.sizing
        self._session_path: Optional[Path] = None
        self._curves: List[pg.PlotDataItem] = []
        self._build_ui()
        self._rescan()

    # -- UI ----------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, self._s.DATA_PAGE_SPACING, 0, 0)
        root.setSpacing(self._s.DATA_PAGE_SPACING)

        # 顶部概览
        overview = QLabel(labels.HISTORY_LIST_TITLE)
        overview.setObjectName("dcTrainOverview")
        root.addWidget(overview)

        body = QSplitter(Qt.Horizontal)
        body.setChildrenCollapsible(False)
        body.addWidget(self._build_list_pane())
        body.addWidget(self._build_detail_pane())
        body.setStretchFactor(0, 1)
        body.setStretchFactor(1, 3)
        root.addWidget(body, 1)

        hint = QLabel(labels.HISTORY_INVALID_HINT)
        hint.setObjectName("dcTrainHint")
        root.addWidget(hint)

    def _build_list_pane(self) -> QWidget:
        pane = QWidget()
        lay = QVBoxLayout(pane)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(self._s.DATA_PAGE_SPACING)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.addStretch(1)
        refresh = QPushButton(labels.HISTORY_REFRESH)
        refresh.setObjectName("dcGhostBtn")
        refresh.setCursor(Qt.PointingHandCursor)
        refresh.clicked.connect(self._rescan)
        btn_row.addWidget(refresh)
        lay.addLayout(btn_row)

        self._list = QListWidget()
        self._list.setObjectName("dcList")
        self._list.currentItemChanged.connect(self._on_current_changed)
        lay.addWidget(self._list, 1)
        return pane

    def _build_detail_pane(self) -> QWidget:
        pane = QFrame()
        pane.setObjectName("dcSidePanel")
        lay = QVBoxLayout(pane)
        lay.setContentsMargins(
            self._s.DETAIL_HEADER_MARGIN_H, self._s.DATA_PAGE_SPACING,
            self._s.DETAIL_HEADER_MARGIN_H, self._s.DATA_PAGE_SPACING,
        )
        lay.setSpacing(self._s.DATA_PAGE_SPACING)

        self._title = QLabel(labels.HISTORY_NO_SELECTED)
        self._title.setObjectName("dcPanelTitle")
        lay.addWidget(self._title)

        self._meta = QLabel("")
        self._meta.setObjectName("dcTrainHint")
        lay.addWidget(self._meta)

        # 详情分两个区块：电流 I-t 与状态灯（同为折线图），强制 1:1 平分。
        # - 两个 block 显式 Expanding，让 splitter 在拉伸方向上对称扩张
        # - 状态灯块目前只装提示文本（偏小），sizePolicy 不强制会按内容尺寸 → 撑不满
        # - setSizes 在首次 showEvent 里执行，否则布局尚未就绪会被 splitter 忽略
        self._detail_sizer = QSplitter(Qt.Vertical)
        self._detail_sizer.setChildrenCollapsible(False)
        current_block = self._build_current_block()
        led_block = self._build_led_block()
        for w in (current_block, led_block):
            w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._detail_sizer.addWidget(current_block)
        self._detail_sizer.addWidget(led_block)
        self._detail_sizer.setStretchFactor(0, 1)
        self._detail_sizer.setStretchFactor(1, 1)
        lay.addWidget(self._detail_sizer, 1)
        return pane

    def showEvent(self, event) -> None:  # noqa: D401  Qt 事件钩子
        """首次显示时把 splitter 强制 1:1 初始尺寸，绕过"按内容分配"的默认行为。"""
        super().showEvent(event)
        sizes = self._detail_sizer.sizes()
        total = sum(sizes) or 1
        if sizes and (sizes[0] != sizes[1]):
            half = total // 2
            self._detail_sizer.setSizes([half, total - half])

    def _section_header(self, text: str) -> QLabel:
        cap = QLabel(text)
        cap.setObjectName("dcTrainSectionTitle")
        return cap

    def _build_current_block(self) -> QWidget:
        """区块 1：电流 I-t 曲线。"""
        frame = QFrame()
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(self._s.DATA_PAGE_SPACING)

        lay.addWidget(self._section_header(labels.HISTORY_CURRENT_SECTION))

        bg = DEFAULT_TOKENS.colors.RACK_3D_BG
        self._plot = pg.PlotWidget()
        self._plot.setObjectName("detailPlot")
        self._plot.setBackground((bg[0] / 255.0, bg[1] / 255.0, bg[2] / 255.0))
        self._plot.showGrid(x=True, y=True, alpha=0.3)
        self._plot.setLabel("left", labels.CHART_CURRENT_Y_LABEL)
        self._plot.setLabel("bottom", labels.CHART_X_LABEL)
        for i in range(4):
            self._curves.append(self._plot.plot(
                pen=pg.mkPen(
                    (_CURVE_COLORS[i][0], _CURVE_COLORS[i][1], _CURVE_COLORS[i][2]),
                    width=2,
                ),
                name=labels.CHART_LEGEND_CURRENT_NAMES[i],
            ))
        lay.addWidget(self._plot, 1)
        return frame

    def _build_led_block(self) -> QWidget:
        """区块 2：状态灯区。LED 逐秒记录落盘后在此绘制亮/灭方波，当前为占位。"""
        frame = QFrame()
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(self._s.DATA_PAGE_SPACING)

        lay.addWidget(self._section_header(labels.HISTORY_LED_SECTION))

        holder = QFrame()
        holder.setObjectName("dcSidePanel")
        hlay = QVBoxLayout(holder)
        hlay.setContentsMargins(
            self._s.DETAIL_HEADER_MARGIN_H, self._s.DATA_PAGE_SPACING,
            self._s.DETAIL_HEADER_MARGIN_H, self._s.DATA_PAGE_SPACING,
        )
        hlay.addStretch(1)
        pending = QLabel(labels.HISTORY_LED_PENDING)
        pending.setObjectName("dcTrainHint")
        pending.setWordWrap(True)
        pending.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        hlay.addWidget(pending, 0, Qt.AlignHCenter)
        hlay.addStretch(1)
        lay.addWidget(holder, 1)
        return frame

    # -- 会话扫描 -----------------------------------------------------------
    def _rescan(self) -> None:
        """枚举 ml/detection_logs/<CH-XX>/*.bin → 两级列表（设备标题 + 启动会话）。"""
        self._list.clear()
        self._session_path = None
        self._title.setText(labels.HISTORY_NO_SELECTED)
        self._meta.setText("")
        for curve in self._curves:
            curve.setData([], [])

        root = detection_log_root()
        if not root.exists():
            self._list.addItem(labels.HISTORY_EMPTY)
            return

        # 按设备 cid 分组
        by_cid: dict[int, list] = {}
        for path in sorted(root.glob("*/*.bin")):
            try:
                header, n, first_ts, last_ts = inspect_device_log(path)
            except Exception as e:  # noqa: BLE001 单个坏文件不阻断扫描
                _log.warning("skip unreadable session %s: %r", path, e)
                continue
            if n <= 0 or first_ts is None:
                continue
            by_cid.setdefault(header[1], []).append((path, header, n, first_ts, last_ts))

        if not by_cid:
            self._list.addItem(labels.HISTORY_EMPTY)
            return

        for cid in sorted(by_cid):
            device_item = QListWidgetItem(format_cid(cid))
            device_item.setFlags(Qt.NoItemFlags)  # 设备标题不可选
            self._list.addItem(device_item)
            for path, header, n, first_ts, last_ts in by_cid[cid]:
                dur_s = max(0, int((last_ts or first_ts) - first_ts))
                text = labels.HISTORY_SESSION_TEMPLATE.format(
                    start=_format_start(header[3]),
                    dur=format_hms(dur_s),
                    n=n,
                )
                item = QListWidgetItem(text)
                item.setData(Qt.UserRole, str(path))
                item.setToolTip(str(path))
                self._list.addItem(item)
        narrative.event("history_page_rescan", note="数据中心历史页刷新会话列表")

    # -- 回看 ---------------------------------------------------------------
    def _on_current_changed(self, current: Optional[QListWidgetItem], _prev=None) -> None:
        if current is None or not current.data(Qt.UserRole):
            return
        path = Path(current.data(Qt.UserRole))
        self._session_path = path
        try:
            header, rows = read_device_log(path)
        except Exception as e:  # noqa: BLE001
            _log.error("load session failed %s: %r", path, e)
            self._title.setText(labels.HISTORY_NO_SELECTED)
            return
        self._render(header, rows)

    def _render(self, header, rows) -> None:
        """按 valid 切有效段重建 I-t 曲线，空态段留空。"""
        _, cid, session_id, start_ms, _ = header
        self._title.setText(labels.HISTORY_DETAIL_TITLE_TEMPLATE.format(
            device=format_cid(cid), start=_format_start(start_ms),
        ))
        dur_s = max(0, int(rows[-1][0] - rows[0][0])) if rows else 0
        self._meta.setText(labels.HISTORY_META_TEMPLATE.format(
            start=_format_start(start_ms), dur=format_hms(dur_s),
            n=len(rows), session=session_id,
        ))

        t0 = rows[0][0] if rows else 0
        # 按 valid==1 切连续有效段
        seg_indices = self._split_valid(rows)
        for i in range(4):
            xs: List[float] = []
            ys: List[float] = []
            for seg in seg_indices:
                seg_x = [(rows[k][0] - t0) for k in seg]
                seg_y = [rows[k][2][i] for k in seg]
                if xs:
                    xs.append(math.nan)  # 段间分隔 → 曲线断开（空态留空）
                    ys.append(math.nan)
                xs.extend(seg_x)
                ys.extend(seg_y)
            self._curves[i].setData(xs, ys, connect="finite")

    @staticmethod
    def _split_valid(rows) -> List[List[int]]:
        """把行下标按 valid 切分为连续有效段（valid==1 的连续游程）。"""
        segments: List[List[int]] = []
        cur: List[int] = []
        for idx, (_, valid, _) in enumerate(rows):
            if valid:
                cur.append(idx)
            elif cur:
                segments.append(cur)
                cur = []
        if cur:
            segments.append(cur)
        return segments