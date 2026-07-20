"""v3.0 单 channel 详情页（双击 3D LED 打开）。

设计要点（v2 优化）：
- 复用全局 HistoryBuffer，取消本地 ring（与电流页/主页共享视图）
- 事件驱动重绘 + 5fps 兜底（避免 60fps 抢 CPU）
- 订阅 CellController.state_changed，不镜像 _state
- 6 个关键日志点（observability hardening 一致性）

布局（高度从上到下）：
┌────────────────────────────────────────┐
│ ← 返回主页  详情 // CH-NN · state      │  header(56)
├────────────────────────────────────────┤
│                                        │
│        I-t 曲线 + 归零红线             │  chart(*)
│                                        │
├────────────────────────────────────────┤
│ 操作  //  ACTIONS                      │
│ [▶ 开始][⏸ 暂停][↻ 继续][■ 停止]      │  actions(64)
└────────────────────────────────────────┘
"""

from __future__ import annotations

from typing import List, Optional

import pyqtgraph as pg
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QCloseEvent
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
)

from app.core import config, labels
from app.core.formatting import format_cid
from app.core.tokens import DEFAULT_TOKENS
from app.data.history_buffer import HistoryBuffer
from app.data.protocol import ChannelReading
from app.observability import get_logger, narrative
from app.services.cell_controller import CellController, DetectionState


_log = get_logger("app.ui.pages.detail_page")


