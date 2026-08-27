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
from app.ui.vision_worker import get_vision_worker
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
        # 暂停/继续共享一个按钮：当前应执行的 action（随选区状态动态切换）
        self._pause_action = "pause"
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
        self._btn_pause.clicked.connect(self._emit_pause_action)
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

    def _emit_pause_action(self) -> None:
        # 选区含"已暂停"时按钮变成"继续"，此时 emit resume；否则 emit pause
        self.action_requested.emit(self._pause_action)

    def refresh_actions(self, n: int, actions: dict) -> None:
        """按选区内 cell 实际状态细化启用/禁用与"暂停/继续"动态切换。

        actions: {"start","pause","resume","stop"} → 各自可操作的 cell 数。
        - start  仅在存在"停止"cell 时可用
        - 暂停/继续 共享一个按钮：选区含"已暂停"→"↻ 继续"(resume)，
          否则含"运行中"→"⏸ 暂停"(pause)，两者皆无则禁用
        - stop   仅在存在"运行中/已暂停"cell 时可用
        - clear  始终可用
        """
        has = n > 0
        # 启动：有处于 stopped 的 cell 才可点
        self._btn_start.setEnabled(has and actions["start"] > 0)
        # 暂停/继续：动态文本 + 切换目标 action
        if actions["resume"] > 0:
            self._btn_pause.setText(labels.TOOLBAR_BTN_RESUME_LABEL)
            self._pause_action = "resume"
        else:
            self._btn_pause.setText(labels.TOOLBAR_BTN_PAUSE_LABEL)
            self._pause_action = "pause"
        self._btn_pause.setEnabled(
            has and (actions["pause"] > 0 or actions["resume"] > 0)
        )
        # 停止：有非停止 cell 才可点
        self._btn_stop.setEnabled(has and actions["stop"] > 0)
        # 清空总是可用
        self._btn_clear.setEnabled(True)
        self._selection_label.setText(
            labels.TOOLBAR_SELECTION_TEMPLATE.format(n=n)
        )


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
        # 初始刷新：无选区 → 按钮默认禁用
        self._refresh_toolbar()

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
        # 选区内的 cell 状态变化 → 同步刷新按钮启用/暂停-继续
        if self._grid.selection():
            self._refresh_toolbar()

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
        # 视频检测由 `_sync_vision_follow`（在 _sync_source_running 内）按电流
        # 运行集合统一跟随监控，无需在此单独拉起。
        return transitioned

    def _stop_detection(self, cids) -> None:
        """把 cids 置为停止并取消倒计时、复位自动检测（允许下次再触发）。"""
        transitioned = self._controller.apply("stop", cids)
        for cid in transitioned:
            self._countdown.cancel(cid)
            self._detector.reset(cid)
        if transitioned:
            self._sync_source_running()
            # 停止同样由 _sync_vision_follow 按电流运行集合在监控中移除该通道。
        return transitioned

    def _sync_source_running(self) -> None:
        """按 controller 实际状态同步 demo running cells（供异常/空载判定）。

        同时把「电流运行/暂停」通道全集登记到通道视频注册表，作为检测页判断
        「切走/关闭时是否保留该通道后台视频检测」的依据（保留则后台持续累计）。
        """
        new_running = {
            cid for cid in range(1, config.GRID_ROWS * config.GRID_COLS + 1)
            if self._controller.state_of(cid).value in ("running", "paused")
        }
        self._source.set_running(sorted(new_running))
        from app.services.channel_video_registry import get_channel_video_registry
        get_channel_video_registry().set_current_running(list(new_running))
        # 电流运行集合作为「视频检测的唯一事实源」，动态跟随到静默监控 monitor
        self._sync_vision_follow()

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
    def _refresh_toolbar(self) -> None:
        """依据选区内各 cell 状态，刷新工具条按钮启用与暂停/继续切换。"""
        cids = list(self._grid.selection())
        actions = {
            "start":  self._controller.count_actionable("start", cids),
            "pause":  self._controller.count_actionable("pause", cids),
            "resume": self._controller.count_actionable("resume", cids),
            "stop":   self._controller.count_actionable("stop", cids),
        }
        self._toolbar.refresh_actions(len(cids), actions)

    def _on_selection_changed(self, cids: set) -> None:
        self._refresh_toolbar()
        if cids:
            _log.debug("selection changed: %d cells", len(cids))

    def _apply_action_to_cids(self, action: str, cids) -> list:
        """统一动作执行：状态机 + 运行源 + 老化倒计时的联动（主页/详情页共用入口）。

        - start： 启动老化倒计时（_start_detection）
        - stop：  取消老化倒计时、复位自动检测（_stop_detection）
        - pause： 切 paused 状态 + 冻结对应 cell 的倒计时
        - resume：切 running 状态 + 恢复对应 cell 的倒计时
        """
        if action == "start":
            return self._start_detection(cids)
        if action == "stop":
            return self._stop_detection(cids)
        if action == "pause":
            transitioned = self._controller.apply(action, cids)
            if transitioned:
                self._sync_source_running()
                for cid in transitioned:
                    self._countdown.pause(cid)
            # 视频联动不依赖电流状态机：只要用户对某 CH 暂停，其视频流检测即同步
            # 暂停（worker 对无对应 job 忽略，幂等安全）
            self._sync_vision_pause("pause", list(cids))
            return transitioned
        if action == "resume":
            transitioned = self._controller.apply(action, cids)
            if transitioned:
                self._sync_source_running()
                for cid in transitioned:
                    self._countdown.resume(cid)
            self._sync_vision_pause("resume", list(cids))
            return transitioned
        return []

    def _sync_vision_pause(self, action: str, cids: list) -> None:
        """把电流页的暂停/恢复同步到对应的视频流检测（单向：电流→视频）。

        对每个成功转移的 cid，向全局视觉 worker 下发同 job 的 pause/resume，
        使该通道若正在做视频流检测时也同步暂停/恢复。worker 对不存在/未打开的
        job 自动忽略，故无视频检测时调用是安全的（幂等）。
        """
        cmd = "pause" if action == "pause" else "resume"
        from app.services.channel_video_registry import get_channel_video_registry
        reg = get_channel_video_registry()
        is_pause = action == "pause"
        wm = get_vision_worker()
        for cid in cids:
            # 登记电流页暂停态：供之后新开的视频流/监控路继承该状态。
            reg.set_paused(cid, is_pause)
            wm.send({"cmd": cmd, "job": cid})
        narrative.event(
            "current_vision_sync",
            action=action,
            channels=sorted(cids),
            note=f"电流检测 {action} 已同步到 {len(cids)} 个通道的视频流检测",
        )

    def _sync_vision_stop(self, cids: list) -> None:
        """把电流页的停止同步到监控：从 54 路静默监控中移除这些通道（单向：电流→视频）。

        通常由 `_sync_vision_follow` 全量跟随即可；此方法保留入口，供老化完成等
        路径即时移除单/多路；worker 对不存在的路幂等忽略。
        """
        rm = [int(c) for c in (cids or [])]
        if not rm:
            return
        get_vision_worker().send({"cmd": "monitor_sync", "remove": rm})
        if hasattr(self, "_mon_active"):
            self._mon_active.difference_update(rm)
        narrative.event(
            "current_vision_sync",
            action="stop",
            channels=sorted(rm),
            note=f"电流检测 stop 已从静默监控移除 {len(rm)} 个通道",
        )

    def _sync_vision_start(self, cids: list) -> list:
        """(保留接口) 视频检测由 `_sync_vision_follow` 动态跟随电流集合，本方法不再单独拉起。"""
        return []

    def _sync_vision_follow(self) -> None:
        """把「电流运行集合」同步为 54 路静默监控 monitor 的通道集合（动态跟随）。

        电流启动/停止/暂停都经 `_sync_source_running`，本方法据此全量对齐监控：
        取 `current_running_cids()` 中「有视频源」的通道；首次建立用 `monitor`
        全量开，之后用 `monitor_sync` 增量增删（保各路统计持续）。超出 54 路上限
        的通道因硬件限制不监控。
        """
        if not hasattr(self, "_mon_active"):
            self._mon_active = set()
            self._mon_started = False
        from app.services.channel_video_registry import get_channel_video_registry
        reg = get_channel_video_registry()
        current = {c for c in reg.current_running_cids() if reg.path(c)}
        if len(current) > 54:
            current = set(sorted(current)[:54])
        wm = get_vision_worker()
        if self._mon_started and not current:
            wm.send({"cmd": "monitor_stop"})
            self._mon_active.clear()
            self._mon_started = False
            return
        if not self._mon_started and current:
            jobs = [{"job": c, "video": reg.path(c), "paused": reg.is_paused(c)}
                    for c in sorted(current)]
            # monitor 默认 4fps、320×320、GPU 批量（见 worker），适应 54 路级静默检测
            wm.send({"cmd": "monitor", "jobs": jobs, "loop": True, "fps": 4.0})
            self._mon_active = set(current)
            self._mon_started = True
            return
        if self._mon_started:
            rem = self._mon_active - current
            add = current - self._mon_active
            if rem:
                wm.send({"cmd": "monitor_sync", "remove": sorted(rem)})
            if add:
                wm.send({"cmd": "monitor_sync",
                         "add": [{"job": c, "video": reg.path(c),
                                  "paused": reg.is_paused(c)}
                                 for c in sorted(add)]})
            self._mon_active = set(current)

    def _on_toolbar_action(self, action: str) -> None:
        cids = list(self._grid.selection())
        if action == "clear":
            self._grid.clear_selection()
            return
        if not cids:
            return
        transitioned = self._apply_action_to_cids(action, cids)
        _log.info(
            "toolbar action=%s requested=%d transitioned=%d",
            action, len(cids), len(transitioned),
        )

    # -- Esc 清空 / Ctrl+A 全选 ---------------------------------------------
    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key_Escape:
            self._grid.clear_selection()
            return
        if event.modifiers() & Qt.ControlModifier and event.key() == Qt.Key_A:
            self._grid.select_all()
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
