"""v3.1 视频流检测页（单通道详情）。

从视频总览双击某位点进入本页。针对该通道：
- 「导入视频」选择本地视频，「开始」下达检测命令给**全局常驻 worker**。
- 常驻 worker（`ml/vision/worker.py`，由 `app/ui/vision_worker.py` 单例管理）
  在进程启动时**预加载** YOLO+TinyConv 模型，之后按 job 逐帧检测，复用不重复启动。
- GUI 只向 worker 的 stdin 写命令、读 stdout 事件（JSON），**不向 GUI 引入 torch**。

结果面板：
- **系列自动判定（仅标题）**：根据检测结果（LED 基础类前缀）自动标注系列
  （FP / A / 其他）。
- **所有信号灯类别都纳入**：检测到的信号灯（含 pwr，worker 侧已排除 area）
  全部进入亮灭统计，不按系列丢弃。
- **按统一位置分组多表**：把信号灯按槽位（LED 名末位 `_N`）分组，
  同一槽位的 `pwr0`/`vpl0` 排在同一张亮灭方波表内相邻；最多 4 张表。
- 每张表：Y 轴=LED 位点行、X 轴=时间，亮(H)/灭(L) 以方波折线表示；
  表下方一行统计该组累计闪烁次数 + 检测时长。
- 视频预览按输入分辨率等比缩放到固定小窗口居中显示。
"""
from __future__ import annotations

import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

import pyqtgraph as pg

from app.core import labels
from app.core.tokens import DEFAULT_TOKENS
from app.observability import get_logger, narrative
from app.services.channel_video_registry import get_channel_video_registry
from app.ui.vision_worker import get_vision_worker
from app.ui.qss_utils import refresh_qss

_S = DEFAULT_TOKENS.sizing
_C = DEFAULT_TOKENS.colors

_log = get_logger("app.ui.pages.video_stream_page")

PROJECT_ROOT = Path(__file__).resolve().parents[3]   # d:\Aging

# 无摄像头联动测试用默认视频：进入页面自动载入并循环检测，便于验证暂停/恢复
DEFAULT_TEST_VIDEO = PROJECT_ROOT / "video" / "0001.mp4"

# 一个通道内最多同时展示的亮灭分组表数
MAX_TABLES = 4


