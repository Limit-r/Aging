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
    QSizePolicy, QVBoxLayout, QWidget,
)

from app.core import config, labels
from app.core.tokens import DEFAULT_TOKENS
from app.observability import get_logger, narrative
from app.services.channel_video_registry import get_channel_video_registry
from app.ui.vision_worker import get_vision_worker
from app.ui.qss_utils import refresh_qss

_S = DEFAULT_TOKENS.sizing
PROJECT_ROOT = Path(__file__).resolve().parents[3]   # d:\Aging
_log = get_logger("app.ui.pages.video_page")


class VideoMarkCell(QFrame):
    """位点标记单元：CH-XX + 大圆点占位 + 双击提示 + 右上状态徽标。

    v3.1 视觉重设：
    - 圆角 12、上下深空渐变、描边色随 `status` 属性变化
    - 顶部 16pt 粗体 `CH-XX`，右上 8x8 圆点徽标
    - 中部 30pt 大圆点占位 + 9pt 次级色 `位点 X`
    - 监控中时显示紧凑数字摘要（替代占位字符）
    - hover 时整格变亮 + 边框霓虹青
    """
    opened = pyqtSignal(int)  # 双击 → 打开该通道视频流检测页
    # 单元状态：idle / opening / running / paused / error / done
    STATUSES = ("idle", "opening", "running", "paused", "error", "done")

    def __init__(self, cid: int, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.cell_id = cid
        self.setObjectName("videoCell")
        self.setProperty("status", "idle")
        self.setMinimumSize(_S.VIDEO_CELL_MIN_W, _S.VIDEO_CELL_MIN_H)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(labels.CELL_OPEN_HINT)
        self._build_ui()
        refresh_qss(self)

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(2)

        # 顶部：CH-XX（占左侧）+ 右上 8x8 圆点（占右侧）
        head = QHBoxLayout()
        head.setSpacing(6)
        header = QLabel(labels.CELL_HEADER_TEMPLATE.format(cid=self.cell_id))
        header.setObjectName("videoCellHeader")
        head.addWidget(header)
        head.addStretch(1)
        # 圆点徽标：固定 8x8、贴右上角
        self._dot = QLabel("", self)
        self._dot.setObjectName("videoCellDot")
        self._dot.setProperty("status", "idle")
        self._dot.setFixedSize(8, 8)
        head.addWidget(self._dot, 0, Qt.AlignTop | Qt.AlignRight)
        outer.addLayout(head)

        # 中部：占位大圆点字符（30pt 居中），监控中会被摘要覆盖
        self._mark = QLabel("●")
        self._mark.setObjectName("videoCellMark")
        self._mark.setAlignment(Qt.AlignCenter)
        outer.addWidget(self._mark, 1)

        # 监控中摘要 label（与 mark 同一位置覆盖显示；初始隐藏）
        self._monitor = QLabel("")
        self._monitor.setObjectName("videoCellMonitor")
        self._monitor.setAlignment(Qt.AlignCenter)
        self._monitor.setWordWrap(True)
        self._monitor.hide()
        outer.addWidget(self._monitor, 0)

        # 底部双击提示
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

    def set_status(self, status: str) -> None:
        """按 status 更新描边 + 圆点徽标。"""
        if status not in self.STATUSES:
            status = "idle"
        self.setProperty("status", status)
        self._dot.setProperty("status", status)
        refresh_qss(self)
        refresh_qss(self._dot)

    # ------------------------------------------------------------ 静默监控
    def set_monitor(self, text: str) -> None:
        """静默监控时在单元中显示聚合信息（覆盖默认占位字符）。"""
        self._mark.hide()
        self._monitor.setText(text)
        self._monitor.show()

    def clear_monitor(self) -> None:
        """退出/停止静默监控后恢复默认占位字符。"""
        self._monitor.hide()
        self._monitor.setText("")
        self._mark.show()


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
        self._poll.setInterval(1000)
        self._poll.timeout.connect(self._poll_tick)
        self._build_ui()
        self._set_hint(labels.MONITOR_IDLE_HINT)
        self._wire_worker()
        self._try_load_default_videos()
        self._poll.start()
        narrative.event(
            "video_overview_init",
            note="v3.0 视频总览：位点标记网格（双击进入视频流检测 / 54 路静默监控）")

    def showEvent(self, event) -> None:
        """首次显示：不再自动开静默监控。

        默认视频仅登记为「电流启动时自动拉起对应检测」的映射源（见
        `_try_load_default_videos`），是否检测由电流页「运行通道」驱动，
        而非无条件开一路监控。需要多路同时后台监控时可手动点「开始静默监控」。
        """
        super().showEvent(event)

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
        # 重置单元：清监控摘要 + 切到 opening 描边
        for cell in self._cells.values():
            cell.clear_monitor()
            cell.set_status("idle")
        for cid in self._videos:
            self._cells[cid].set_monitor(labels.CELL_MONITOR_OPENING)
            self._cells[cid].set_status("opening")
        _log.info("silent monitor start: %d videos", len(jobs))

    def _stop_monitor(self) -> None:
        get_vision_worker().send({"cmd": "monitor_stop"})
        self._sync_registry_monitor(False)
        self._set_controls(False)
        self._set_hint(labels.MONITOR_IDLE_HINT)
        # 复位单元状态 + KPI
        for cid in self._videos:
            cell = self._cells.get(cid)
            if cell is not None:
                cell.clear_monitor()
                cell.set_status("idle")
        self._update_kpi(running=0, paused=0, error=0, total=len(self._videos))

    def _set_controls(self, running: bool) -> None:
        # 已移除手动调控按钮：视频检测默认静默、跟随电流，无需页面启停开关。
        # 保留空实现以避免历史调用点报错。
        pass

    def _poll_tick(self) -> None:
        self._refresh_overview()

    def _refresh_overview(self) -> None:
        """按「电流运行集合」+「视频映射」刷新总览格状态，明确提示哪台设备在运行。

        视频检测由电流驱动：电流运行且该通道有视频源 →「运行中」；有源但电流未
        运行 →「待机」；无视频源 →「无源」。KPI 的 running 即「正在检测的设备数」。
        """
        reg = get_channel_video_registry()
        running = standby = source = 0
        for cid in range(1, self._total + 1):
            cell = self._cells.get(cid)
            if cell is None:
                continue
            has = reg.path(cid) is not None
            in_run = cid in reg.current_running_cids()
            if in_run and has:
                cell.set_monitor(labels.VIDEO_CELL_STATE_RUNNING)
                cell.set_status("running")
                running += 1
            elif has:
                cell.set_monitor(labels.VIDEO_CELL_STANDBY)
                cell.set_status("idle")
                standby += 1
            else:
                cell.set_monitor(labels.VIDEO_CELL_NO_SOURCE)
                cell.set_status("idle")
            if has:
                source += 1
        self._update_kpi(running=running, paused=0, error=0, total=self._total)

    def _apply_snapshot(self, streams: list[dict], done: bool) -> None:
        # KPI 统计累计
        running = paused = error = 0
        by_job = {s["job"]: s for s in streams}
        for cid in self._videos:
            s = by_job.get(cid)
            if s is None:
                continue
            status = s.get("status")
            if status == "done":
                text = labels.CELL_MONITOR_DONE
                self._cells[cid].set_status("done")
            elif status == "error":
                text = labels.CELL_MONITOR_ERROR + " " + (s.get("error") or "")
                self._cells[cid].set_status("error")
                error += 1
            elif status == "opening":
                text = labels.CELL_MONITOR_OPENING
                self._cells[cid].set_status("opening")
            elif status == "paused":   # 该路被暂停（电流页联动暂停时可见）
                n = sum(s.get("flashes", {}).values())
                text = labels.CELL_MONITOR_PAUSED.format(
                    n=n, loops=s.get("loops", 0))
                self._cells[cid].set_status("paused")
                paused += 1
            else:  # running / opened
                n = sum(s.get("flashes", {}).values())
                text = labels.CELL_MONITOR_LOOP_TEMPLATE.format(
                    n=n, loops=s.get("loops", 0))
                self._cells[cid].set_status("running")
                running += 1
            self._cells[cid].set_monitor(text)
        # 刷新 KPI 卡片
        self._update_kpi(running=running, paused=paused,
                         error=error, total=len(self._videos))
        if done:
            self._finish_monitor()

    def _finish_monitor(self) -> None:
        self._monitoring = False
        self._mon_done = True
        self._poll.stop()
        self._sync_registry_monitor(False)
        self._set_controls(False)
        self._set_hint(labels.MONITOR_DONE)
        # 复位单元状态 + KPI
        for cid in self._videos:
            cell = self._cells.get(cid)
            if cell is not None:
                cell.clear_monitor()
                cell.set_status("idle")
        self._update_kpi(running=0, paused=0, error=0, total=len(self._videos))

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
            cell.set_status("idle")

    # ------------------------------------------------------------ KPI 卡片
    def _build_kpi(self, kind: str, title: str, value: int) -> QFrame:
        """单张 KPI 玻璃卡片：标题 + 数字 + 单位。"""
        card = QFrame()
        card.setObjectName("kpiCard")
        card.setProperty("kind", kind)
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        lay = QHBoxLayout(card)
        lay.setContentsMargins(14, 8, 14, 8)
        lay.setSpacing(10)
        # 左：标题（垂直堆叠 title / value+unit）
        text_col = QVBoxLayout()
        text_col.setSpacing(0)
        title_lbl = QLabel(title)
        title_lbl.setObjectName("kpiTitle")
        text_col.addWidget(title_lbl)
        val_row = QHBoxLayout()
        val_row.setSpacing(4)
        val_lbl = QLabel(str(value))
        val_lbl.setObjectName("kpiValue")
        val_lbl.setProperty("kind", kind)
        unit_lbl = QLabel(labels.KPI_UNIT)
        unit_lbl.setObjectName("kpiUnit")
        val_row.addWidget(val_lbl)
        val_row.addWidget(unit_lbl)
        val_row.addStretch(1)
        text_col.addLayout(val_row)
        lay.addLayout(text_col, 1)
        return card, val_lbl

    def _build_kpi_row(self) -> tuple[QFrame, dict[str, QLabel]]:
        """构建 4 张 KPI 卡片行，返回 (容器, {kind: value_label})。"""
        row = QFrame()
        row.setObjectName("kpiRow")
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(10)
        kinds = (
            ("running", labels.KPI_TITLE_RUNNING, 0),
            ("paused", labels.KPI_TITLE_PAUSED, 0),
            ("error", labels.KPI_TITLE_ERROR, 0),
            ("total", labels.KPI_TITLE_TOTAL, self._total),
        )
        val_labels: dict[str, QLabel] = {}
        for kind, title, init in kinds:
            card, val = self._build_kpi(kind, title, init)
            rl.addWidget(card, 1)
            val_labels[kind] = val
        return row, val_labels

    def _update_kpi(self, *, running: int, paused: int, error: int, total: int) -> None:
        """刷新 KPI 数字。"""
        if not hasattr(self, "_kpi_vals"):
            return
        self._kpi_vals["running"].setText(str(running))
        self._kpi_vals["paused"].setText(str(paused))
        self._kpi_vals["error"].setText(str(error))
        self._kpi_vals["total"].setText(str(total))

    # ------------------------------------------------------------ 布局
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # 顶部信息条：主标题（霓虹青粗体）+ 副标题（次级色小号）
        bar = QFrame(self)
        bar.setObjectName("videoToolbar")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(14, 0, 14, 0)
        bl.setSpacing(12)
        title = QLabel(labels.VIDEO_OVERVIEW_TITLE)
        title.setObjectName("videoTitle")
        bl.addWidget(title)
        subtitle = QLabel(labels.VIDEO_OVERVIEW_SUBTITLE_TEMPLATE.format(
            rows=config.GRID_ROWS, cols=config.GRID_COLS,
            total=self._total))
        subtitle.setObjectName("videoTitleSub")
        bl.addWidget(subtitle)
        bl.addStretch(1)
        # 提示行：右上角小字 hint
        hint = QLabel(labels.VIDEO_OVERVIEW_HINT)
        hint.setObjectName("videoHint")
        bl.addWidget(hint)
        outer.addWidget(bar)

        # KPI 摘要行：4 张玻璃卡片
        kpi_row, kpi_vals = self._build_kpi_row()
        outer.addWidget(kpi_row)
        self._kpi_vals = kpi_vals
        # 默认初始 KPI：仅总计
        self._update_kpi(running=0, paused=0, error=0, total=self._total)

        # 状态行：只读提示。视频检测「默认静默、跟随电流」，由电流页启动/停止
        # 对应通道自动调控，本页不再提供手动启停按钮。
        sbar = QFrame(self)
        sbar.setObjectName("videoToolbar")
        sl = QHBoxLayout(sbar)
        sl.setContentsMargins(14, 6, 14, 6)
        mstat = QLabel(labels.MONITOR_IDLE_HINT)
        mstat.setObjectName("videoInfo")
        self._current_hint = mstat
        sl.addWidget(mstat, 0)
        sl.addStretch(1)
        outer.addWidget(sbar)

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