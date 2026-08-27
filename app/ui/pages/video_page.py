"""v3.0 视频检测·总览页（位置标记视图）。

本页只做**位点标记**：以 9×8 网格展示全部检测位点（CH-01 … CH-72），
**不显示检测结果**。双击某位点 → 发出 `open_stream_requested(cid)`，
由 HomePage 路由跳转到该通道的视频流检测页（video_stream）。

布局参考电流检测页的 9×8 网格，但每个单元仅是位置标签。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
    QVBoxLayout, QWidget,
)

from app.core import config, labels
from app.core.tokens import DEFAULT_TOKENS
from app.observability import get_logger, narrative
from app.services.channel_video_registry import get_channel_video_registry
from app.ui.vision_worker import get_vision_worker

_S = DEFAULT_TOKENS.sizing
PROJECT_ROOT = Path(__file__).resolve().parents[2]   # d:\Aging
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
        self._mark = mark
        self._mark_original = mark.text()
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

    # ------------------------------------------------------------ 静默监控
    def set_monitor(self, text: str) -> None:
        """静默监控时在单元中显示聚合信息（覆盖默认位点标记）。"""
        self._mark.setText(text)

    def clear_monitor(self) -> None:
        """退出/停止静默监控后恢复默认位点标记。"""
        self._mark.setText(self._mark_original)


class VideoOverviewPage(QWidget):
    """视频总览：位点标记网格。"""
    # (cid, video_path|None) —— 若该位点正被静默监控，带上视频路径供实时页直接开始
    open_stream_requested = pyqtSignal(int, object)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("videoPage")
        self._total = config.GRID_ROWS * config.GRID_COLS
        self._cells: dict[int, VideoMarkCell] = {}
        self._videos: dict[int, str] = {}      # cid -> 视频路径（静默监控映射）
        self._monitoring = False
        self._mon_done = False
        self._poll = QTimer(self)
        self._poll.setInterval(config.MONITOR_POLL_MS)
        self._poll.timeout.connect(self._poll_tick)
        self._build_ui()
        self._set_hint(labels.MONITOR_IDLE_HINT)
        self._wire_worker()
        self._auto_monitor_started = False
        self._try_load_default_videos()
        narrative.event(
            "video_overview_init",
            note="v3.0 视频总览：位点标记网格（双击进入视频流检测 / 54 路静默监控）")

    def showEvent(self, event) -> None:
        """首次显示时默认进入静默检测（自动载入默认测试视频并开始监控，一次性）。"""
        super().showEvent(event)
        if (not self._auto_monitor_started and self._videos
                and not self._monitoring and not self._mon_done):
            self._auto_monitor_started = True
            self._start_monitor()

    def _wire_worker(self) -> None:
        worker = get_vision_worker()
        worker.ensure_started()
        worker.job_event.connect(self._on_worker_event)

    # ------------------------------------------------------------ 控制联动注册
    def _sync_registry_paths(self) -> None:
        """把当前 `_videos`（cid→路径）登记到通道视频注册表，供电流页联动读取。"""
        reg = get_channel_video_registry()
        for cid, path in self._videos.items():
            reg.set_path(cid, path)

    def _sync_registry_monitor(self, active: bool) -> None:
        """登记/清除当前位点集在静默监控中的状态。"""
        if not self._videos:
            return
        get_channel_video_registry().set_monitored(list(self._videos), active)

    def _try_load_default_videos(self) -> None:
        """无外部载入时，用 ``video/`` 下的默认测试视频作为静默检测默认源。

        「默认进入静默检测」：进入视频检测页即自动载入（首路 CH-01，行序即通道），
        上限 `config.MONITOR_MAX_VIDEOS`。载入后首次 `showEvent` 会自动开始监控。
        """
        vids = [str(p) for p in sorted(PROJECT_ROOT.glob("video/*.mp4"))]
        if not vids:
            return
        if len(vids) > config.MONITOR_MAX_VIDEOS:
            vids = vids[:config.MONITOR_MAX_VIDEOS]
        self._videos = {cid: path for cid, path in enumerate(vids, start=1)}
        self._sync_registry_paths()
        self._start_btn.setEnabled(True)
        self._set_hint(labels.MONITOR_DEFAULT_AUTO.format(n=len(self._videos)))
        _log.info("video overview default source loaded: %d videos", len(vids))

    def _set_hint(self, text: str) -> None:
        if self._current_hint is not None:
            self._current_hint.setText(text)

    def _on_mark_opened(self, cid: int) -> None:
        """位点双击：若该路正被静默监控，带上其视频路径，实时页直接开始检测。"""
        path = self._videos.get(cid)
        self.open_stream_requested.emit(cid, path)

    # ------------------------------------------------------------ 静默监控控制
    def _choose_videos(self) -> None:
        files, _sel = QFileDialog.getOpenFileNames(
            self, labels.MONITOR_CHOOSE_DIALOG_TITLE.format(
                max=config.MONITOR_MAX_VIDEOS),
            "", labels.VIDEO_IMPORT_FILTER)
        if not files:
            return
        if len(files) > config.MONITOR_MAX_VIDEOS:
            self._set_hint(labels.MONITOR_TOO_MANY_ERROR.format(
                max=config.MONITOR_MAX_VIDEOS, n=len(files)))
            return
        self._videos = {cid: path for cid, path in enumerate(files, start=1)}
        self._sync_registry_paths()
        self._start_btn.setEnabled(True)
        self._set_hint(labels.MONITOR_CHOOSE_DIALOG_TITLE.format(
            max=config.MONITOR_MAX_VIDEOS))

    def _load_manifest(self) -> None:
        """从 .txt 清单加载视频列表（每行一个路径，行序对应 CH-01…）。

        相对路径按清单所在目录解析（便于写 ``video\\FP02.mp4`` 这类相对路径）。
        """
        mfile, _sel = QFileDialog.getOpenFileName(
            self, labels.MONITOR_MANIFEST_DIALOG_TITLE, "",
            labels.MONITOR_MANIFEST_FILTER)
        if not mfile:
            return
        base = os.path.dirname(mfile)
        self._videos = {}
        for idx, raw in enumerate(open(mfile, encoding="utf-8"), start=1):
            path = raw.strip().lstrip("\ufeff")   # 剥 UTF-8 BOM
            if not path or path.startswith("#"):
                continue
            if not os.path.isabs(path):
                full = os.path.join(base, path)
                if not os.path.exists(full):       # 也试相对工作目录
                    full = os.path.join(os.getcwd(), path)
            else:
                full = path
            if not os.path.exists(full):
                self._set_hint(labels.MONITOR_MANIFEST_MISSING.format(
                    idx=idx, path=path))
                return
            self._videos[len(self._videos) + 1] = full
            if len(self._videos) >= config.MONITOR_MAX_VIDEOS:
                break
        if not self._videos:
            self._set_hint(labels.MONITOR_MANIFEST_EMPTY)
            return
        self._sync_registry_paths()
        self._choose_btn.setEnabled(False)
        self._start_btn.setEnabled(True)
        self._set_hint(labels.MONITOR_MANIFEST_LOADED.format(
            n=len(self._videos)))
        _log.info("monitor manifest loaded: %d videos", len(self._videos))

    def _start_monitor(self) -> None:
        if not self._videos:
            self._set_hint(labels.MONITOR_EMPTY_ERROR)
            return
        worker = get_vision_worker()
        worker.ensure_started()
        reg = get_channel_video_registry()
        jobs = [{"job": cid, "video": path, "paused": reg.is_paused(cid)}
                for cid, path in self._videos.items()]
        worker.send({"cmd": "monitor", "jobs": jobs, "loop": True})
        self._monitoring = True
        self._mon_done = False
        self._sync_registry_monitor(True)
        self._set_controls(True)
        self._set_hint(labels.MONITOR_RUNNING_HINT.format(
            count=len(jobs), fps=config.MONITOR_FPS,
            size=config.MONITOR_INPUT_TEXT))
        self._poll.start()
        for cell in self._cells.values():
            cell.clear_monitor()
        for cid in self._videos:
            self._cells[cid].set_monitor(labels.CELL_MONITOR_OPENING)
        _log.info("silent monitor start: %d videos", len(jobs))

    def _stop_monitor(self) -> None:
        get_vision_worker().send({"cmd": "monitor_stop"})
        self._sync_registry_monitor(False)
        self._set_controls(False)
        self._set_hint(labels.MONITOR_IDLE_HINT)

    def _set_controls(self, running: bool) -> None:
        self._choose_btn.setEnabled(not running)
        self._load_btn.setEnabled(not running)
        self._start_btn.setEnabled(False)
        self._stop_btn.setEnabled(running)

    def _poll_tick(self) -> None:
        get_vision_worker().send({"cmd": "snapshot"})

    def _apply_snapshot(self, streams: list[dict], done: bool) -> None:
        by_job = {s["job"]: s for s in streams}
        for cid in self._videos:
            s = by_job.get(cid)
            if s is None:
                continue
            status = s.get("status")
            if status == "done":
                text = labels.CELL_MONITOR_DONE
            elif status == "error":
                text = labels.CELL_MONITOR_ERROR + " " + (s.get("error") or "")
            elif status == "opening":
                text = labels.CELL_MONITOR_OPENING
            elif status == "paused":   # 该路被暂停（电流页联动暂停时可见）
                n = sum(s.get("flashes", {}).values())
                text = labels.CELL_MONITOR_PAUSED.format(
                    n=n, loops=s.get("loops", 0))
            else:  # running / opened
                n = sum(s.get("flashes", {}).values())
                text = labels.CELL_MONITOR_LOOP_TEMPLATE.format(
                    n=n, loops=s.get("loops", 0))
            self._cells[cid].set_monitor(text)
        if done:
            self._finish_monitor()

    def _finish_monitor(self) -> None:
        self._monitoring = False
        self._mon_done = True
        self._poll.stop()
        self._sync_registry_monitor(False)
        self._set_controls(False)
        self._set_hint(labels.MONITOR_DONE)

    def _on_worker_event(self, payload: dict) -> None:
        if not self._monitoring:
            return
        ptype = payload.get("type")
        if ptype == "snapshot":
            self._apply_snapshot(payload.get("streams", []),
                                 bool(payload.get("done")))
        elif ptype == "error":
            self._set_hint(labels.MONITOR_POLLING_ERROR.format(
                msg=payload.get("message", "")))
        elif ptype == "monitor_finished":
            if not self._mon_done:
                # 未走正常 done 就结束 → 非循环/异常退出，明确提示避免误判
                self._set_hint(labels.MONITOR_ABNORMAL_FINISH)
            self._finish_monitor()

    # ------------------------------------------------------------ 会话/worker
    def shutdown_monitor(self) -> None:
        if self._monitoring or self._poll.isActive():
            self._poll.stop()
        get_vision_worker().send({"cmd": "monitor_stop"})
        self._sync_registry_monitor(False)
        for cell in self._cells.values():
            cell.clear_monitor()

    # ------------------------------------------------------------ 布局
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

        # 静默集中监控工具条
        mbar = QFrame(self)
        mbar.setObjectName("videoToolbar")
        ml = QHBoxLayout(mbar)
        ml.setContentsMargins(12, 6, 12, 6)
        ml.setSpacing(10)
        mstat = QLabel("")
        mstat.setObjectName("videoInfo")
        self._current_hint = mstat
        ml.addWidget(mstat, 1)
        self._load_btn = QPushButton(labels.MONITOR_LOAD_MANIFEST_BTN)
        self._load_btn.setObjectName("videoBtn")
        self._load_btn.clicked.connect(self._load_manifest)
        ml.addWidget(self._load_btn)
        self._choose_btn = QPushButton(labels.MONITOR_CHOOSE_BTN)
        self._choose_btn.setObjectName("videoBtn")
        self._choose_btn.clicked.connect(self._choose_videos)
        ml.addWidget(self._choose_btn)
        self._start_btn = QPushButton(labels.MONITOR_START_BTN)
        self._start_btn.setObjectName("videoBtnAccent")
        self._start_btn.setEnabled(False)
        self._start_btn.clicked.connect(self._start_monitor)
        ml.addWidget(self._start_btn)
        self._stop_btn = QPushButton(labels.MONITOR_STOP_BTN)
        self._stop_btn.setObjectName("videoBtn")
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._stop_monitor)
        ml.addWidget(self._stop_btn)
        outer.addWidget(mbar)

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
            cell.opened.connect(self._on_mark_opened)
            row = (cid - 1) // config.GRID_COLS
            col = (cid - 1) % config.GRID_COLS
            grid.addWidget(cell, row, col)
            self._cells[cid] = cell

        outer.addLayout(grid, 1)