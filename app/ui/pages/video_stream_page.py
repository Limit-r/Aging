"""v3.0 视频流检测页（单通道详情）。

从视频总览双击某位点进入本页。针对该通道：
- 「导入视频」选择本地视频，「开始」下达检测命令给**常驻 worker**。
- 常驻 worker（`ml/vision/worker.py`）在进程启动时**预加载** YOLO+TinyConv 模型，
  之后按 job 逐帧检测，避免每次开始检测都重新加载模型。
- GUI 只通过 QProcess 向 worker 写 stdin 命令、读 stdout 事件（JSON），
  **不向 GUI 进程引入 torch**。

结果面板：实时检测画面 + 分类/亮灭/闪烁的卡片化展示。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from collections import OrderedDict
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import QProcess, QProcessEnvironment, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
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


def _repolish(widget: QWidget) -> None:
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)


class VsResultPanel(QWidget):
    """检测结果面板：分类行 + 闪烁折线图 + LED 亮/灭时刻表。

    使用 keyed 复用避免每个采样全量重建导致闪烁；未出现的行隐藏。
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("vsResult")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self._title = QLabel(labels.VIDEO_STATS_TITLE)
        self._title.setObjectName("vsPanelTitle")
        lay.addWidget(self._title)

        self._placeholder = QLabel(labels.VIDEO_STATS_NONE)
        self._placeholder.setObjectName("vsEmpty")
        self._placeholder.setAlignment(Qt.AlignCenter)
        self._placeholder.setWordWrap(True)
        lay.addWidget(self._placeholder, 1)

        self._count_title = QLabel(labels.VIDEO_COUNT_SECTION_TITLE)
        self._count_title.setObjectName("vsSectionTitle")
        self._count_rows: "OrderedDict[str, tuple]" = OrderedDict()
        self._rows_box = QVBoxLayout()
        self._rows_box.setSpacing(4)

        # 闪烁折线图（累计闪烁次数 / 检测秒）
        self._flash_title = QLabel(labels.VIDEO_FLASH_SECTION_TITLE)
        self._flash_title.setObjectName("vsSectionTitle")
        self._chart_title = QLabel(labels.VIDEO_FLASH_CHART_TITLE)
        self._chart_title.setObjectName("vsSectionTitle")
        self._chart = pg.PlotWidget()
        self._chart.setObjectName("vsFlashChart")
        bg = _C.RACK_3D_BG
        self._chart.setBackground(
            (bg[0] / 255.0, bg[1] / 255.0, bg[2] / 255.0))
        self._chart.showGrid(x=True, y=True, alpha=0.25)
        self._chart.setLabel("bottom", labels.VIDEO_FLASH_X_LABEL)
        self._chart.setLabel("left", labels.VIDEO_FLASH_Y_LABEL)
        cyan = _C.LED_PAUSED
        self._flash_curve = self._chart.plot(
            pen=pg.mkPen((cyan[0], cyan[1], cyan[2]), width=2))
        self._chart.setFixedHeight(_S.VIDEO_CHART_H)
        self._flash_series: list = []
        self._last_series_sec: int = -1

        # LED 亮/灭时刻表
        self._timing_title = QLabel(labels.VIDEO_TIMING_SECTION_TITLE)
        self._timing_title.setObjectName("vsSectionTitle")
        self._timing_scroll = QScrollArea()
        self._timing_scroll.setObjectName("vsTimingScroll")
        self._timing_scroll.setWidgetResizable(True)
        self._timing_scroll.setFrameShape(QFrame.NoFrame)
        self._timing_host = QWidget()
        self._timing_host.setObjectName("vsTimingHost")
        self._timing_grid = QVBoxLayout(self._timing_host)
        self._timing_grid.setContentsMargins(0, 0, 0, 0)
        self._timing_grid.setSpacing(2)
        self._timing_scroll.setWidget(self._timing_host)
        self._timing_rows: "OrderedDict[str, tuple]" = OrderedDict()

        lay.addWidget(self._count_title)
        lay.addLayout(self._rows_box)
        lay.addWidget(self._flash_title)
        lay.addWidget(self._chart_title)
        lay.addWidget(self._chart)
        lay.addWidget(self._timing_title)
        lay.addWidget(self._timing_scroll, 1)
        lay.addStretch(0)

    # -- 分类行 ---------------------------------------------------------
    def _badge(self, kind: str) -> QLabel:
        b = QLabel(kind)
        b.setObjectName("vsBadge")
        b.setProperty("vbadge", kind)
        b.setAlignment(Qt.AlignCenter)
        b.setFixedHeight(_S.VIDEO_BADGE_H)
        _repolish(b)
        return b

    def _make_row(self, name: str) -> None:
        wrap = QWidget()
        wrap.setObjectName("vsRow")
        hl = QHBoxLayout(wrap)
        hl.setContentsMargins(6, 3, 6, 3)
        hl.setSpacing(8)
        name_lb = QLabel(name)
        name_lb.setObjectName("vsRowName")
        count_lb = QLabel("0")
        count_lb.setObjectName("vsRowCount")
        h_badge = self._badge(labels.VBADGE_H)
        l_badge = self._badge(labels.VBADGE_L)
        hl.addWidget(name_lb)
        hl.addStretch(1)
        hl.addWidget(count_lb)
        hl.addWidget(h_badge)
        hl.addWidget(l_badge)
        self._rows_box.addWidget(wrap)
        self._count_rows[name] = (name_lb, count_lb, h_badge, l_badge)

    def _set_badge(self, lb: QLabel, kind: str, n: int) -> None:
        lb.setText(f"{kind} {n}")
        lb.setProperty("active", n > 0)
        _repolish(lb)

    def set_data(self, counts: dict, hl: dict, flashes: dict,
                 sw: Optional[dict] = None,
                 elapsed: Optional[float] = None) -> None:
        """刷新分类 / 折线图 / 时刻表。

        counts: {name:n}；hl: {name:{H,L}}；flashes: {led:n}；
        sw: {led:{state,on,on_s,off_s,flashes}}；elapsed: 检测已运行秒数。
        """
        have = bool(counts) or bool(flashes) or bool(sw)
        self._placeholder.setVisible(not have)
        self._title.setVisible(have)

        names = sorted(counts.keys())
        for name in names:
            if name not in self._count_rows:
                self._make_row(name)
            row = self._count_rows[name]
            h = hl.get(name, {"H": 0, "L": 0})
            row[0].setText(name)
            row[1].setText(str(counts[name]))
            self._set_badge(row[2], labels.VBADGE_H, h.get("H", 0))
            self._set_badge(row[3], labels.VBADGE_L, h.get("L", 0))
            row[0].parentWidget().show()
        for name, row in list(self._count_rows.items()):
            if name not in names:
                row[0].parentWidget().hide()
        self._count_title.setVisible(bool(counts))

        # 闪烁折线图
        if flashes:
            self._update_chart(flashes, elapsed)
            self._chart_title.show()
            self._chart.show()
        self._flash_title.setVisible(bool(flashes))

        # LED 亮/灭时刻表
        if sw:
            self._update_timing(sw)

    # -- 闪烁折线图 -----------------------------------------------------
    def _update_chart(self, flashes: dict, elapsed: Optional[float]) -> None:
        total = sum(flashes.values())
        sec = int(elapsed) if elapsed is not None else 0
        if sec > self._last_series_sec:
            self._last_series_sec = sec
            self._flash_series.append([elapsed, total])
        if not self._flash_series:
            return
        xs = [p[0] for p in self._flash_series]
        ys = [p[1] for p in self._flash_series]
        self._flash_curve.setData(xs, ys)
        self._chart.setXRange(0, max(xs[-1], 1) + 0.5, padding=0)
        self._chart.setYRange(0, max(ys), padding=0.1)

    # -- LED 亮/灭时刻表 -------------------------------------------------
    def _make_timing_row(self, led: str) -> None:
        wrap = QWidget()
        wrap.setObjectName("vsTimingRow")
        wrap.setMinimumHeight(_S.VIDEO_TIMING_ROW_H)
        hl = QHBoxLayout(wrap)
        hl.setContentsMargins(6, 0, 6, 0)
        hl.setSpacing(8)
        led_lb = QLabel(led)
        led_lb.setObjectName("vsRowName")
        state_badge = self._badge(labels.VBADGE_H)
        on_lb = QLabel("")
        on_lb.setObjectName("vsTimingStat")
        on_lb.setAlignment(Qt.AlignCenter)
        off_lb = QLabel("")
        off_lb.setObjectName("vsTimingStat")
        off_lb.setAlignment(Qt.AlignCenter)
        flash_lb = QLabel("")
        flash_lb.setObjectName("vsTimingFlash")
        flash_lb.setAlignment(Qt.AlignRight)
        hl.addWidget(led_lb)
        hl.addWidget(state_badge)
        hl.addStretch(1)
        hl.addWidget(on_lb)
        hl.addWidget(off_lb)
        hl.addWidget(flash_lb)
        self._timing_grid.addWidget(wrap)
        self._timing_rows[led] = (wrap, state_badge, on_lb, off_lb, flash_lb)

    def _update_timing(self, sw: dict) -> None:
        seen = set()
        for led, s in sorted(sw.items()):
            seen.add(led)
            if led not in self._timing_rows:
                self._make_timing_row(led)
            row = self._timing_rows[led]
            st = s.get("state")
            badge_text = labels.VBADGE_H if st == "H" else labels.VBADGE_L
            row[1].setText(badge_text)
            row[1].setProperty("vbadge", badge_text)
            _repolish(row[1])
            on = s.get("on")
            row[2].setText(
                labels.VIDEO_TIMING_ON_TEMPLATE.format(s=on)
                if on is not None else labels.VIDEO_TIMING_ON_NONE)
            row[3].setText(
                labels.VIDEO_TIMING_OFF_TEMPLATE.format(s=s.get("off_s", 0)))
            row[4].setText(
                labels.VIDEO_TIMING_FLASH_TEMPLATE.format(n=s.get("flashes", 0)))
            row[0].show()
        for led, row in list(self._timing_rows.items()):
            if led not in seen:
                row[0].hide()
        self._timing_title.setVisible(bool(sw))

    def set_placeholder(self) -> None:
        self._placeholder.setText(labels.VIDEO_STATS_NONE)
        self._placeholder.show()
        self._title.show()
        for name, row in self._count_rows.items():
            row[0].parentWidget().hide()
        self._count_title.hide()

        # 清空折线图
        self._flash_series.clear()
        self._last_series_sec = -1
        self._flash_curve.setData([], [])
        self._flash_title.hide()
        self._chart_title.hide()
        self._chart.hide()

        # 清空时刻表
        self._timing_title.hide()
        for row in self._timing_rows.values():
            row[0].hide()

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
                payload.get("counts", {}), payload.get("hl", {}),
                payload.get("flashes", {}), payload.get("sw"),
                payload.get("elapsed"))
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