class DetailPage(QWidget):
    """单 channel 详情：I-t 实时曲线 + 操作按钮。"""

    # 用户点"返回主页" → HomePage 收到后 router 切回 home
    requested_back = pyqtSignal()
    # 用户点操作按钮 → HomePage 转发给 CellController
    # action: "start" / "pause" / "resume" / "stop"
    action_requested = pyqtSignal(str, int)  # (action, cid)

    # 30s 周期采样日志
    _SAMPLE_INTERVAL_MS = 30_000
    # 5fps 兜底重绘（事件驱动主路径之外）
    _TICK_INTERVAL_MS = 200
    # 归零异常阈值（电流 < 0.1A 算归零）
    _ZERO_ANOMALY_A = 0.1
    # chart 时间窗（秒）= HISTORY_FRAMES(90) × DATA_REFRESH_MS(2s) = 180s
    _WINDOW_S = 180

    def __init__(
        self,
        history: HistoryBuffer,
        cell_controller: CellController,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._history = history
        self._controller = cell_controller
        self._cid: int = 0  # 0 = 未打开
        self._dirty: bool = False
        self._closing: bool = False  # closeEvent gate（防 RuntimeError）
        self._anomaly_fills: list = []  # 归零异常段填充 item 列表

        self.setObjectName("detailPage")
        self.setMinimumSize(
            DEFAULT_TOKENS.sizing.DETAIL_MIN_W,
            DEFAULT_TOKENS.sizing.DETAIL_MIN_H,
        )

        self._build_ui()
        self._build_chart()
        self._wire_signals()

        _log.info("detail page initialized")
        narrative.event(
            "detail_page_ready",
            note="v3.0 详情页就绪：4 电流曲线 + 操作按钮 + 事件驱动重绘",
        )

    # -- UI 布局 --------------------------------------------------------------
    def _build_ui(self) -> None:
        s = DEFAULT_TOKENS.sizing
        root = QVBoxLayout(self)
        root.setContentsMargins(
            s.DETAIL_MARGIN, s.DETAIL_MARGIN,
            s.DETAIL_MARGIN, s.DETAIL_MARGIN,
        )
        root.setSpacing(s.DETAIL_SPACING)

        # 1) header
        self._header = QFrame()
        self._header.setObjectName("detailHeader")
        self._header.setFixedHeight(s.DETAIL_HEADER_H)
        header_layout = QHBoxLayout(self._header)
        header_layout.setContentsMargins(
            s.DETAIL_HEADER_MARGIN_H, 0,
            s.DETAIL_HEADER_MARGIN_H, 0,
        )
        self._back_btn = QPushButton(labels.DETAIL_BACK_TEXT)
        self._back_btn.setObjectName("detailBackBtn")
        self._back_btn.clicked.connect(self._on_back_clicked)
        header_layout.addWidget(self._back_btn)
        header_layout.addStretch(1)
        self._title_label = QLabel(labels.DETAIL_NO_CHANNEL_TEXT)
        self._title_label.setObjectName("detailTitle")
        header_layout.addWidget(self._title_label)
        root.addWidget(self._header)

        # 2) chart 容器
        self._chart_container = QFrame()
        self._chart_container.setObjectName("detailChart")
        chart_layout = QVBoxLayout(self._chart_container)
        chart_layout.setContentsMargins(0, 0, 0, 0)
        self._plot = pg.PlotWidget()
        self._plot.setObjectName("detailPlot")
        # 背景色：3 元组 (r, g, b) 转 0-1 浮点
        bg = DEFAULT_TOKENS.colors.RACK_3D_BG
        self._plot.setBackground((bg[0] / 255.0, bg[1] / 255.0, bg[2] / 255.0))
        self._plot.showGrid(x=True, y=True, alpha=0.3)
        self._plot.setLabel("left", labels.CHART_CURRENT_Y_LABEL)
        self._plot.setLabel("bottom", labels.CHART_X_LABEL)
        self._plot.setTitle(labels.DETAIL_CHART_TITLE)
        chart_layout.addWidget(self._plot)
        root.addWidget(self._chart_container, 1)

        # 3) actions
        self._actions = QFrame()
        self._actions.setObjectName("detailActions")
        self._actions.setFixedHeight(s.DETAIL_ACTIONS_H)
        actions_layout = QVBoxLayout(self._actions)
        actions_layout.setContentsMargins(
            s.DETAIL_HEADER_MARGIN_H, s.DETAIL_ACTIONS_MARGIN_V,
            s.DETAIL_HEADER_MARGIN_H, s.DETAIL_ACTIONS_MARGIN_V,
        )
        self._actions_title = QLabel(labels.DETAIL_ACTIONS_TITLE)
        self._actions_title.setObjectName("detailActionsTitle")
        actions_layout.addWidget(self._actions_title)
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(s.DETAIL_SPACING)
        self._btn_start = self._make_action_btn(0)
        self._btn_pause = self._make_action_btn(1)
        self._btn_resume = self._make_action_btn(2)
        self._btn_stop = self._make_action_btn(3)
        for btn in (self._btn_start, self._btn_pause, self._btn_resume, self._btn_stop):
            btn_layout.addWidget(btn)
        btn_layout.addStretch(1)
        actions_layout.addLayout(btn_layout)
        root.addWidget(self._actions)

        # 初始状态：未打开
        self._set_actions_enabled(False)

    def _make_action_btn(self, idx: int) -> QPushButton:
        """idx: 0=start / 1=pause / 2=resume / 3=stop"""
        action = ("start", "pause", "resume", "stop")[idx]
        b = QPushButton(labels.DETAIL_ACTION_LABELS[idx])
        b.setObjectName(f"detailBtn{action.capitalize()}")
        b.setProperty("action", action)
        b.clicked.connect(lambda _checked=False, a=action: self._on_action_clicked(a))
        return b

    # -- chart 初始化 ---------------------------------------------------------
    def _build_chart(self) -> None:
        """初始化 chart 组件（4 路曲线 + 归零红线）。"""
        # 4 路电流曲线（4 种 LED_* RGBA 4 元组色，全部不同）
        self._curves: list = []
        line_colors = [
            DEFAULT_TOKENS.colors.LED_RUNNING,   # 绿 - I1
            DEFAULT_TOKENS.colors.LED_PAUSED,    # 青 - I2
            DEFAULT_TOKENS.colors.LED_WARNING,   # 橙 - I3
            DEFAULT_TOKENS.colors.LED_HOVER,     # 白蓝 - I4
        ]
        for i in range(4):
            c = self._plot.plot(
                pen=pg.mkPen(
                    (line_colors[i][0], line_colors[i][1], line_colors[i][2]),
                    width=2,
                ),
                name=labels.CHART_LEGEND_CURRENT_NAMES[i],
            )
            self._curves.append(c)
        # 归零红线（y=0A）：LED_ALERT 是 4 元组 RGBA
        alert = DEFAULT_TOKENS.colors.LED_ALERT
        self._zero_line = pg.InfiniteLine(
            pos=0, angle=0,
            pen=pg.mkPen((alert[0], alert[1], alert[2]), width=1, style=Qt.DashLine),
            label=labels.DETAIL_ZERO_LINE_LABEL,
            labelOpts={"position": 0.95, "color": (alert[0], alert[1], alert[2])},
        )
        self._plot.addItem(self._zero_line)
        # Y 轴范围
        self._plot.setYRange(-0.5, 5.0)

    # -- 信号接线 -------------------------------------------------------------
    def _wire_signals(self) -> None:
        """订阅 HistoryBuffer.appended（事件驱动）+ CellController.state_changed。

        注意：HistoryBuffer 暴露的是 appended 信号（过去式），
        不是同名方法 append()——同名 method 会覆盖 PyQt5 signal 描述符。
        """
        # 事件驱动：appended 信号触发 dirty 标记
        self._history.appended.connect(self._on_history_append)
        # 状态同步：state_changed 更新 title + 启用/禁用异常检测
        self._controller.state_changed.connect(self._on_state_changed)
        # 5fps 兜底 tick
        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(self._TICK_INTERVAL_MS)
        self._tick_timer.timeout.connect(self._tick_chart)
        self._tick_timer.start()
        # 30s 周期采样日志
        self._sample_timer = QTimer(self)
        self._sample_timer.setInterval(self._SAMPLE_INTERVAL_MS)
        self._sample_timer.timeout.connect(self._on_sample)
        self._sample_timer.start()

    # -- 公共 API -------------------------------------------------------------
    def set_channel(self, cid: int) -> None:
        """切换到指定 channel（单开语义：覆盖当前显示）。"""
        if self._closing:
            return
        old = self._cid
        self._cid = cid
        self._dirty = True
        self._set_actions_enabled(True)
        # 清除旧异常段
        self._clear_anomaly_segments()
        # 更新 title
        self._refresh_title()
        _log.info("detail page open: cid=%d (was %s)", cid, old)
        narrative.event(
            "detail_page_open", cid=cid,
            note=f"用户打开 {format_cid(cid)} 详情页",
        )

    def _refresh_title(self) -> None:
        """根据当前 cid + 状态刷新 title 文本。"""
        if self._cid == 0:
            self._title_label.setText(labels.DETAIL_NO_CHANNEL_TEXT)
            return
        state = self._controller.state_of(self._cid)
        state_text = self._state_text(state)
        self._title_label.setText(labels.DETAIL_TITLE_TEMPLATE.format(
            cid=format_cid(self._cid), state=state_text,
        ))

    @staticmethod
    def _state_text(state: DetectionState) -> str:
        """DetectionState → 中文显示文本（统一走 labels.DETECTION_STATE_*）。"""
        return {
            DetectionState.RUNNING: labels.DETECTION_STATE_RUNNING,
            DetectionState.PAUSED: labels.DETECTION_STATE_PAUSED,
            DetectionState.STOPPED: labels.DETECTION_STATE_STOPPED,
        }.get(state, labels.DETECTION_STATE_UNKNOWN)

    # -- 槽函数 ---------------------------------------------------------------
    # 不使用 @safe_call 装饰：functools.wraps 不保留真实签名给 PyQt5 内省，
    # 签名不匹配时会被 safe_call 静默吞 TypeError → UI 无响应（项目记忆已记）。
    # 改为内部 try/except 显式记录，确保错误能被定位。
    def _on_history_append(self, reading: ChannelReading) -> None:
        """HistoryBuffer.appended 信号 → 标记 dirty（事件驱动）。"""
        try:
            if self._closing:
                return
            if reading.channel_id == self._cid:
                self._dirty = True
        except Exception as e:
            _log.error("exception in _on_history_append: %r", e, exc_info=True)

    def _on_state_changed(self, cid: int, old_value: str, new_value: str) -> None:
        """CellController.state_changed → 更新 title + 异常检测开关。"""
        try:
            if self._closing or cid != self._cid:
                return
            self._refresh_title()
            # 归零异常检测仅在 RUNNING 状态启用
            if DetectionState(new_value) != DetectionState.RUNNING:
                self._clear_anomaly_segments()
        except Exception as e:
            _log.error("exception in _on_state_changed: %r", e, exc_info=True)

    def _tick_chart(self) -> None:
        """5fps 兜底 tick：无 dirty 直接返回，否则重绘。"""
        try:
            if self._closing or not self._dirty or self._cid == 0:
                return
            self._render_chart()
            self._dirty = False
        except Exception as e:
            _log.error("exception in _tick_chart: %r", e, exc_info=True)

    def _on_sample(self) -> None:
        """30s 周期采样日志。"""
        try:
            if self._closing or self._cid == 0:
                return
            ts, currents = self._history.snapshot(self._cid)
            n = len(ts)
            # 是否有归零段（I1 通道 < 0.1A 算归零）
            zero_anomaly = False
            if currents and len(currents) > 0 and currents[0]:
                zero_anomaly = any(v < self._ZERO_ANOMALY_A for v in currents[0])
            narrative.event(
                "detail_tick_sample",
                cid=self._cid,
                points=n,
                zero_anomaly=zero_anomaly,
                note="30s 周期采样",
            )
        except Exception as e:
            _log.error("exception in _on_sample: %r", e, exc_info=True)

    def _on_back_clicked(self) -> None:
        try:
            if self._closing:
                return
            narrative.event(
                "detail_page_close",
                cid=self._cid,
                reason="back_button",
                note="用户点击返回主页",
            )
            self.requested_back.emit()
        except Exception as e:
            _log.error("exception in _on_back_clicked: %r", e, exc_info=True)

    def _on_action_clicked(self, action: str) -> None:
        try:
            if self._closing or self._cid == 0:
                return
            narrative.event(
                "detail_action",
                actor="user",
                action=action,
                cid=self._cid,
                note=f"用户在 {format_cid(self._cid)} 详情页点击 {action}",
            )
            self.action_requested.emit(action, self._cid)
        except Exception as e:
            _log.error("exception in _on_action_clicked: %r", e, exc_info=True)

    # -- 渲染 -----------------------------------------------------------------
    def _render_chart(self) -> None:
        """从 HistoryBuffer 读数据 → setData + 异常段检测。"""
        ts, currents = self._history.snapshot(self._cid)
        if not ts:
            return
        # 1) 4 路电流曲线
        for i, curve in enumerate(self._curves):
            if i < len(currents):
                curve.setData(ts, currents[i])
        # 2) 归零异常段检测
        self._detect_zero_anomaly(ts, currents)

    def _detect_zero_anomaly(self, ts: list, currents: list) -> None:
        """检测 current < 阈值且 RUNNING 状态的段，标红。"""
        state = self._controller.state_of(self._cid)
        if state != DetectionState.RUNNING:
            self._clear_anomaly_segments()
            return
        if not currents or len(currents) < 1:
            return
        i1 = currents[0]
        if not i1:
            return
        # 找归零段
        anomaly_ranges: list = []
        in_anomaly = False
        start_idx = 0
        for idx, val in enumerate(i1):
            if val < self._ZERO_ANOMALY_A:
                if not in_anomaly:
                    in_anomaly = True
                    start_idx = idx
            else:
                if in_anomaly:
                    anomaly_ranges.append((start_idx, idx - 1))
                    in_anomaly = False
        if in_anomaly:
            anomaly_ranges.append((start_idx, len(i1) - 1))
        # 清除旧填充线
        self._clear_anomaly_segments()
        if not anomaly_ranges:
            return
        # 画新的红色填充：先构造后 add，逐项 try 防止 addItem 异常时
        # 旧 fills 已清但新 item 未入 _anomaly_fills 造成 widget 持有"孤儿"item
        alert = DEFAULT_TOKENS.colors.LED_ALERT
        for start, end in anomaly_ranges:
            if end - start < 1:
                continue
            x_seg = ts[start:end + 1]
            y_seg = i1[start:end + 1]
            y_upper = [max(v, 0.01) for v in y_seg]
            fill = pg.FillBetweenItem(
                pg.PlotDataItem(x_seg, y_upper),
                pg.PlotDataItem(x_seg, [0.0] * len(y_seg)),
                brush=pg.mkBrush(alert[0], alert[1], alert[2], 60),  # 60=alpha
            )
            try:
                self._plot.addItem(fill)
            except Exception as e:
                _log.error("addItem anomaly fill failed: %r", e, exc_info=True)
                continue
            self._anomaly_fills.append(fill)
        if anomaly_ranges:
            narrative.event(
                "detail_zero_anomaly",
                cid=self._cid,
                count=len(anomaly_ranges),
                note=f"检测到 {len(anomaly_ranges)} 段电流归零异常",
            )

    def _clear_anomaly_segments(self) -> None:
        """清除已画的异常填充线。"""
        for f in self._anomaly_fills:
            self._plot.removeItem(f)
        self._anomaly_fills = []

    def _set_actions_enabled(self, enabled: bool) -> None:
        for btn in (self._btn_start, self._btn_pause, self._btn_resume, self._btn_stop):
            btn.setEnabled(enabled and self._cid != 0)

    # -- closeEvent -----------------------------------------------------------
    def closeEvent(self, event: QCloseEvent) -> None:
        """关闭时防 RuntimeError。"""
        self._closing = True
        if hasattr(self, "_tick_timer"):
            self._tick_timer.stop()
        if hasattr(self, "_sample_timer"):
            self._sample_timer.stop()
        self._clear_anomaly_segments()
        super().closeEvent(event)
