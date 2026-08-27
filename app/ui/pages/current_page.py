"""v3.0 电流检测页（Phase A.8：选区 + 批量工具条 + 选区计数）。

布局（Phase A.8）：
┌──────────────────────────────────────────────────────────────────────┐
│  ⚡ 电流检测 │ ▶启动 │ ⏸暂停 │ ■停止 │ ✕清空 │ 已选 4 │ 72 CHANNELS │  工具条
├──────────────────────────────────────────────────────────────────────┤
│  [CH-01  ⚪ON  1.2 3.4 2.1 4.0]  ← 单击/Shift+点击/Ctrl+点击         │
│  [CH-02  ⚪ON  1.0 3.2 2.4 4.2]                                       │
│  [CH-03  ⚪ON  ...        ]                                            │
│  ... 9 列 × 8 行 = 72 cell，一次显示无滚动 ...                          │
└──────────────────────────────────────────────────────────────────────┘

Phase A.8 交互：
- 单击 cell：单选（清空旧选区）
- Shift+点击：连续多选（从 anchor 到当前 cid）
- Ctrl+点击：切换（加入/移出选区）
- Esc：清空选区
- ▶ 启动 / ⏸ 暂停 / ■ 停止：作用在选区
- ✕ 清空：清空选区
- 已选 N：实时显示选区数量
"""

from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QKeyEvent
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton, QSizePolicy,
)

from app.core import config, labels
from app.core.tokens import DEFAULT_TOKENS
from app.data.demo_source import DemoDataSource
from app.data.history_buffer import HistoryBuffer
from app.observability import get_logger, narrative
from app.services.auto_detector import AutoAgingDetector
from app.services.cell_controller import CellController, DetectionState
from app.services.cell_ui_manager import CellUIManager
from app.services.countdown import CountdownService
from app.services.aging_settings import get_aging_settings
from app.widgets.cell_grid import CellGrid


_log = get_logger("app.ui.pages.current_page")

# 取一次 sizing 引用
_S = DEFAULT_TOKENS.sizing


