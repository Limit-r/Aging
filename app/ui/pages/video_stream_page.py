"""v3.0 视频流检测页（单通道详情）。

从视频总览双击某位点进入本页。针对该通道：
- 「导入视频」选择本地视频，「开始」下达检测命令给**常驻 worker**。
- 常驻 worker（`ml/vision/worker.py`）在进程启动时**预加载** YOLO+TinyConv 模型，
  之后按 job 逐帧检测，避免每次开始检测都重新加载模型。
- GUI 只通过 QProcess 向 worker 写 stdin 命令、读 stdout 事件（JSON），
  **不向 GUI 进程引入 torch**。

结果面板：实时检测画面 + VPL / CPL / PWR 三条闪烁折线图。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import QProcess, QProcessEnvironment, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

import pyqtgraph as pg

from app.core import config, labels
from app.core.tokens import DEFAULT_TOKENS
from app.observability import get_logger, narrative

_S = DEFAULT_TOKENS.sizing
_C = DEFAULT_TOKENS.colors
PROJECT_ROOT = Path(__file__).resolve().parents[3]   # d:\Aging
WORKER_SCRIPT = PROJECT_ROOT / "ml" / "vision" / "worker.py"

_log = get_logger("app.ui.pages.video_stream_page")


class VsResultPanel(QWidget):
    """检测结果面板：按系列（FP / A / 其他）各独立一张闪烁折线图。

    area 类已在 worker 侧排除，仅统计信号灯（CPL/VPL 等）的闪烁；
    系列自动区分：FP 系列 / A 系列 / 后续其他系列。
    """

    # 系列标识（自动区分；除 FP/A 外的其他系列归入 other）
    SERIES_ORDER: tuple = ("FP", "A", "other")

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("vsResult")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        self._title = QLabel(labels.VIDEO_STATS_TITLE)
        self._title.setObjectName("vsPanelTitle")
        lay.addWidget(self._title)

        self._flash_title = QLabel(labels.VIDEO_FLASH_SECTION_TITLE)
        self._flash_title.setObjectName("vsSectionTitle")
        lay.addWidget(self._flash_title)

        # 系列滚动区：窗口高度不足时内部滚动，不再挤压窗口尺寸
        self._scroll = QScrollArea()
        self._scroll.setObjectName("vsSeriesScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._host = QWidget()
        self._host.setObjectName("vsSeriesHost")
        self._blocks = QVBoxLayout(self._host)
        self._blocks.setContentsMargins(0, 0, 0, 0)
        self._blocks.setSpacing(10)
        self._scroll.setWidget(self._host)

        self._charts: dict = {}
        self._series: dict = {}
        palette = [_C.LED_PAUSED, _C.LED_RUNNING, _C.LED_WARNING]
        for i, series in enumerate(self.SERIES_ORDER):
            block = QWidget()
            bv = QVBoxLayout(block)
            bv.setContentsMargins(0, 0, 0, 0)
            bv.setSpacing(4)
            display = labels.VIDEO_SERIES_OTHER if series == "other" else series
            stitle = QLabel(
                labels.VIDEO_SERIES_TITLE_TEMPLATE.format(series=display))
            stitle.setObjectName("vsSectionTitle")
            plot = pg.PlotWidget()
            plot.setObjectName("vsFlashChart")
            bg = _C.RACK_3D_BG
            plot.setBackground(
                (bg[0] / 255.0, bg[1] / 255.0, bg[2] / 255.0))
            plot.showGrid(x=True, y=True, alpha=0.25)
            plot.setLabel("bottom", labels.VIDEO_FLASH_X_LABEL)
            plot.setLabel("left", labels.VIDEO_FLASH_Y_LABEL)
            plot.setFixedHeight(_S.VIDEO_CHART_BLOCK_H)
            c = palette[i]
            curve = plot.plot(pen=pg.mkPen((c[0], c[1], c[2]), width=2))
            bv.addWidget(stitle)
            bv.addWidget(plot)
            self._blocks.addWidget(block)
            self._charts[series] = (block, plot, curve)
            self._series[series] = []
        lay.addWidget(self._scroll, 1)

        self._placeholder = QLabel(labels.VIDEO_STATS_NONE)
        self._placeholder.setObjectName("vsEmpty")
        self._placeholder.setAlignment(Qt.AlignCenter)
        self._placeholder.setWordWrap(True)
        lay.addWidget(self._placeholder, 1)
        self._placeholder.hide()
        self._last_series_sec: int = -1

    @staticmethod
    def _series_of(led: str) -> str:
        base = led.split("_", 1)[0]
        return base if base in ("FP", "A") else "other"

    def set_data(self, flashes: dict, elapsed: Optional[float] = None) -> None:
        """刷新各系列折线图。flashes: {led:累计闪烁数}。"""
        have = bool(flashes)
        self._placeholder.setVisible(not have)
        self._title.setVisible(True)
        self._flash_title.setVisible(have)
        self._scroll.setVisible(have)
        if flashes:
            self._update_chart(flashes, elapsed)

    def _update_chart(self, flashes: dict, elapsed: Optional[float]) -> None:
        sec = int(elapsed) if elapsed is not None else 0
        if sec > self._last_series_sec:
            self._last_series_sec = sec
            for series in self.SERIES_ORDER:
                total = sum(v for led, v in flashes.items()
                            if self._series_of(led) == series)
                self._series[series].append([elapsed, total])
        for series in self.SERIES_ORDER:
            pts = self._series[series]
            if not pts:
                continue
            block, plot, curve = self._charts[series]
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            curve.setData(xs, ys)
            plot.setXRange(0, max(xs[-1], 1) + 0.5, padding=0)
            plot.setYRange(0, max(max(ys), 1), padding=0.1)

    def set_placeholder(self) -> None:
        self._placeholder.setText(labels.VIDEO_STATS_NONE)
        self._placeholder.show()
        self._title.show()
        self._flash_title.hide()
        self._scroll.hide()
        self._series = {s: [] for s in self.SERIES_ORDER}
        self._last_series_sec = -1
        for block, plot, curve in self._charts.values():
            curve.setData([], [])

    def set_message(self, msg: str) -> None:
        self.set_placeholder()
        self._placeholder.setText(msg or labels.VIDEO_CELL_STATE_ERROR)


class VideoStreamPage(QWidget):
    """单通道视频流检测页。"""
    requested_back = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("videoStreamPage")
        self._cid: Optional[int] = None
        self._video_path: Optional[str] = None
        self._worker = None       # 常驻 worker QProcess
        self._worker_buf = ""
        self._worker_ready = False
        self._running = False
        self._outdir = Path(tempfile.mkdtemp(prefix="aging_videostream_"))
        self._build_ui()
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(_S.VIDEO_REFRESH_MS)
        self._refresh_timer.timeout.connect(self._refresh_video)
        self._ensure_worker()
        narrative.event(
            "video_stream_init",
            note="v3.0 视频流检测页：常驻 worker 预加载模型，逐帧检测")

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
        self._btn_start = self._make_btn(labels.VIDEO_TOOLBAR_BTN_START)
        self._btn_stop = self._make_btn(labels.VIDEO_TOOLBAR_BTN_STOP)
        self._btn_import.clicked.connect(self._on_import)
        self._btn_start.clicked.connect(self._on_start)
        self._btn_stop.clicked.connect(self._on_stop)
        bl.addWidget(self._btn_import)
        bl.addWidget(self._btn_start)
        bl.addWidget(self._btn_stop)
        outer.addWidget(bar)

        # 主体：左实时画面 + 右结果卡片
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
        self._video = QLabel(labels.VIDEO_PANEL_EMPTY_HINT)
        self._video.setObjectName("vsVideo")
        self._video.setAlignment(Qt.AlignCenter)
        self._video.setWordWrap(True)
        # Ignored 策略：让图像缩放跟随可用空间，防止图像 sizeHint 顶大窗口/预览区
        self._video.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        lv.addWidget(self._video, 1)
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

    def _make_btn(self, text: str) -> QPushButton:
        b = QPushButton(text)
        b.setObjectName("btnBatch")
        b.setCursor(Qt.PointingHandCursor)
        b.setMinimumHeight(_S.TOOLBAR_BTN_MIN_H)
        return b

    # -- 常驻 worker -----------------------------------------------------
    def _ensure_worker(self) -> None:
        """启动/复用常驻检测 worker（模型预加载，启动后持续存活）。"""
        if self._worker is not None:
            return
        proc = QProcess(self)
        proc.setProcessChannelMode(QProcess.MergedChannels)
        penv = QProcessEnvironment.systemEnvironment()
        penv.insert("PYTHONIOENCODING", "utf-8")
        penv.insert("PYTHONUNBUFFERED", "1")
        proc.setProcessEnvironment(penv)
        proc.setWorkingDirectory(str(PROJECT_ROOT))
        proc.readyReadStandardOutput.connect(self._on_worker_stdout)
        proc.finished.connect(self._on_worker_finished)
        proc.errorOccurred.connect(self._on_worker_error)
        self._worker = proc
        self._worker_buf = ""
        self._worker_ready = False
        proc.start(sys.executable, [str(WORKER_SCRIPT)])
        narrative.event("vision_worker_preload", note="常驻检测 worker 启动（模型预加载）")

    def _on_worker_stdout(self) -> None:
        proc = self._worker
        if proc is None:
            return
        data = bytes(proc.readAllStandardOutput()).decode("utf-8", "replace")
        lines = (self._worker_buf + data).split("\n")
        self._worker_buf = lines.pop()
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except (ValueError, json.JSONDecodeError):
                continue
            self._handle_worker_event(payload)

    def _handle_worker_event(self, payload: dict) -> None:
        ptype = payload.get("type")
        if ptype == "ready":
            self._worker_ready = True
            _log.info("vision worker ready: %s", payload.get("device"))
        elif ptype == "fatal":
            self._result.set_message(payload.get("message", ""))
            self._finish_run()
        elif ptype == "error" and payload.get("job") == self._cid:
            self._result.set_message(payload.get("message", labels.VIDEO_CELL_STATE_ERROR))
            self._finish_run()
        elif ptype == "sample" and payload.get("job") == self._cid:
            self._result.set_data(
                payload.get("flashes", {}), payload.get("elapsed"))
        elif ptype == "done" and payload.get("job") == self._cid:
            self._video.setText(labels.VIDEO_CELL_STATE_DONE)
            self._finish_run()

    def _on_worker_finished(self, _code: int, _status: int) -> None:
        _log.warning("vision worker exited")
        self._worker = None
        self._worker_ready = False
        if self._running:
            self._result.set_message(labels.VIDEO_CELL_STATE_ERROR)
            self._finish_run()

    def _on_worker_error(self, error: QProcess.ProcessError) -> None:
        _log.warning("vision worker error: %s", error)
        if self._running:
            self._result.set_message(labels.VIDEO_CELL_STATE_ERROR)
            self._finish_run()

    # -- 工具条动作 ---------------------------------------------------------
    def _on_back(self) -> None:
        self._stop_detection()
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
        self._result.set_placeholder()
        self._btn_start.setEnabled(True)

    def _on_start(self) -> None:
        if self._video_path is None or self._cid is None or self._running:
            return
        if self._worker is None:
            self._ensure_worker()
        self._video.setText(labels.VIDEO_PANEL_LOADING)
        self._btn_start.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self._running = True
        self._send({"cmd": "detect", "job": self._cid,
                    "video": self._video_path, "outdir": str(self._outdir)})
        self._refresh_timer.start()
        narrative.event(
            "video_stream_start", note=f"CH-{self._cid:02d} 逐帧检测启动")

    def _on_stop(self) -> None:
        self._stop_detection(mark_idle=True)

    def _send(self, obj: dict) -> None:
        proc = self._worker
        if proc is None:
            return
        proc.write((json.dumps(obj) + "\n").encode("utf-8"))

    def _stop_detection(self, mark_idle: bool = False) -> None:
        if self._cid is not None and self._running:
            self._send({"cmd": "stop", "job": self._cid})
        self._running = False
        self._stop_timer()
        self._btn_stop.setEnabled(False)
        if not mark_idle:
            self._btn_start.setEnabled(bool(self._video_path))

    def _finish_run(self) -> None:
        self._running = False
        self._stop_timer()
        self._btn_stop.setEnabled(False)
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
    def set_channel(self, cid: int) -> None:
        self._stop_detection()
        self._cid = cid
        self._title.setText(labels.VIDEO_STREAM_TITLE_TEMPLATE.format(cid=cid))
        _log.info("video stream set channel: CH-%02d", cid)

    def closeEvent(self, event) -> None:
        self._stop_detection()
        if self._worker is not None:
            self._send({"cmd": "quit"})
            self._worker.terminate()
        event.accept()