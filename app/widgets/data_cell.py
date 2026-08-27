"""数据单元 widget。

布局：
    ┌─────────────────────────────────┐  ← 单元外框
    │ CH-NN              ● ON         │  ← 头部：底部分隔线
    │ ─────────────────────────────── │
    │ ┌────┐ ┌────┐ ┌────┐ ┌────┐    │  ← 1 行 4 列 = 4 电流（I1-I4）
    │ │ I1 │ │ I2 │ │ I3 │ │ I4 │    │
    │ │4.40│ │4.40│ │4.40│ │4.40│    │
    │ └────┘ └────┘ └────┘ └────┘    │
    └─────────────────────────────────┘

数据来源：通过 `update_data(ChannelReading)` 接收；不直接生成数据。
"""

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QWidget, QLabel, QGridLayout, QVBoxLayout, QHBoxLayout, QSizePolicy,
)

from app.core import config, labels
from app.core.tokens import DEFAULT_TOKENS
from app.core.formatting import format_cid
from app.data.protocol import ChannelReading
from app.observability import safe_call
from app.ui.qss_utils import refresh_qss


class DataPoint(QWidget):
    """单个数据点方格：label + value + unit。"""

    def __init__(self, label: str, unit: str, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setObjectName("dataPoint")
        self.setProperty("alert", False)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        sizing = DEFAULT_TOKENS.sizing
        # Phase A: 缩到小尺寸，让 72 cell 一次显示无滚动
        self.setMinimumSize(
            sizing.DATA_POINT_MIN_W_NEW, sizing.DATA_POINT_MIN_H_NEW,
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            sizing.DATA_POINT_MARGIN_H, sizing.DATA_POINT_MARGIN_V,
            sizing.DATA_POINT_MARGIN_H, sizing.DATA_POINT_MARGIN_V,
        )
        layout.setSpacing(0)

        top = QHBoxLayout()
        top.setSpacing(sizing.DATA_POINT_TOP_SPACING)
        top.setContentsMargins(0, 0, 0, 0)
        self._label = QLabel(label)
        self._label.setObjectName("dataPointLabel")
        self._label.setAlignment(Qt.AlignCenter)
        self._unit = QLabel(unit)
        self._unit.setObjectName("dataPointUnit")
        self._unit.setAlignment(Qt.AlignCenter)
        top.addStretch(1)
        top.addWidget(self._label)
        top.addWidget(self._unit)
        top.addStretch(1)
        layout.addLayout(top)

        self._value = QLabel("--")
        self._value.setObjectName("dataPointValue")
        self._value.setAlignment(Qt.AlignCenter)
        f = QFont(DEFAULT_TOKENS.fonts.FAMILY_DATA)
        f.setPointSize(DEFAULT_TOKENS.font_sizes.DATA_POINT_VALUE)
        f.setBold(True)
        self._value.setFont(f)
        layout.addWidget(self._value, 1)

    def set_value(self, value, alert: bool = False) -> None:
        # 接受 float 或 str（str 用于 NO_DATA 等占位"---"）
        if isinstance(value, str):
            self._value.setText(value)
        else:
            self._value.setText(f"{value:0.2f}")
        if bool(self.property("alert")) != alert:
            self.setProperty("alert", alert)
            self._value.setProperty("alert", alert)
            refresh_qss(self)
            refresh_qss(self._value)


class DataGrid(QWidget):
    """1 行 4 列 = 4 个电流数据点（I1-I4）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setObjectName("dataGrid")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        layout = QVBoxLayout(self)
        sizing = DEFAULT_TOKENS.sizing
        layout.setContentsMargins(
            sizing.DATA_GRID_MARGIN, sizing.DATA_GRID_MARGIN,
            sizing.DATA_GRID_MARGIN, sizing.DATA_GRID_MARGIN,
        )
        layout.setSpacing(sizing.DATA_GRID_SPACING)

        self._current_points = []

        row = QGridLayout()
        row.setSpacing(DEFAULT_TOKENS.sizing.DATA_GRID_SPACING)
        row.setContentsMargins(0, 0, 0, 0)
        for i, lbl in enumerate(config.CURRENT_LABELS):
            p = DataPoint(lbl, "A")
            self._current_points.append(p)
            row.addWidget(p, 0, i)
        for c in range(config.DATA_POINTS_PER_ROW):
            row.setColumnStretch(c, 1)
        layout.addLayout(row, 1)

    def current_points(self):
        return self._current_points


class HeaderBar(QWidget):
    """头部信息行：CH-NN + 状态；带底部分隔线。"""

    def __init__(self, cell_id: int, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setObjectName("headerBar")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(DEFAULT_TOKENS.sizing.HEADER_BAR_H)

        layout = QHBoxLayout(self)
        sizing = DEFAULT_TOKENS.sizing
        layout.setContentsMargins(
            sizing.HEADER_BAR_MARGIN_LR, 0,
            sizing.HEADER_BAR_MARGIN_LR, sizing.HEADER_BAR_MARGIN_B,
        )
        layout.setSpacing(sizing.HEADER_BAR_MARGIN_LR)

        self._id_label = QLabel(format_cid(cell_id))
        self._id_label.setObjectName("cellId")

        self._status_label = QLabel(labels.STATUS_ONLINE_TEXT)
        self._status_label.setObjectName("cellStatus")
        self._status_label.setStyleSheet(f"color: {config.COLOR_TEXT_OK};")

        layout.addWidget(self._id_label)
        layout.addStretch(1)
        layout.addWidget(self._status_label)

    def set_status_text(self, text: str, color: str) -> None:
        self._status_label.setText(text)
        self._status_label.setStyleSheet(f"color: {color};")


class DataCell(QWidget):
    """单个数据通道：头部 + 2x4 数据网格。

    数据由外部 DataSource 通过 update_data(ChannelReading) 注入。
    状态由 DataSource 通过 update_status(StatusUpdate) 单独推送。
    """

    STATUS_OFFLINE = "offline"
    STATUS_ONLINE = "online"
    STATUS_PAUSED = "paused"
    STATUS_ANOMALY = "anomaly"
    STATUS_NO_DATA = "no_data"

    def __init__(self, cell_id: int, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.cell_id = cell_id
        self.setObjectName("dataCell")
        self.setProperty("status", self.STATUS_ONLINE)
        self.setProperty("hovered", False)
        # expired_pending 闪烁状态："off" / "on" / 缺省
        self.setProperty("expired_pending", "off")
        self._expired_pending = False
        self._blink_timer = QTimer(self)
        self._blink_timer.setInterval(500)
        self._blink_timer.timeout.connect(self._toggle_blink)
        # 老化完成闪烁（高亮蓝灯）：独立于归零闪烁；默认 "none" = 无 QSS 样式
        self.setProperty("aging_done", "none")
        self._aging_done = False
        self._aging_blink_timer = QTimer(self)
        self._aging_blink_timer.setInterval(500)
        self._aging_blink_timer.timeout.connect(self._toggle_aging_blink)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        sizing = DEFAULT_TOKENS.sizing
        # Phase A: 缩到小尺寸，让 72 cell 一次显示无滚动
        self.setMinimumSize(
            sizing.DATA_CELL_MIN_W, sizing.DATA_CELL_MIN_H,
        )

        self._build_ui()
        self._init_display()

    # -- UI 构建 -------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        sizing = DEFAULT_TOKENS.sizing
        outer.setContentsMargins(
            sizing.CELL_OUTER_MARGIN_H, sizing.CELL_OUTER_MARGIN_V,
            sizing.CELL_OUTER_MARGIN_H, sizing.CELL_OUTER_MARGIN_V,
        )
        outer.setSpacing(sizing.CELL_OUTER_SPACING)

        self._header = HeaderBar(self.cell_id)
        outer.addWidget(self._header)

        self._grid = DataGrid()
        outer.addWidget(self._grid, 1)
        # 让所有子控件对鼠标透明：否则点击 HeaderBar/DataPoint/QLabel 时，
        # 父级 childAt() 命中的是子控件而非本 DataCell，会导致单击选中 /
        # 双击打开"时灵时不灵"。统一透明后，鼠标事件稳定由 DataCell 本体接收。
        for child in self.findChildren(QWidget):
            child.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    def _init_display(self) -> None:
        """初始空白态：所有点显示 '---'、状态 no_data。"""
        self._show_no_data_placeholders()
        self.set_status(self.STATUS_NO_DATA)

    def _show_no_data_placeholders(self) -> None:
        for p in self._grid.current_points():
            p.set_value(config.NO_DATA_PLACEHOLDER)

    # -- 数据注入 ------------------------------------------------------------
    def update_data(self, reading: ChannelReading) -> None:
        if reading.channel_id != self.cell_id:
            return  # 防御：MainWindow 派发应已过滤

        # NO_DATA 状态时仍刷新数字占位（被 set_status 覆盖）
        if self.property("status") == self.STATUS_NO_DATA:
            self._show_no_data_placeholders()
        else:
            for i, p in enumerate(self._grid.current_points()):
                v = reading.currents[i]
                p.set_value(v, alert=(v > config.ANOMALY_CURRENT_THRESHOLD))

    def update_status(self, status_value) -> None:
        """接受 ChannelStatus enum 或字符串。"""
        s = status_value.value if hasattr(status_value, "value") else status_value
        if s == self.STATUS_ONLINE:
            self.set_status(self.STATUS_ONLINE)
        elif s == self.STATUS_PAUSED:
            self.set_status(self.STATUS_PAUSED)
        elif s == self.STATUS_ANOMALY:
            self.set_status(self.STATUS_ANOMALY)
        elif s == self.STATUS_NO_DATA:
            self._show_no_data_placeholders()
            self.set_status(self.STATUS_NO_DATA)
        else:
            self.set_status(self.STATUS_OFFLINE)

    # -- 状态 ----------------------------------------------------------------
    @safe_call(context="data_cell.set_status")
    def set_status(self, status: str) -> None:
        if self.property("status") != status:
            self.setProperty("status", status)
            refresh_qss(self)
        c = DEFAULT_TOKENS.colors
        if status == self.STATUS_ONLINE:
            self._header.set_status_text(
                labels.STATUS_ONLINE_TEXT, c.TEXT_NEON_GREEN
            )
        elif status == self.STATUS_PAUSED:
            self._header.set_status_text(
                labels.STATUS_PAUSED_TEXT, c.TEXT_NEON_CYAN
            )
        elif status == self.STATUS_ANOMALY:
            self._header.set_status_text(
                labels.STATUS_ALERT_TEXT, c.TEXT_DANGER
            )
        elif status == self.STATUS_NO_DATA:
            self._header.set_status_text(
                labels.STATUS_NO_DATA_TEXT, c.TEXT_NO_DATA
            )
        else:
            self._header.set_status_text(
                labels.STATUS_OFFLINE_TEXT, c.TEXT_DIM
            )

    # -- 交互 ----------------------------------------------------------------
    def enterEvent(self, event):
        self.setProperty("hovered", True)
        refresh_qss(self)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setProperty("hovered", False)
        refresh_qss(self)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        # DataCell 是被动显示组件：只 emit 点击事件和 modifier，
        # 不在这里改选区。选区逻辑由 MainWindow 集中处理。
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.cell_id, int(event.modifiers()))
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.double_clicked.emit(self.cell_id)
        super().mouseDoubleClickEvent(event)

    # -- 选中 ----------------------------------------------------------------
    @safe_call(context="data_cell.set_selected")
    def set_selected(self, selected: bool) -> None:
        if bool(self.property("selected")) != selected:
            # 显式传字符串"true"/"false"给 QSS 匹配 `[selected="true"]` 选择器
            self.setProperty("selected", "true" if selected else "false")
            refresh_qss(self)
            self.selected_changed.emit(self.cell_id, selected)

    # -- 倒计时归零闪烁 -------------------------------------------------------
    @safe_call(context="data_cell.set_expired_pending")
    def set_expired_pending(self, pending: bool) -> None:
        """设置/清除"倒计时归零·等待操作人手动停止"闪烁高亮。

        - True  : 启动 500ms 闪烁 timer，边框在 on/off 间切换
        - False : 停止 timer，恢复 "off" 静态
        """
        if self._expired_pending == pending:
            return
        self._expired_pending = pending
        if pending:
            self.setProperty("expired_pending", "on")
            self._blink_timer.start()
        else:
            self._blink_timer.stop()
            self.setProperty("expired_pending", "off")
        refresh_qss(self)

    @safe_call(context="data_cell._toggle_blink")
    def _toggle_blink(self) -> None:
        if not self._expired_pending:
            return
        current = self.property("expired_pending")
        new = "off" if current == "on" else "on"
        self.setProperty("expired_pending", new)
        refresh_qss(self)

    @safe_call(context="data_cell.set_aging_done")
    def set_aging_done(self, done: bool) -> None:
        """设置/清除"老化倒计时结束"高亮蓝灯闪烁。

        - True  : 启动 500ms 闪烁 timer，边框在蓝亮/暗蓝间切换
        - False : 停止 timer，恢复"none"（无 QSS 样式，不影响正常状态边框）
        """
        if self._aging_done == done:
            return
        self._aging_done = done
        if done:
            self.setProperty("aging_done", "on")
            self._aging_blink_timer.start()
        else:
            self._aging_blink_timer.stop()
            self.setProperty("aging_done", "none")
        refresh_qss(self)

    @safe_call(context="data_cell._toggle_aging_blink")
    def _toggle_aging_blink(self) -> None:
        if not self._aging_done:
            return
        current = self.property("aging_done")
        new = "off" if current == "on" else "on"
        self.setProperty("aging_done", new)
        refresh_qss(self)

    selected_changed = pyqtSignal(int, bool)
    double_clicked = pyqtSignal(int)
    clicked = pyqtSignal(int, int)