class VsResultPanel(QWidget):
    """按统一位置分组的 LED 亮灭方波图（最多 4 张表）+ 每组闪烁/时长统计。

    - **所有信号灯类别都纳入**：检测到的信号灯（含 pwr，worker 侧已排除 area）
      全部进入统计，不按系列丢弃；系列仅在标题标注（best-effort）。
    - **分组多表**：信号灯按槽位（`base_<slot>` 的末位 `slot`）分组，
      同一槽位的 LED（如 pwr0 / vpl0）编排在同一张表内相邻；最多 `MAX_TABLES` 张。
    - 每张表：Y 轴为组内 LED 位点行，X 轴为时间，亮(H)/灭(L) 以方波折线表达；
      表下方一行统计该组累计闪烁 + 检测时长。
    - 硬性约定：用户可见文案一律 `labels.X`，尺寸/颜色走 `tokens.X`。
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("vsResult")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        self._title = QLabel(labels.VIDEO_STATS_TITLE)
        self._title.setObjectName("vsPanelTitle")
        lay.addWidget(self._title)

        # 滚动区：多张表时整体增高，面板内部滚动而不挤压窗口
        self._scroll = QScrollArea()
        self._scroll.setObjectName("vsSeriesScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._host = QWidget()
        self._host.setObjectName("vsSeriesHost")
        self._host_lay = QVBoxLayout(self._host)
        self._host_lay.setContentsMargins(0, 0, 0, 0)
        self._host_lay.setSpacing(12)
        self._scroll.setWidget(self._host)

        self._series_title = QLabel("")
        self._series_title.setObjectName("vsSectionTitle")
        self._host_lay.addWidget(self._series_title)

        self._scroll.hide()
        lay.addWidget(self._scroll, 1)

        self._placeholder = QLabel(labels.VIDEO_STATS_NONE)
        self._placeholder.setObjectName("vsEmpty")
        self._placeholder.setAlignment(Qt.AlignCenter)
        self._placeholder.setWordWrap(True)
        lay.addWidget(self._placeholder, 1)
        self._placeholder.show()

        # -- 状态 --
        self._series: Optional[str] = None      # 已判定的系列（FP/A/other）
        self._seen: set = set()                 # 该系列所有见过的 LED id
        self._tables: list = []                 # 分组表（按槽位）
        self._table_for_slot: dict = {}         # slot -> 表
        self._sec = 0

    # ------------------------------------------------------------------ 系列
    @staticmethod
    def _series_of(led: str) -> str:
        base = led.split("_", 1)[0]
        return base if base in ("FP", "A") else "other"

    @staticmethod
    def _display_name(series: str) -> str:
        return labels.VIDEO_SERIES_OTHER if series == "other" else series

    @staticmethod
    def _slot_of(led: str) -> str:
        return led.rsplit("_", 1)[1]

    def _determine_series(self, led_ids: list) -> None:
        if self._series is not None:
            return
        cnt = Counter(self._series_of(led) for led in led_ids)
        if not cnt:
            return
        self._series = max(cnt, key=cnt.get)
        self._series_title.setText(
            labels.VIDEO_SERIES_TITLE_TEMPLATE.format(
                series=self._display_name(self._series)))

    # ------------------------------------------------------------------ 表
    def _new_table(self, slot: str) -> dict:
        block = QWidget()
        bv = QVBoxLayout(block)
        bv.setContentsMargins(0, 0, 0, 0)
        bv.setSpacing(4)
        stitle = QLabel(
            labels.VIDEO_CH_TABLE_TITLE_TEMPLATE.format(ch=slot))
        stitle.setObjectName("vsSectionTitle")

        plot = pg.PlotWidget()
        plot.setObjectName("vsFlashChart")
        bg = _C.RACK_3D_BG
        plot.setBackground((bg[0] / 255.0, bg[1] / 255.0, bg[2] / 255.0))
        plot.showGrid(x=True, y=True, alpha=0.18)
        plot.setLabel("bottom", labels.VIDEO_WS_X_LABEL)
        plot.setLabel("left", labels.VIDEO_WS_Y_LABEL)
        plot.setAntialiasing(True)

        summary = QLabel("")
        summary.setObjectName("vsSeriesSummary")

        bv.addWidget(stitle)
        bv.addWidget(plot)
        bv.addWidget(summary)
        self._host_lay.addWidget(block)

        return {
            "slot": slot,
            "block": block,
            "plot": plot,
            "summary": summary,
            "leds": [],       # 组内 LED（位点行序）
            "lanes": {},      # led -> 行号
            "curves": {},     # led -> PlotDataItem
            "state": {},      # led -> 1/0 最近亮灭
            "samples": {},    # led -> [[sec, val], ...]
            "flashes": 0,
        }

    def _table_for(self, slot: str) -> dict:
        tb = self._table_for_slot.get(slot)
        if tb is None:
            tb = self._new_table(slot)
            self._tables.append(tb)
            self._table_for_slot[slot] = tb
            # 组表按槽位数排序，展示更稳定
            self._tables.sort(key=lambda t: (int(t["slot"]), t["slot"]))
        return tb

    # ------------------------------------------------------------------ 绘制
    def _pen(self, lane: int) -> pg.Pen:
        cols = _C.VIDEO_WAVE_COLORS
        c = cols[lane % len(cols)]
        return pg.mkPen((c[0], c[1], c[2]), width=2)

    def _value(self, tb: dict, led: str, on: bool) -> float:
        r = tb["lanes"][led]
        return r + (_S.VIDEO_WAVE_HIGH_INSET if on else _S.VIDEO_WAVE_LOW_INSET)

    def _ensure_lanes(self) -> None:
        """为该系列所有已知 LED 建立槽位分组与组内行（排序后稳定布局）。

        组表数量受 `MAX_TABLES` 上限约束，超出后新槽位不再创建。
        """
        for led in sorted(self._seen):
            slot = self._slot_of(led)
            if slot not in self._table_for_slot and \
                    len(self._table_for_slot) >= MAX_TABLES:
                continue
            tb = self._table_for(slot)
            if led in tb["lanes"]:
                continue
            lane = len(tb["leds"])
            tb["leds"].append(led)
            tb["lanes"][led] = lane
            tb["state"][led] = 0
            tb["samples"][led] = []
            curve = pg.PlotDataItem(pen=self._pen(lane), stepMode="left")
            tb["plot"].addItem(curve)
            tb["curves"][led] = curve

    def set_data(self, flashes: dict, elapsed, states: Optional[dict]) -> None:
        states = states or {}
        self._sec = int(elapsed) if elapsed is not None else 0
        led_ids = list(states.keys())
        if not led_ids:
            # 尚无检测到任何信号灯，保持占位
            self._placeholder.setVisible(True)
            self._scroll.hide()
            return
        # 系列仅用于标题（best-effort）；统计不按系列过滤
        self._determine_series(led_ids)
        self._placeholder.hide()
        self._scroll.show()
        # 纳入全部信号灯 LED（worker 侧已排除 area 类），保持连线连续性
        for led in led_ids:
            self._seen.add(led)
        self._ensure_lanes()

        # 按表推进方波与统计
        for tb in self._tables:
            for led in tb["leds"]:
                if led in states:
                    tb["state"][led] = 1 if states[led] == "H" else 0
                tb["samples"][led].append(
                    [self._sec, self._value(tb, led, tb["state"][led])])
            tb["flashes"] = sum(
                flashes.get(led, 0) for led in tb["leds"])
            self._render(tb)

    def _render(self, tb: dict) -> None:
        for led in tb["leds"]:
            pts = tb["samples"][led]
            if pts:
                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                tb["curves"][led].setData(xs, ys)
        n = len(tb["leds"])
        if n:
            plot = tb["plot"]
            # Y 轴范围需容纳行内 inset：最下行低值 ≈ LOW_INSET，最上行高值
            # ≈ (n-1)+HIGH_INSET，否则顶部那行会被裁到可视区外（缩放才可见）
            lo = _S.VIDEO_WAVE_LOW_INSET
            hi = _S.VIDEO_WAVE_HIGH_INSET
            plot.setYRange(-lo - 0.1, (n - 1) + hi + 0.1, padding=0)
            plot.getAxis("left").setTicks(
                [[(r + 0.5, led) for r, led in enumerate(tb["leds"])]])
            plot.setXRange(0, max(self._sec, 1) + 0.5, padding=0)
            plot.setFixedHeight(
                max(_S.VIDEO_CHART_BLOCK_H, n * _S.VIDEO_WAVE_LANE_H))
        tb["summary"].setText(
            labels.VIDEO_SERIES_SUMMARY_TEMPLATE.format(
                flashes=tb["flashes"], sec=self._sec))

    # ------------------------------------------------------------------ 复位
    def _reset(self) -> None:
        for tb in self._tables:
            tb["plot"].clear()
            tb["block"].deleteLater()
        self._tables = []
        self._table_for_slot = {}
        self._series = None
        self._seen = set()
        self._sec = 0
        self._series_title.setText("")
        self._placeholder.setText(labels.VIDEO_STATS_NONE)
        self._placeholder.show()
        self._scroll.hide()

    def set_message(self, msg: str) -> None:
        self._reset()
        self._placeholder.setText(
            msg or labels.VIDEO_CELL_STATE_ERROR)


class VideoStreamPage(QWidget):
    """单通道视频流检测页。"""
    requested_back = pyqtSignal()
    # action: "pause"/"resume"/"stop" —— 用户在本页的暂停/继续/停止，转发给
    # 电流页统一业务路径，实现「视频↔电流」在 pause/resume/stop 三态上的双向联动。
    action_requested = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("videoStreamPage")
        self._cid: Optional[int] = None
        self._video_path: Optional[str] = None
        self._outdir = Path(tempfile.mkdtemp(prefix="aging_videostream_"))
        self._running = False
        self._paused = False
        self._worker_ready = False
        # 全局单例 worker：跨页面复用，进程只启动一次
        self._wm = get_vision_worker()
        self._wm.ready.connect(self._on_worker_ready)
        self._wm.fatal.connect(self._on_worker_fatal)
        self._wm.job_event.connect(self._on_worker_event)
        self._build_ui()
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(_S.VIDEO_REFRESH_MS)
        self._refresh_timer.timeout.connect(self._refresh_video)
        self._wm.ensure_started()
        # 无摄像头联动测试：自动载入默认循环视频，便于直接点击「开始」验证
        if DEFAULT_TEST_VIDEO.exists():
            self._video_path = str(DEFAULT_TEST_VIDEO)
            self._video.setText(labels.VIDEO_PANEL_LOADING)
            self._btn_start.setEnabled(True)
            _log.info("auto-loaded default test video: %s", self._video_path)
        narrative.event(
            "video_stream_init",
            note="v3.1 视频流检测页：全局单例 worker + 槽位分组多表亮灭方波图")

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # 顶部工具条
        bar = QFrame(self)
        bar.setObjectName("vsToolbar")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(10, 0, 10, 0)
        bl.setSpacing(8)
        self._btn_back = QPushButton(labels.VIDEO_BACK_BTN)
        self._btn_back.setObjectName("vsBack")
        self._btn_back.setCursor(Qt.PointingHandCursor)
        self._btn_back.clicked.connect(self._on_back)
        bl.addWidget(self._btn_back)
        self._title = QLabel("")
        self._title.setObjectName("vsTitle")
        bl.addWidget(self._title)
        bl.addStretch(1)
        self._btn_import = self._make_btn(labels.VIDEO_TOOLBAR_BTN_IMPORT)
        self._btn_pause = self._make_btn(labels.VIDEO_TOOLBAR_BTN_PAUSE)
        self._btn_start = self._make_btn(labels.VIDEO_TOOLBAR_BTN_START)
        self._btn_stop = self._make_btn(labels.VIDEO_TOOLBAR_BTN_STOP)
        self._btn_import.clicked.connect(self._on_import)
        self._btn_pause.clicked.connect(self._on_pause)
        self._btn_start.clicked.connect(self._on_start)
        self._btn_stop.clicked.connect(self._on_stop)
        bl.addWidget(self._btn_import)
        bl.addWidget(self._btn_pause)
        bl.addWidget(self._btn_start)
        bl.addWidget(self._btn_stop)
        bl.addSpacing(8)
        # 检测状态指示：运行中 / 已暂停
        self._status = QLabel(labels.VIDEO_DETECT_STATUS_IDLE)
        self._status.setObjectName("vsDetectStatus")
        self._status.setProperty("state", "idle")
        bl.addWidget(self._status)
        outer.addWidget(bar)

        # 主体：左实时画面 + 右结果图表
        body = QHBoxLayout()
        body.setContentsMargins(8, 8, 8, 8)
        body.setSpacing(10)
        left = QFrame(self)
        left.setObjectName("vsLive")
        lv = QVBoxLayout(left)
        lv.setContentsMargins(8, 8, 8, 8)
        lv.setSpacing(6)
        live_title = QLabel(labels.VIDEO_LIVE_TITLE)
        live_title.setObjectName("vsPanelTitle")
        lv.addWidget(live_title)
        # 预览尺寸随视频等比缩放、居中显示（不再撑满左区域）
        wrap = QWidget()
        wh = QHBoxLayout(wrap)
        wh.setContentsMargins(0, 0, 0, 0)
        wh.addStretch(1)
        vv = QVBoxLayout()
        vv.setContentsMargins(0, 0, 0, 0)
        vv.addStretch(1)
        self._video = QLabel(labels.VIDEO_PANEL_EMPTY_HINT)
        self._video.setObjectName("vsVideo")
        self._video.setAlignment(Qt.AlignCenter)
        self._video.setWordWrap(True)
        # 暂停角标：作为预览子控件，叠加在冻结帧左上角，明确提示「已暂停」
        self._pause_badge = QLabel(labels.VIDEO_DETECT_STATUS_PAUSED, self._video)
        self._pause_badge.setObjectName("vsPauseBadge")
        self._pause_badge.setAlignment(Qt.AlignCenter)
        self._pause_badge.hide()
        vv.addWidget(self._video, 0, Qt.AlignCenter)
        vv.addStretch(1)
        wh.addLayout(vv, 0)
        wh.addStretch(1)
        lv.addWidget(wrap, 1)

        right = QFrame(self)
        right.setObjectName("vsStatsPanel")
        sv = QVBoxLayout(right)
        sv.setContentsMargins(10, 10, 10, 10)
        sv.setSpacing(8)
        self._result = VsResultPanel(right)
        sv.addWidget(self._result, 1)
        body.addWidget(left, 4)
        body.addWidget(right, 2)
        outer.addLayout(body, 1)

        self._btn_stop.setEnabled(False)
        self._btn_start.setEnabled(False)
        self._btn_pause.setEnabled(False)

    def _make_btn(self, text: str) -> QPushButton:
        b = QPushButton(text)
        b.setObjectName("btnBatch")
        b.setCursor(Qt.PointingHandCursor)
        b.setMinimumHeight(_S.TOOLBAR_BTN_MIN_H)
        return b

    # -- 预览尺寸随视频分辨率缩放 -----------------------------------------
    def _set_preview_size(self, w, h) -> None:
        try:
            w, h = int(w), int(h)
        except (TypeError, ValueError):
            return
        if w <= 0 or h <= 0:
            return
        max_w = _S.VIDEO_PREVIEW_MAX_W
        max_h = _S.VIDEO_PREVIEW_MAX_H
        scale = min(max_w / w, max_h / h, 1.0)
        self._video.setFixedSize(int(w * scale), int(h * scale))
        self._pause_badge.adjustSize()
        self._pause_badge.move(6, 6)
        self._video.setPixmap(QPixmap())  # 清空旧图避免残留拉伸

    # -- worker 事件（来自全局单例）-----------------------------------------
    def _on_worker_ready(self, device: str) -> None:
        self._worker_ready = True
        _log.info("vision worker ready: %s", device)

    def _on_worker_fatal(self, message: str) -> None:
        self._worker_ready = False
        self._result.set_message(
            message or labels.VIDEO_CELL_STATE_ERROR)
        self._finish_run()
        self._set_detect_status("error", labels.VIDEO_DETECT_STATUS_ERROR)

    def _on_worker_event(self, payload: dict) -> None:
        ptype = payload.get("type")
        if ptype == "job_start" and payload.get("job") == self._cid:
            self._set_preview_size(payload.get("w"), payload.get("h"))
        elif ptype == "sample" and payload.get("job") == self._cid:
            self._result.set_data(
                payload.get("flashes", {}), payload.get("elapsed"),
                payload.get("states"))
        elif ptype == "paused" and payload.get("job") == self._cid:
            self._paused = True
            self._refresh_pause_ui()
            narrative.event(
                "video_stream_paused", note=f"CH-{self._cid:02d} 视频检测已暂停")
        elif ptype == "resumed" and payload.get("job") == self._cid:
            self._paused = False
            self._refresh_pause_ui()
            narrative.event(
                "video_stream_resumed", note=f"CH-{self._cid:02d} 视频检测已恢复")
        elif ptype == "done" and payload.get("job") == self._cid:
            self._video.setText(labels.VIDEO_CELL_STATE_DONE)
            self._finish_run()
        elif ptype == "error" and payload.get("job") == self._cid:
            self._result.set_message(
                payload.get("message") or labels.VIDEO_CELL_STATE_ERROR)
            self._finish_run()
            self._set_detect_status("error", labels.VIDEO_DETECT_STATUS_ERROR)

    # -- 工具条动作 ---------------------------------------------------------
    def _on_back(self) -> None:
        # 返回总览：若该通道仍由电流驱动运行，则保留后台检测持续统计（不看也累计），
        # 仅复位本页展示；否则按普通停止释放。
        self._leave_channel()
        self.requested_back.emit()

    def _on_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, labels.VIDEO_IMPORT_DIALOG_TITLE, "",
            labels.VIDEO_IMPORT_FILTER)
        if not path:
            return
        self._stop_detection()
        self._video_path = path
        self._video.setText(os.path.basename(path))
        self._result._reset()
        self._btn_start.setEnabled(True)
        if self._cid is not None:
            get_channel_video_registry().set_path(self._cid, path)

    def _on_start(self) -> None:
        if self._video_path is None or self._cid is None or self._running:
            return
        # 视频检测默认跟随电流：仅当该通道处于电流检测「运行/暂停」集合时才启动，
        # 保证「电流启动哪个通道，就开哪路视频检测」一一对应，杜绝把电流未运行的
        # 通道（如从总览双击进入）也拉起来。
        reg = get_channel_video_registry()
        if self._cid not in reg.current_running_cids():
            self._result.set_message(labels.VIDEO_NEED_CURRENT_RUNNING)
            self._set_detect_status("idle", labels.VIDEO_NEED_CURRENT_RUNNING)
            return
        self._wm.ensure_started()
        self._video.setText(labels.VIDEO_PANEL_LOADING)
        self._btn_start.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self._running = True
        self._paused = get_channel_video_registry().is_paused(self._cid)
        self._wm.send({"cmd": "detect", "job": self._cid,
                       "video": self._video_path, "outdir": str(self._outdir),
                       "loop": True,
                       "paused": self._paused})
        narrative.event(
            "video_stream_start", note=f"CH-{self._cid:02d} 循环检测启动")
        # 运行中→启动缩略图刷新；暂停开流→冻结预览并显示角标（勿先启定时器）
        self._refresh_pause_ui()

    def _on_stop(self) -> None:
        self._stop_detection(mark_idle=True)
        # 视频“停止” → 同步到电流页（controller.stop + 倒计时取消 + 电流→视频 stop 幂等）
        self.action_requested.emit("stop")

    def _on_pause(self) -> None:
        """切换当前检测的暂停/恢复（视频模块自身按钮）。"""
        if self._cid is None or not self._running:
            return
        if self._paused:
            self._wm.ensure_started()
            self._wm.send({"cmd": "resume", "job": self._cid})
            # 即时反馈；worker resumed 事件到达后 _refresh_pause_ui 再次校正确认
            self._paused = False
            self._refresh_pause_ui()
            self.action_requested.emit("resume")
        else:
            self._wm.ensure_started()
            self._wm.send({"cmd": "pause", "job": self._cid})
            self._paused = True
            self._refresh_pause_ui()
            self.action_requested.emit("pause")

    def _set_detect_status(self, state: str, text: str) -> None:
        """刷新检测状态指示（文本 + `[state]` QSS 颜色）。"""
        self._status.setText(text)
        self._status.setProperty("state", state)
        refresh_qss(self._status)

    def _set_pause_badge(self, show: bool, text: Optional[str] = None) -> None:
        """控制暂停角标显隐，并保持在预览左上角。"""
        if text is not None:
            self._pause_badge.setText(text)
        if show:
            self._pause_badge.adjustSize()
            self._pause_badge.move(6, 6)
        self._pause_badge.setVisible(show)

    def _refresh_pause_ui(self) -> None:
        """按当前 _running/_paused 刷新暂停按钮、状态颜色与预览冻结。"""
        if not self._running:
            self._btn_pause.setEnabled(False)
            self._set_detect_status("idle", labels.VIDEO_DETECT_STATUS_IDLE)
            self._set_pause_badge(False)
            return
        self._btn_pause.setEnabled(True)
        if self._paused:
            # 已暂停：冻结最后一帧（停缩略图刷新，避免陈旧帧覆盖暂停提示）
            # 并在预览左上角叠加「已暂停」角标，明确暂停反馈。
            self._btn_pause.setText(labels.VIDEO_TOOLBAR_BTN_RESUME)
            self._set_detect_status("paused", labels.VIDEO_DETECT_STATUS_PAUSED)
            self._set_pause_badge(True)
            self._stop_timer()
        else:
            self._btn_pause.setText(labels.VIDEO_TOOLBAR_BTN_PAUSE)
            self._set_detect_status("running", labels.VIDEO_DETECT_STATUS_RUNNING)
            self._set_pause_badge(False)
            if not self._refresh_timer.isActive():
                self._refresh_timer.start()

    def _stop_detection(self, mark_idle: bool = False) -> None:
        if self._cid is not None and self._running:
            self._wm.send({"cmd": "stop", "job": self._cid})
        self._running = False
        self._paused = False
        self._stop_timer()
        self._btn_stop.setEnabled(False)
        self._refresh_pause_ui()
        if not mark_idle:
            self._btn_start.setEnabled(bool(self._video_path))

    def _leave_channel(self) -> None:
        """切走/关闭检测页：仅在电流不运行该通道时才真正停流。

        若该通道仍处于「电流运行/暂停」集合中，则后台视频检测必须持续（电流
        驱动启停、不看也统计），这里只复位本页展示状态；否则按普通停止释放。
        """
        cid = self._cid
        running = cid is not None and self._running
        if running:
            reg = get_channel_video_registry()
            if cid in reg.current_running_cids():
                # 电流仍在跑该通道：保留后台流，仅清空本页展示
                self._running = False
                self._paused = False
                self._stop_timer()
                self._btn_stop.setEnabled(False)
                self._refresh_pause_ui()
                return
        self._stop_detection()

    def _finish_run(self) -> None:
        self._running = False
        self._paused = False
        self._stop_timer()
        self._btn_stop.setEnabled(False)
        self._refresh_pause_ui()
        self._btn_start.setEnabled(bool(self._video_path))

    def _stop_timer(self) -> None:
        if self._refresh_timer.isActive():
            self._refresh_timer.stop()

    # -- 实时画面 -----------------------------------------------------------
    def _refresh_video(self) -> None:
        if self._cid is None:
            return
        thumb = self._outdir / f"cell_{self._cid}.jpg"
        if not thumb.exists():
            return
        pix = QPixmap(str(thumb))
        if pix.isNull():
            return
        target = self._video.size()
        self._video.setPixmap(pix.scaled(
            target, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    # -- 公共 API / 生命周期 --------------------------------------------------
    def set_channel(self, cid: int, video_path: Optional[str] = None) -> None:
        """设置频道；若带 video_path（来自静默监控单击），直接载入并开始实时检测。"""
        self._leave_channel()
        self._cid = cid
        self._title.setText(labels.VIDEO_STREAM_TITLE_TEMPLATE.format(cid=cid))
        if video_path:
            self._video_path = video_path
            self._video.setText(os.path.basename(video_path))
            self._result._reset()
            self._btn_start.setEnabled(True)
            get_channel_video_registry().set_path(cid, video_path)
            _log.info("video stream set channel CH-%02d (带路径，直启)", cid)
            self._btn_start.click()   # 自动开始实时检测
            return
        # 无外部路径：若已自动载入默认测试视频，进入详情页即直接开始循环检测，
        # 便于验证状态灯能被持续识别（省去手动点「开始」）。
        if self._video_path:
            self._result._reset()
            self._btn_start.setEnabled(True)
            _log.info("video stream set channel CH-%02d (默认测试视频，自动开始)", cid)
            self._btn_start.click()
        else:
            _log.info("video stream set channel: CH-%02d", cid)

    def closeEvent(self, event) -> None:
        # 若当前通道仍由电流驱动运行，则保留后台检测流（持续统计），仅复位展示；
        # 否则停流释放。worker 为全局单例，由 HomePage 在应用退出时统一关闭。
        self._leave_channel()
        event.accept()