class CurrentToolbar(QFrame):
    """电流页工具条：标题 + 批量按钮 + 选区计数 + 元信息。"""

    # action: "start" / "pause" / "stop" / "clear"
    action_requested = pyqtSignal(str)

    def __init__(self, total: int, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("currentToolbar")
        self.setFixedHeight(_S.TOOLBAR_H)
        self._build_ui(total)

    def _build_ui(self, total: int) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(
            _S.DETAIL_HEADER_MARGIN_H, 0,
            _S.DETAIL_HEADER_MARGIN_H, 0,
        )
        layout.setSpacing(_S.TOOLBAR_SPACING)

        # 左：标题
        title = QLabel(labels.TOOLBAR_TITLE)
        title.setObjectName("currentTitle")
        layout.addWidget(title)

        layout.addSpacing(_S.TOOLBAR_GAP)

        # 中：批量按钮
        self._btn_start = self._make_btn(labels.TOOLBAR_BTN_START_LABEL, "btnBatch")
        self._btn_pause = self._make_btn(labels.TOOLBAR_BTN_PAUSE_LABEL, "btnBatch")
        self._btn_stop = self._make_btn(labels.TOOLBAR_BTN_STOP_LABEL, "btnBatch")
        self._btn_clear = self._make_btn(labels.TOOLBAR_BTN_CLEAR_LABEL, "btnBatch")
        self._btn_start.clicked.connect(lambda: self.action_requested.emit("start"))
        self._btn_pause.clicked.connect(lambda: self.action_requested.emit("pause"))
        self._btn_stop.clicked.connect(lambda: self.action_requested.emit("stop"))
        self._btn_clear.clicked.connect(lambda: self.action_requested.emit("clear"))
        layout.addWidget(self._btn_start)
        layout.addWidget(self._btn_pause)
        layout.addWidget(self._btn_stop)
        layout.addWidget(self._btn_clear)

        layout.addStretch(1)

        # 右：选区计数
        self._selection_label = QLabel(labels.TOOLBAR_SELECTION_TEMPLATE.format(n=0))
        self._selection_label.setObjectName("selectionCount")
        layout.addWidget(self._selection_label)

        layout.addSpacing(_S.TOOLBAR_GAP)

        # 最右：元信息
        info = QLabel(
            f"{total} CHANNELS  ·  I1-I4  ·  REFRESH {config.DATA_REFRESH_MS}ms"
        )
        info.setObjectName("currentInfo")
        layout.addWidget(info)

    def _make_btn(self, text: str, name: str) -> QPushButton:
        b = QPushButton(text)
        b.setObjectName(name)
        b.setCursor(Qt.PointingHandCursor)
        b.setMinimumHeight(_S.TOOLBAR_BTN_MIN_H)
        return b

    def update_selection(self, n: int) -> None:
        self._selection_label.setText(labels.TOOLBAR_SELECTION_TEMPLATE.format(n=n))
        # 选区为空时禁用 start/pause/stop
        has = n > 0
        self._btn_start.setEnabled(has)
        self._btn_pause.setEnabled(has)
        self._btn_stop.setEnabled(has)
        # clear 总是可用
        self._btn_clear.setEnabled(True)


class CurrentDetectionPage(QWidget):
    """电流检测页（Phase A.8：选区 + 批量工具条）。"""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("currentPage")
        self.setFocusPolicy(Qt.StrongFocus)  # 让 Esc 键能触发
        # CellController
        self._controller = CellController(
            total=config.GRID_ROWS * config.GRID_COLS, parent=self,
        )
        # HistoryBuffer
        self._buffer = HistoryBuffer(
            channel_count=config.GRID_ROWS * config.GRID_COLS, parent=self,
        )
        # DemoDataSource
        self._source = DemoDataSource(
            total=config.GRID_ROWS * config.GRID_COLS,
            interval_ms=config.DATA_REFRESH_MS, parent=self,
        )
        # CellUIManager
        self._ui_mgr = CellUIManager()
        # 异常状态缓存
        self._last_visual: dict[int, str] = {}
        # 老化自动检测 + 每 cell 倒计时
        self._detector = AutoAgingDetector(parent=self)
        self._detector.triggered.connect(self._on_auto_triggered)
        self._countdown = CountdownService(parent=self)
        # 接线
        self._source.batch_reading.connect(self._on_batch_reading)
        self._controller.state_changed.connect(self._on_state_changed)
        self._build_ui()
        # demo 启动
        self._demo_start_initial_cells()
        self._source.start()
        narrative.event(
            "current_page_init",
            note="v3.0 电流检测页 Phase A.8：选区 + 批量工具条 + 4 cell demo + 老化自动检测",
        )

    # -- Phase 3：对外暴露的服务引用（HomePage 用于构造 DetailPage）---------
    @property
    def cell_controller(self) -> CellController:
        return self._controller

    @property
    def history_buffer(self) -> HistoryBuffer:
        return self._buffer

    @property
    def data_source(self) -> "DemoDataSource":
        return self._source

    @property
    def countdown_service(self) -> CountdownService:
        """会话内每 cell 倒计时服务（HomePage 等可复用）。"""
        return self._countdown

    @property
    def auto_detector(self) -> AutoAgingDetector:
        """老化自动检测器（供外部查询/复位）。"""
        return self._detector

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        total = config.GRID_ROWS * config.GRID_COLS
        # 工具条
        self._toolbar = CurrentToolbar(total=total, parent=self)
        self._toolbar.action_requested.connect(self._on_toolbar_action)
        outer.addWidget(self._toolbar)
        # CellGrid
        self._grid = CellGrid(total=total, parent=self)
        self._grid.selection_changed.connect(self._on_selection_changed)
        self._grid.cell_double_clicked.connect(self._on_cell_double_clicked)
        outer.addWidget(self._grid, 1)

    # -- demo ----------------------------------------------------------------
    def _demo_start_initial_cells(self) -> None:
        initial = [1, 2, 3, 4]
        self._start_detection(initial)
        _log.info("demo: initial cells %s set to RUNNING", initial)

    def get_all_visual_states(self) -> "dict[int, str]":
        return dict(self._last_visual)

    # -- 槽函数 --------------------------------------------------------------
    def _on_batch_reading(self, readings) -> None:
        """Phase 1.28：异常检测双重保险。
        只有同时满足「controller 状态为 running/paused」AND「demo 标记为 running」
        的 cell 才进行异常判断；其他 cell 强制视觉为 offline（不显示任何颜色变化）。
        """
        threshold = config.ANOMALY_CURRENT_THRESHOLD
        running_cids = self._source.get_running_cids()  # 双重保险
        for r in readings:
            self._buffer.append(r)
            cid = r.channel_id
            # 老化自动检测：电流 0→稳定浮动 判定，触发由 _on_auto_triggered 处理
            self._detector.feed(cid, r.currents)
            det_state = self._controller.state_of(cid).value
            if (det_state in ("running", "paused")
                    and cid in running_cids):
                is_anomaly = any(c > threshold for c in r.currents)
                visual = "anomaly" if is_anomaly else "online"
            else:
                visual = "offline"
            if self._last_visual.get(cid) != visual:
                prev = self._last_visual.get(cid)
                self._last_visual[cid] = visual
                # 异常状态切换打 warning（仅当涉及 anomaly 时），方便排查"LED 变红"
                if visual == "anomaly" or prev == "anomaly":
                    _log.warning(
                        "cell_visual_state_change: cid=CH-%02d %s -> %s "
                        "det_state=%s in_demo_running=%s currents=%s threshold=%s",
                        cid, prev, visual, det_state,
                        cid in running_cids, r.currents, threshold,
                    )
                self.cell_visual_state.emit(cid, visual)
        self._grid.update_batch(readings)

    def _on_state_changed(self, cid: int, old_state: str, new_state: str) -> None:
        cell = self._grid.cell(cid)
        if cell is not None:
            self._ui_mgr.apply_state(cell, new_state)
        det_state = self._controller.state_of(cid).value
        if det_state in ("running", "paused"):
            visual = "online"
        else:
            visual = "offline"
        if self._last_visual.get(cid) != visual:
            self._last_visual[cid] = visual
            self.cell_visual_state.emit(cid, visual)

    # -- 老化自动检测（电流 0→稳定浮动 → 自动开始倒计时）-------------------
    def _start_detection(self, cids) -> None:
        """把 cids 置为检测中并启动每 cell 老化倒计时（会话老化时长）。"""
        transitioned = self._controller.apply("start", cids)
        if not transitioned:
            return
        aging_seconds = get_aging_settings().aging_seconds
        for cid in transitioned:
            self._countdown.start(cid, aging_seconds)
        self._sync_source_running()
        return transitioned

    def _stop_detection(self, cids) -> None:
        """把 cids 置为停止并取消倒计时、复位自动检测（允许下次再触发）。"""
        transitioned = self._controller.apply("stop", cids)
        for cid in transitioned:
            self._countdown.cancel(cid)
            self._detector.reset(cid)
        if transitioned:
            self._sync_source_running()
        return transitioned

    def _sync_source_running(self) -> None:
        """按 controller 实际状态同步 demo running cells（供异常/空载判定）。"""
        new_running = {
            cid for cid in range(1, config.GRID_ROWS * config.GRID_COLS + 1)
            if self._controller.state_of(cid).value in ("running", "paused")
        }
        self._source.set_running(sorted(new_running))

    def _on_auto_triggered(self, cid: int) -> None:
        """检测到稳定电流：若该 CH 仍为停止态，则自动开始检测 + 倒计时。"""
        if self._controller.state_of(cid).value != DetectionState.STOPPED.value:
            _log.debug(
                "auto_aging skip: cid=CH-%02d already not stopped",
                cid,
            )
            return
        self._start_detection([cid])
        _log.info("auto_aging triggered: CH-%02d 开始老化并启动倒计时", cid)
        narrative.event(
            "auto_aging_triggered",
            channels=[cid],
            note=f"CH-{cid:02d} 检测到稳定电流，自动开始老化并启动倒计时",
        )

    # -- A.8 选区 + 批量 ----------------------------------------------------
    def _on_selection_changed(self, cids: set) -> None:
        self._toolbar.update_selection(len(cids))
        if cids:
            _log.debug("selection changed: %d cells", len(cids))

    def _on_toolbar_action(self, action: str) -> None:
        cids = list(self._grid.selection())
        if action == "clear":
            self._grid.clear_selection()
            return
        if not cids:
            return
        if action == "start":
            transitioned = self._start_detection(cids)
        elif action == "stop":
            transitioned = self._stop_detection(cids)
        else:  # pause / resume：仅切状态，倒计时不因暂停/恢复被取消
            transitioned = self._controller.apply(action, cids)
            if transitioned:
                self._sync_source_running()
        _log.info(
            "toolbar action=%s requested=%d transitioned=%d",
            action, len(cids), len(transitioned),
        )

    # -- Esc 清空选区 --------------------------------------------------------
    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key_Escape:
            self._grid.clear_selection()
            return
        super().keyPressEvent(event)

    # -- 异常告警信号（3D LED 联动） -----------------------------------------
    cell_visual_state = pyqtSignal(int, str)
    # 双击 cell 网格 → 请求打开详情页（emit cid）
    cell_detail_requested = pyqtSignal(int)

    def _on_cell_double_clicked(self, cid: int) -> None:
        """双击电流页 CH 卡片 → 通知 HomePage 打开对应详情页。"""
        narrative.event(
            "current_cell_direct_open",
            cid=cid,
            note=f"用户双击电流页 CH-{cid:02d}，打开详情页",
        )
        self.cell_detail_requested.emit(cid)
