"""数据中心页（Phase 6）。

三个页签：
- 历史 / 趋势 / 导出（后续实现）
- 数据标注（Phase B 接入画框标注器）
- 训练 / 转换（后续实现）

懒加载约束：本页顶部**不** import ml，
保证 Main.py 启动不加载 torch / opencv / openvino 等重型依赖；
数据标注 / 训练能力在后续阶段按需加载。
"""

import datetime
import os
import re
import sys

from PyQt5.QtCore import QProcess, QProcessEnvironment, Qt, QThread, QTimer, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QColor, QTextCharFormat, QTextCursor
from PyQt5.QtWidgets import (
    QButtonGroup, QComboBox, QDialog, QFileDialog, QFrame,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMenu, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QSpinBox, QSplitter, QStackedWidget, QToolButton, QVBoxLayout, QWidget,
)

from app.core import config, labels
from app.core.tokens import DEFAULT_TOKENS
from app.observability import narrative

# 训练页 · 运行期正则（进度 / 指标解析，见 _parse_train_output）
_RE_YOLO_EPOCH = re.compile(r"Epoch:(\d+)/(\d+)")
_RE_CLS_EPOCH = re.compile(r"\bepoch\s+(\d+)/(\d+)")
_RE_METRICS = re.compile(r"Precision=([\d.]+), Recall=([\d.]+), F1-Score=([\d.]+)")
_RE_MAP_IMPROVE = re.compile(r"mAP improved from [\d.]+ to ([\d.]+)")
_RE_GPU_COUNT = re.compile(r"Gpu Device Count : (\d+)")
# ANSI 颜色转义（训练脚本输出 \033[1;32m 等，GUI 显示前剥离）
_RE_ANSI = re.compile(r"\x1b\[[0-9;]*m")

# 训练页 · 时间换算常量（避免 3600 / 60 数字字面量）
_SEC_PER_HOUR = 3600
_SEC_PER_MIN = 60

# 仓库根（data_page.py -> app/ui/pages -> 4 级 dirname）
_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


# 标注页类别：Phase A 后改为从类别注册表派生，不再硬编码
# 见 _category_names()（懒加载，保持启动不 import ml）

# 标注工具模式（与 ml.annotation_widget 的模式值保持一致）
_ANNOT_MODE_CREATE = "create"
_ANNOT_MODE_EDIT = "edit"


class DataCenterPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("dataCenterPage")
        self._s = DEFAULT_TOKENS.sizing
        self._tab_group: QButtonGroup
        # 懒加载导入的图片条目（ImageEntry 列表），由 _lazy_annotation_io() 提供类型
        self._entries = []
        self._all_entries = []         # 未筛选的完整图片列表（筛选用主列表）
        # 标注页需要但不随 UI 构建期初始化的引用
        self._image_list: QListWidget
        self._object_list: QListWidget
        self._canvas_hint: QLabel
        self._canvas_corner_lb: QLabel
        self._footer_count: QLabel
        self._canvas = None            # AnnotationCanvas（懒加载）
        self._current_entry = None     # 当前选中 ImageEntry
        self._xml_dir = None           # 当前导入的 XML 目录
        self._current_series = ""      # 当前标注图片所属系列（决定显示的类别）
        self._skip_item_change = False  # 未保存提示取消时回退选中，避免递归
        self._tool_draw_btn = None     # 「绘制」工具按钮（_build_category_bar 中创建）
        # 训练子进程（QProcess，信号驱动异步读日志，不阻塞事件循环）
        self._proc: QProcess = None
        self._pending_cmds = []
        self._proc_buf = ""            # stdout 未读完整的残行
        self._train_ts0 = 0.0
        # 训练页 · 深度优化状态（进度 / 指标 / 阶段 / 日志持久化 / 设备检测）
        self._train_cur_stage = None   # 当前阶段 key（DATA/YOLO/ROI/CLS）
        self._train_stage_t0 = 0.0     # 当前阶段开始时间
        self._train_epoch_cur = 0
        self._train_epoch_total = 0
        self._train_metrics = None     # (mAP, P, R, F1)
        self._train_progress = 0
        self._train_log_path = None    # 本轮训练日志持久化文件
        self._train_log_fh = None      # 文件句柄
        self._train_elapsed_timer = None
        self._stop_requested = False   # 用户确认停止标记
        self._dev_proc: QProcess = None  # 设备检测子进程
        self._dev_info = None          # 最近一次环境探测结果（ml.auto_params.EnvInfo）
        self._train_pending_cb = None  # 环境探测完成后的回调
        self._pending_run = None       # 等待探测完成后启动的阶段列表
        self._last_rec = None          # 最近一次自动推荐结果（供日志备注复用）
        self._build_ui()

    # -- UI 构建 -------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(
            self._s.DATA_PAGE_MARGIN,
            self._s.DATA_PAGE_MARGIN,
            self._s.DATA_PAGE_MARGIN,
            self._s.DATA_PAGE_MARGIN,
        )
        root.setSpacing(self._s.DATA_PAGE_SPACING)
        root.addWidget(self._build_header())
        # 先建 stack（自绘页签需要切换它），再建 tabs bar
        self._stack = QStackedWidget()
        self._stack.setObjectName("dataStack")
        self._stack.addWidget(self._build_history_page())
        self._stack.addWidget(self._build_annotate_page())
        self._stack.addWidget(self._build_train_page())
        root.addWidget(self._build_tabs_bar())
        root.addWidget(self._stack, 1)
        # 启动后自动探测环境 + 刷新数据集概览（不点按钮，进来即显示）
        QTimer.singleShot(0, self._auto_probe_on_startup)

    def _auto_probe_on_startup(self) -> None:
        """启动时自动评估环境与数据集概览。
        注：用 QTimer.singleShot(0) 延后到事件循环，让首帧先渲染完。"""
        try:
            self._detect_device()
        except Exception:
            pass
        try:
            self._refresh_dataset_overview()
        except Exception:
            pass

    # -- 顶栏：徽章 + 标题 + 副标题 + 状态 -------------------------------------
    def _build_header(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("dataHeader")
        bar.setFixedHeight(self._s.DATA_HEADER_H)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(
            self._s.DATA_HEADER_PAD_L, 0,
            self._s.DATA_HEADER_PAD_R, 0,
        )
        lay.setSpacing(self._s.DATA_HEADER_GAP)
        lay.setAlignment(Qt.AlignVCenter)

        badge = QLabel("DC")
        badge.setObjectName("dataHeaderBadge")
        badge.setAlignment(Qt.AlignCenter)
        badge.setMinimumWidth(self._s.DATA_HEADER_BADGE_MIN_W)
        badge.setMaximumWidth(self._s.DATA_HEADER_BADGE_MAX_W)
        lay.addWidget(badge)

        title_col = QVBoxLayout()
        title_col.setSpacing(0)
        title = QLabel(labels.DATA_CENTER_TITLE)
        title.setObjectName("dataHeaderTitle")
        subtitle = QLabel(labels.DATA_CENTER_SUBTITLE)
        subtitle.setObjectName("dataHeaderSubtitle")
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        title_wrap = QWidget()
        title_wrap.setObjectName("dataHeaderTitleWrap")
        title_wrap.setLayout(title_col)
        lay.addWidget(title_wrap)
        lay.addStretch(1)

        status = QLabel("● ACTIVE")
        status.setObjectName("dataHeaderStatus")
        lay.addWidget(status)
        return bar

    # -- 自绘页签栏（QPushButton + ButtonGroup 实现可点击切换） -----------------
    def _build_tabs_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("dataTabsBar")
        bar.setFixedHeight(self._s.DATA_TABS_H)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(
            self._s.DATA_TABS_PAD_L, 0,
            self._s.DATA_TABS_PAD_R, 0,
        )
        lay.setSpacing(self._s.DATA_TABS_GAP)
        lay.setAlignment(Qt.AlignVCenter)

        self._tab_group = QButtonGroup(self)
        self._tab_group.setExclusive(True)
        tabs = (
            (labels.DATA_TAB_HISTORY, 0),
            (labels.DATA_TAB_ANNOTATE, 1),
            (labels.DATA_TAB_TRAIN, 2),
        )
        for text, idx in tabs:
            btn = QPushButton(text)
            btn.setObjectName("dataTab")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _checked=False, i=idx: self._stack.setCurrentIndex(i))
            self._tab_group.addButton(btn, idx)
            lay.addWidget(btn)
        lay.addStretch(1)
        # 默认选中"数据标注"页
        self._tab_group.button(1).setChecked(True)
        self._stack.setCurrentIndex(1)
        return bar

    # -- 三个页内容 -----------------------------------------------------------
    def _build_history_page(self) -> QWidget:
        return self._build_placeholder_page(labels.DATA_TAB_HISTORY, labels.DATA_HISTORY_PLACEHOLDER)

    # -- 训练 / 转换页 ----------------------------------------------------------
    def _build_train_page(self) -> QWidget:
        """统一 9 类模型：训练控制区（状态/参数/启动合一）+ 日志回显。"""
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, self._s.DATA_PAGE_SPACING, 0, 0)
        lay.setSpacing(self._s.DATA_PAGE_SPACING)

        overview = QLabel(labels.TRAIN_TAB_OVERVIEW)
        overview.setObjectName("dcTrainOverview")
        lay.addWidget(overview)

        lay.addWidget(self._build_train_control_section(), 0)
        lay.addWidget(self._build_train_log_section(), 1)
        return page

    def _build_train_control_section(self) -> QFrame:
        """训练控制区（合并：状态 / 自动推荐 / 环境&数据&续训 / 启动）。
        原 3 个分段已合并为同一卡片，自上而下：状态条 → 进度 → 推荐 → 环境行 → 续训行 → 主操作 → 提示。"""
        sec = QFrame()
        sec.setObjectName("dcTrainStatusSection")
        v = QVBoxLayout(sec)
        v.setContentsMargins(self._s.TRAIN_CARD_PAD_X, self._s.TRAIN_CARD_PAD_Y,
                             self._s.TRAIN_CARD_PAD_X, self._s.TRAIN_CARD_PAD_Y)
        v.setSpacing(self._s.TRAIN_STATUS_GAP)

        # ① 状态条：阶段 + 指标（一行）
        status_row = QHBoxLayout()
        status_row.setSpacing(self._s.TRAIN_STATUS_GAP)
        self._train_stage_lb = QLabel(labels.TRAIN_STATUS_STAGE.format(
            stage=labels.TRAIN_STAGE_IDLE))
        self._train_stage_lb.setObjectName("dcTrainStageLabel")
        status_row.addWidget(self._train_stage_lb)
        status_row.addStretch(1)
        self._train_metrics_lb = QLabel(labels.TRAIN_METRICS_EMPTY)
        self._train_metrics_lb.setObjectName("dcTrainMetricsLabel")
        status_row.addWidget(self._train_metrics_lb)
        v.addLayout(status_row)

        # ② 进度条 + ETA 状态行（紧贴进度条上方一行）
        self._train_status_lb = QLabel(labels.TRAIN_STATUS_ETA_IDLE)
        self._train_status_lb.setObjectName("dcTrainStatusLabel")
        v.addWidget(self._train_status_lb)
        self._train_progress_bar = QProgressBar()
        self._train_progress_bar.setObjectName("dcTrainProgress")
        self._train_progress_bar.setFixedHeight(self._s.TRAIN_PROGRESS_H)
        self._train_progress_bar.setValue(0)
        v.addWidget(self._train_progress_bar)
        self._train_elapsed_timer = QTimer(self)
        self._train_elapsed_timer.setInterval(config.TRAIN_ELAPSED_TICK_MS)
        self._train_elapsed_timer.timeout.connect(self._on_train_tick)

        # ③ 信息汇总：设备 + 数据集 + 推荐（合并为一行，仅文本，无按钮）
        self._train_dev_lb = QLabel(labels.TRAIN_DEVICE_EMPTY)
        self._train_dev_lb.setObjectName("dcTrainStatusLabel")
        self._train_ds_lb = QLabel(labels.TRAIN_DATASET_LABEL + "  " + labels.TRAIN_DATASET_EMPTY)
        self._train_ds_lb.setObjectName("dcTrainStatusLabel")
        self._train_auto_summary = QLabel(labels.TRAIN_AUTO_WAIT)
        self._train_auto_summary.setObjectName("dcTrainStatusLabel")
        self._train_auto_summary.setWordWrap(True)
        info_row = QHBoxLayout()
        info_row.setSpacing(self._s.TRAIN_PARAM_GAP)
        info_row.addWidget(self._train_dev_lb, 1)
        info_row.addSpacing(self._s.TRAIN_PARAM_GAP)
        info_row.addWidget(self._train_ds_lb, 1)
        info_row.addSpacing(self._s.TRAIN_PARAM_GAP)
        info_row.addWidget(self._train_auto_summary, 1)
        v.addLayout(info_row)

        # ④ 主操作：高级·单步 + 一键完整流程 + 停止
        action_row = QHBoxLayout()
        action_row.setSpacing(self._s.TRAIN_PARAM_GAP)
        advanced = QToolButton()
        advanced.setObjectName("dcGhostBtn")
        advanced.setText(labels.TRAIN_BTN_ADVANCED)
        advanced.setFixedWidth(self._s.TRAIN_MENU_ADV_W)
        advanced.setPopupMode(QToolButton.InstantPopup)
        adv_menu = QMenu(advanced)
        for text, fn in (
            (labels.TRAIN_BTN_GENDATA, lambda: self._train_run(["DATA"])),
            (labels.TRAIN_BTN_TRAIN_YOLO, lambda: self._train_run(["YOLO"])),
            (labels.TRAIN_BTN_MERGE_ROI, lambda: self._train_run(["ROI"])),
            (labels.TRAIN_BTN_TRAIN_CLS, lambda: self._train_run(["CLS"])),
        ):
            act = adv_menu.addAction(text)
            act.triggered.connect(fn)
        advanced.setMenu(adv_menu)
        action_row.addWidget(advanced)
        action_row.addStretch(1)
        self._train_oneclick = QPushButton(labels.TRAIN_BTN_ONECLICK)
        self._train_oneclick.setObjectName("dcPrimaryBtn")
        self._train_oneclick.clicked.connect(self._train_run_all)
        action_row.addWidget(self._train_oneclick)
        self._train_stop_btn = QPushButton(labels.TRAIN_BTN_STOP)
        self._train_stop_btn.setObjectName("dcGhostBtn")
        # 注：方法 _train_stop_handler 避免与按钮 self._train_stop_btn 同名歧义
        self._train_stop_btn.clicked.connect(self._train_stop_handler)
        self._train_stop_btn.setEnabled(False)
        action_row.addWidget(self._train_stop_btn)
        v.addLayout(action_row)

        # ⑥ 提示（仅运行期显示；空闲时不渲染，避免占空）
        self._train_hint = QLabel("")
        self._train_hint.setObjectName("dcTrainHint")
        self._train_hint.setVisible(False)
        v.addWidget(self._train_hint)

        return sec

    def _build_train_log_section(self) -> QFrame:
        """日志回显分段。"""
        sec = QFrame()
        sec.setObjectName("dcTrainSection")
        v = QVBoxLayout(sec)
        v.setContentsMargins(self._s.TRAIN_CARD_PAD_X, self._s.TRAIN_CARD_PAD_Y,
                             self._s.TRAIN_CARD_PAD_X, self._s.TRAIN_CARD_PAD_Y)
        v.setSpacing(self._s.DATA_PAGE_SPACING)

        title = QLabel(labels.TRAIN_SECTION_LOG)
        title.setObjectName("dcTrainSectionTitle")
        v.addWidget(title)

        self._train_log = QPlainTextEdit()
        self._train_log.setObjectName("dcTrainLog")
        self._train_log.setReadOnly(True)
        self._train_log.setMinimumHeight(self._s.TRAIN_LOG_MIN_H)
        v.addWidget(self._train_log)
        return sec

    # ---- 训练子进程：worker / 触发 / 停止 -----------------------------------
    def _train_params(self) -> dict:
        """返回最终生效的超参数：始终由系统自动推荐（phi 固定为 n）。"""
        rec = self._recommended_params()
        self._last_rec = rec           # 供日志备注复用，避免重复统计
        return {
            "phi": rec.phi,            # 固定为 "n"
            "yolo_epochs": rec.yolo_epochs,
            "yolo_batch": rec.yolo_batch,
            "yolo_lr": rec.yolo_lr,
            "cls_epochs": rec.cls_epochs,
            "cls_batch": rec.cls_batch,
            "cls_lr": rec.cls_lr,
        }

    def _recommended_params(self):
        """自动推荐：结合最近一次环境探测（未探测则按保守默认）与当前数据集。"""
        from ml.train import auto_params
        env = self._dev_info or auto_params.EnvInfo()
        ds = auto_params.dataset_stats()
        return auto_params.recommend(env, ds)

    def _train_run_all(self) -> None:
        """一键完整流程：DATA → YOLO → ROI → CLS 串行。"""
        self._train_run(["DATA", "YOLO", "ROI", "CLS"])

    def _train_run(self, stages) -> None:
        """启动一串训练阶段；自动模式下若尚未探测环境，先探测再启动。

        训练前对首个阶段做数据集前置校验，数据不可用时阻断并提示，避免跑空失败。
        """
        if self._proc is not None and self._proc.state() != QProcess.NotRunning:
            return
        if self._dev_proc is not None and self._dev_proc.state() != QProcess.NotRunning:
            return  # 环境探测进行中，等待完成回调后自动启动
        if not self._train_precheck(stages):
            return
        if self._dev_info is None:
            self._pending_run = list(stages)
            self._set_hint(labels.TRAIN_AUTO_PROBING)
            self._detect_device(self._start_pending_run)
            return
        self._start_run(stages)

    def _train_precheck(self, stages) -> bool:
        """数据集前置校验：YOLO/CLS/一键需数据可用，DATA 阶段跳过。

        返回 False 时已阻断（弹框 + 写日志），调用方不再启动。
        """
        first = stages[0] if stages else ""
        from ml.train import auto_params
        kind = "DATA" if first == "DATA" else "CLS" if first == "CLS" \
            else "ONECLICK" if len(stages) > 1 else "YOLO"
        ok, reason = auto_params.validate_for_training(kind)
        if ok:
            return True
        self._append_log(labels.TRAIN_PRECHECK_BLOCKED.format(
            reason=reason), color=DEFAULT_TOKENS.colors.TEXT_DANGER)
        narrative.event(
            "train_precheck_blocked", reason=reason, stages=",".join(stages),
            note="训练前校验未通过，已阻止启动",
        )
        box = QMessageBox(self)
        box.setWindowTitle(labels.TRAIN_PRECHECK_TITLE)
        box.setText(reason)
        box.setIcon(QMessageBox.Warning)
        box.addButton(labels.ANNOT_OK_BTN, QMessageBox.AcceptRole)
        box.exec_()
        return False

    def _start_pending_run(self) -> None:
        stages = self._pending_run or []
        self._pending_run = None
        if stages:
            self._start_run(stages)

    def _start_run(self, stages) -> None:
        """真正启动训练：打开日志、置状态、串行派发。"""
        self._pending_cmds = list(stages)
        self._proc = None
        self._proc_buf = ""
        self._train_ts0 = self._time_now()
        self._stop_requested = False
        self._open_train_log()
        narrative.event(
            "train_run_start",
            stages=",".join(stages),
            log_file=self._train_log_path or "none",
            note="训练流程启动（自动参数已分配）",
        )

        if self._pending_cmds:
            self._train_oneclick.setEnabled(False)
            self._train_stop_btn.setEnabled(True)
            self._set_hint(labels.TRAIN_HINT_RUNNING, running=True)
            self._spawn_next_cmd()

    def _time_now(self) -> float:
        import time
        return time.time()

    def _spawn_next_cmd(self) -> None:
        if not self._pending_cmds:
            self._on_all_done()
            return
        stage = self._pending_cmds[0]
        p = self._train_params()
        if stage in ("YOLO", "CLS"):
            # 自动分配说明写入日志（可读性优先，见 labels.TRAIN_AUTO_*）
            self._append_log(self._auto_notes_text(),
                             color=DEFAULT_TOKENS.colors.TEXT_DIM)
        if stage == "YOLO":
            params = {"epochs": p["yolo_epochs"], "batch": p["yolo_batch"],
                      "lr": p["yolo_lr"], "phi": p["phi"]}
        elif stage == "CLS":
            params = {"epochs": p["cls_epochs"], "batch": p["cls_batch"],
                      "lr": p["cls_lr"]}
        else:
            params = {}

        # 阶段级状态初始化（进度 / 指标 / 计时）
        self._train_cur_stage = stage
        self._train_stage_t0 = self._time_now()
        self._train_epoch_cur = 0
        self._train_epoch_total = 0
        self._train_metrics = None
        self._train_progress = 0
        self._train_progress_bar.setValue(0)
        self._train_stage_lb.setText(labels.TRAIN_STATUS_STAGE.format(
            stage=labels.TRAIN_STAGE_NAMES.get(stage, stage)))
        self._train_metrics_lb.setText(labels.TRAIN_METRICS_EMPTY)
        if self._train_elapsed_timer is not None:
            self._train_elapsed_timer.start()

        from ml.train import training_runner
        from ml.train.training_runner import build_cmd
        cmd = build_cmd(stage, params)
        self._append_log(labels.TRAIN_STARTING.format(cmd=" ".join(map(str, cmd))),
                         color=DEFAULT_TOKENS.colors.TEXT_NEON_CYAN)
        narrative.event(
            "train_stage_start", stage=stage,
            cmd=" ".join(map(str, cmd)),
            note="开始执行训练阶段",
        )

        proc = QProcess(self)
        proc.setWorkingDirectory(training_runner.PROJECT_ROOT)
        proc.setProcessChannelMode(QProcess.MergedChannels)  # stderr 并入 stdout，防死锁
        penv = QProcessEnvironment.systemEnvironment()
        penv.insert("PYTHONIOENCODING", "utf-8")   # 子进程统一 utf-8 输出，避免 GBK 乱码
        penv.insert("PYTHONUNBUFFERED", "1")
        proc.setProcessEnvironment(penv)
        proc.readyReadStandardOutput.connect(self._on_proc_out)
        proc.finished.connect(self._on_proc_finished)
        proc.errorOccurred.connect(self._on_proc_error)
        self._proc = proc
        self._proc_buf = ""
        proc.start(cmd[0], cmd[1:])

    def _on_proc_out(self) -> None:
        """QProcess 输出就绪：逐行解析进度/指标并着色回显（合并通道读 stdout）。"""
        if self._proc is None:
            return
        raw = self._proc.readAllStandardOutput()
        data = bytes(raw).decode("utf-8", errors="replace")
        data = self._proc_buf + data
        lines = data.split("\n")
        self._proc_buf = lines.pop()          # 保留未读完整的残行
        for ln in lines:
            ln = _RE_ANSI.sub("", ln).rstrip("\r")
            if not ln:
                continue
            color = self._parse_train_output(ln)
            self._append_log(ln, color=color)

    def _parse_train_output(self, line: str):
        """解析一行训练输出：更新进度/指标，返回着色 hex（None=默认色）。"""
        c = DEFAULT_TOKENS.colors
        low = line.lower()
        if line.startswith("==") or line.startswith("──"):
            return c.TEXT_NEON_CYAN
        if re.search(r"error|traceback|failed|out of memory", low):
            return c.TEXT_DANGER
        m = _RE_YOLO_EPOCH.search(line)
        if m:
            self._train_epoch_cur = int(m.group(1))
            self._train_epoch_total = int(m.group(2))
            if self._train_epoch_total > 0:
                self._train_progress = int(round(
                    self._train_epoch_cur * config.TRAIN_PROGRESS_PCT / self._train_epoch_total))
                self._train_progress_bar.setValue(self._train_progress)
            return c.TEXT_NEON_GREEN
        m = _RE_CLS_EPOCH.search(line)
        if m:
            self._train_epoch_cur = int(m.group(1))
            self._train_epoch_total = int(m.group(2))
            if self._train_epoch_total > 0:
                self._train_progress = int(round(
                    self._train_epoch_cur * config.TRAIN_PROGRESS_PCT / self._train_epoch_total))
                self._train_progress_bar.setValue(self._train_progress)
            return c.TEXT_NEON_GREEN
        m = _RE_METRICS.search(line)
        if m:
            mAP = self._train_metrics[0] if self._train_metrics else 0.0
            self._train_metrics = (mAP, float(m.group(1)), float(m.group(2)),
                                   float(m.group(3)))
            self._update_metrics_label()
            return c.TEXT_NEON_GREEN
        m = _RE_MAP_IMPROVE.search(line)
        if m:
            prev = self._train_metrics or (0.0, 0.0, 0.0, 0.0)
            self._train_metrics = (float(m.group(1)), prev[1], prev[2], prev[3])
            self._update_metrics_label()
            return c.TEXT_NEON_GREEN
        return None

    def _update_metrics_label(self) -> None:
        if self._train_metrics is None:
            self._train_metrics_lb.setText(labels.TRAIN_METRICS_EMPTY)
            return
        m, p, r, f = self._train_metrics
        self._train_metrics_lb.setText(labels.TRAIN_METRICS.format(
            m=round(m, 3), p=round(p, 3), r=round(r, 3), f=round(f, 3)))

    def _on_train_tick(self) -> None:
        """每秒刷新运行耗时与 ETA（仅训练运行期间）。"""
        if self._proc is None:
            return
        elapsed = self._time_now() - self._train_ts0
        if self._train_epoch_total > 0 and self._train_epoch_cur > 0:
            per_epoch = (self._time_now() - self._train_stage_t0) / self._train_epoch_cur
            eta = (self._train_epoch_total - self._train_epoch_cur) * per_epoch
            self._train_status_lb.setText(labels.TRAIN_STATUS_EPOCH.format(
                cur=self._train_epoch_cur, total=self._train_epoch_total,
                elapsed=self._fmt_dur(elapsed), eta=self._fmt_dur(eta)))
        else:
            self._train_status_lb.setText(labels.TRAIN_STATUS_BUSY.format(
                elapsed=self._fmt_dur(elapsed)))

    @staticmethod
    def _fmt_dur(sec: float) -> str:
        """秒 → 'h/m/s' 可读时长（ETA 与耗时展示）。"""
        sec = int(max(sec, 0))
        h, rem = divmod(sec, _SEC_PER_HOUR)
        m, s = divmod(rem, _SEC_PER_MIN)
        if h:
            return "%dh%02dm" % (h, m)
        if m:
            return "%dm%02ds" % (m, s)
        return "%ds" % s

    def _open_train_log(self) -> None:
        """为本轮训练创建持久化日志文件（OSError 则静默降级为仅 UI 回显）。"""
        try:
            os.makedirs(os.path.join(_PROJECT_ROOT, config.LOG_DIR), exist_ok=True)
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            path = os.path.join(_PROJECT_ROOT, config.LOG_DIR, "train_%s.log" % ts)
            self._train_log_path = path
            self._train_log_fh = open(path, "w", encoding="utf-8")
            narrative.event(
                "train_log_open", path=path,
                note="本轮训练日志文件已创建",
            )
            self._append_log(labels.TRAIN_LOG_FILE_OPENED.format(path=path),
                             color=DEFAULT_TOKENS.colors.TEXT_DIM)
        except OSError:
            self._train_log_path = None
            self._train_log_fh = None

    def _train_log_write(self, text: str) -> None:
        if self._train_log_fh is not None:
            try:
                ts = datetime.datetime.now().strftime("%H:%M:%S")
                self._train_log_fh.write("[%s] %s\n" % (ts, str(text)))
                self._train_log_fh.flush()
            except OSError:
                pass

    def _on_proc_finished(self, exit_code: int, exit_status: int) -> None:
        """子进程结束：记录阶段耗时，驱动下一阶段或结束流程。"""
        if self._proc is None:
            return
        if self._proc_buf:
            self._append_log(self._proc_buf)
            self._proc_buf = ""
        rc = int(exit_code)
        stage = self._train_cur_stage
        if not self._pending_cmds:            # 手动停止时可能已清空
            if self._stop_requested:
                self._set_hint(labels.TRAIN_HINT_STOPPED)
            self._stop_requested = False
            self._on_run_finished()
            return
        self._pending_cmds.pop(0)
        if rc != 0:
            self._append_log(labels.TRAIN_STAGE_FAILED.format(
                stage=labels.TRAIN_STAGE_NAMES.get(stage, stage)),
                color=DEFAULT_TOKENS.colors.TEXT_DANGER)
            narrative.event(
                "train_stage_failed", stage=stage, exit=rc,
                note="训练阶段失败（非零退出码）",
            )
            self._set_hint(labels.TRAIN_FAILED.format(reason="exit=%d" % rc), fail=True)
            self._on_run_finished()
            return
        if stage == "DATA":
            self._refresh_dataset_overview()   # 数据生成后即时刷新概览
        if stage is not None:
            sec = int(self._time_now() - self._train_stage_t0)
            self._append_log(labels.TRAIN_STAGE_DONE_TEMPLATE.format(
                stage=labels.TRAIN_STAGE_NAMES.get(stage, stage), sec=sec),
                color=DEFAULT_TOKENS.colors.TEXT_NEON_GREEN)
            narrative.event(
                "train_stage_done", stage=stage, sec=sec,
                note="训练阶段完成",
            )
        if self._pending_cmds:
            self._spawn_next_cmd()
        else:
            self._on_all_done()

    def _on_proc_error(self, err: int) -> None:
        if self._proc is None:
            return
        self._set_hint(labels.TRAIN_FAILED.format(reason="proc_err=%d" % int(err)), fail=True)

    def _on_all_done(self) -> None:
        el = self._time_now() - self._train_ts0
        self._append_log(labels.TRAIN_DONE.format(sec=int(el)))
        narrative.event(
            "train_run_done", sec=int(el),
            note="全部训练阶段完成",
        )
        self._auto_deploy()
        self._set_hint(labels.TRAIN_HINT_IDLE)
        self._on_run_finished()

    def _auto_deploy(self) -> None:
        """训练结束自动部署：把最佳模型复制到集中部署目录 ml/deploy/。"""
        from ml.train.deploy_models import deploy_latest

        self._append_log(labels.TRAIN_DEPLOY_START,
                         color=DEFAULT_TOKENS.colors.TEXT_NEON_CYAN)
        result = deploy_latest(on_log=lambda msg: self._append_log(
            msg, color=DEFAULT_TOKENS.colors.TEXT_DIM))
        if result["ok"]:
            self._append_log(labels.TRAIN_DEPLOY_DONE.format(dir=result["dir"]),
                             color=DEFAULT_TOKENS.colors.TEXT_NEON_GREEN)
            self._run_deploy_smoke()
        else:
            self._append_log(labels.TRAIN_DEPLOY_FAILED.format(reason=result["error"]),
                             color=DEFAULT_TOKENS.colors.TEXT_DANGER)
        narrative.event(
            "train_deploy", ok=result["ok"],
            deploy_dir=result["dir"], files=",".join(result["files"]),
            note="训练完成自动部署新模型",
        )

    def _run_deploy_smoke(self) -> None:
        """部署后冒烟验证：子进程加载 yolo+分类器跑图，确认产物可用。

        以独立脚本运行（不 import torch 进 GUI 进程），结果回显到训练日志。
        """
        from ml.train import training_runner
        script = os.path.join(training_runner.PROJECT_ROOT,
                              "train", "deploy_smoke.py")
        if not os.path.exists(script):
            return
        # 复用训练场进程槽，避免新增一套信号处理
        self._smoke_proc = None
        self._append_log(labels.TRAIN_SMOKE_START,
                         color=DEFAULT_TOKENS.colors.TEXT_NEON_CYAN)
        proc = QProcess(self)
        proc.setWorkingDirectory(training_runner.PROJECT_ROOT)
        proc.setProcessChannelMode(QProcess.MergedChannels)
        penv = QProcessEnvironment.systemEnvironment()
        penv.insert("PYTHONIOENCODING", "utf-8")
        penv.insert("PYTHONUNBUFFERED", "1")
        proc.setProcessEnvironment(penv)
        proc.readyReadStandardOutput.connect(self._on_smoke_out)
        proc.finished.connect(self._on_smoke_finished)
        self._smoke_proc = proc
        proc.start(sys.executable, [script])

    def _on_smoke_out(self) -> None:
        if self._smoke_proc is None:
            return
        raw = self._smoke_proc.readAllStandardOutput()
        for ln in bytes(raw).decode("utf-8", errors="replace").splitlines():
            ln = ln.rstrip("\r")
            if not ln:
                continue
            self._append_log(ln, color=DEFAULT_TOKENS.colors.TEXT_DIM)

    def _on_smoke_finished(self, exit_code: int, exit_status: int) -> None:
        if int(exit_code) == 0:
            self._append_log(labels.TRAIN_SMOKE_OK,
                             color=DEFAULT_TOKENS.colors.TEXT_NEON_GREEN)
        else:
            self._append_log(labels.TRAIN_SMOKE_FAILED.format(exit=int(exit_code)),
                             color=DEFAULT_TOKENS.colors.TEXT_DANGER)
        self._smoke_proc = None

    def _on_run_finished(self) -> None:
        # 停止耗时刷新、关闭日志文件、复位状态区
        if self._train_elapsed_timer is not None:
            self._train_elapsed_timer.stop()
        if self._train_log_fh is not None:
            try:
                self._train_log_fh.close()
            except OSError:
                pass
            self._train_log_fh = None
        self._train_cur_stage = None
        self._train_stage_lb.setText(labels.TRAIN_STATUS_STAGE.format(
            stage=labels.TRAIN_STAGE_IDLE))
        self._train_status_lb.setText(labels.TRAIN_STATUS_ETA_IDLE)
        self._train_progress_bar.setValue(0)
        self._proc = None
        self._train_stop_btn.setEnabled(False)
        self._train_oneclick.setEnabled(True)

    def _train_stop_handler(self) -> None:
        """停止训练：弹确认框 → terminate → 宽限期后仍未退出再 kill。"""
        proc = self._proc
        if proc is None or proc.state() == QProcess.NotRunning:
            return
        box = QMessageBox(self)
        box.setWindowTitle(labels.TRAIN_STOP_CONFIRM_TITLE)
        box.setText(labels.TRAIN_STOP_CONFIRM_MSG)
        box.setIcon(QMessageBox.Question)
        stop_btn = box.addButton(labels.TRAIN_BTN_STOP, QMessageBox.AcceptRole)
        box.addButton(labels.ANNOT_CANCEL_BTN, QMessageBox.RejectRole)
        box.setDefaultButton(stop_btn)
        box.exec_()
        if box.clickedButton() is not stop_btn:
            return
        self._stop_requested = True
        self._pending_cmds = []
        self._train_stop_btn.setEnabled(False)
        self._set_hint(labels.TRAIN_HINT_STOPPING)
        self._append_log(labels.TRAIN_HINT_STOPPING,
                         color=DEFAULT_TOKENS.colors.PROGRESS_CHUNK_WARNING)
        narrative.event(
            "train_stop_requested",
            stage=self._train_cur_stage or "none",
            note="用户确认停止训练",
        )
        proc.terminate()
        # 宽限期后仍未退出 → 强杀（进程已退出则 no-op）
        QTimer.singleShot(config.TRAIN_STOP_GRACE_MS, lambda: self._force_kill(proc))

    @staticmethod
    def _force_kill(proc) -> None:
        if proc is not None and proc.state() != QProcess.NotRunning:
            proc.kill()

    def _append_log(self, text: str, color=None) -> None:
        if text == "":
            return
        self._train_log_write(text)
        cursor = self._train_log.textCursor()
        cursor.movePosition(QTextCursor.End)
        fmt = QTextCharFormat()
        if color is not None:
            fmt.setForeground(QColor(color))
        cursor.insertText(str(text) + "\n", fmt)
        self._train_log.setTextCursor(cursor)
        sb = self._train_log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _set_hint(self, text: str, running: bool = False, fail: bool = False) -> None:
        self._train_hint.setText(text)
        self._train_hint.setProperty("running", running)
        self._train_hint.setProperty("state", "fail" if fail else "")
        self._train_hint.style().unpolish(self._train_hint)
        self._train_hint.style().polish(self._train_hint)

    # -- 训练页 · 数据集概览 / 设备检测 / 配置同步 -------------------------------
    def _refresh_dataset_overview(self) -> None:
        """统计 datasets/merged 下 train/val/test txt 的图数与框数。"""
        from ml.train.training_runner import PROJECT_ROOT as ml_root
        merged = os.path.join(ml_root, "datasets", "merged")

        def _stats(split):
            path = os.path.join(merged, "2025_%s.txt" % split)
            n_img = 0
            n_box = 0
            if os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    for ln in f:
                        ln = ln.strip()
                        if not ln:
                            continue
                        n_img += 1
                        n_box += len(ln.split()) - 1
            return n_img, n_box

        tr, boxes = _stats("train")
        va, _ = _stats("val")
        te, _ = _stats("test")
        if tr == 0 and va == 0 and te == 0:
            self._train_ds_lb.setText(labels.TRAIN_DATASET_EMPTY)
            return
        self._train_ds_lb.setText(labels.TRAIN_DATASET_TEMPLATE.format(
            tr=tr, va=va, te=te, boxes=boxes))
        self._update_auto_summary()   # 数据集变化 → 自动推荐同步刷新

    def _detect_device(self, on_done=None) -> None:
        """子进程探测硬件环境（GPU/CPU/内存），不 import torch 进 GUI 进程。

        on_done: 可选回调，探测完成后调用（用于训练启动前的自动分配）。
        """
        if on_done is not None:
            self._train_pending_cb = on_done   # 不覆盖已有回调（防「重新评估」抢跑）
        self._train_dev_lb.setText(labels.TRAIN_DEVICE_PROBING)
        self._train_auto_summary.setText(labels.TRAIN_AUTO_PROBING)
        from ml.train import auto_params
        from ml.train import training_runner
        proc = QProcess(self)
        proc.setWorkingDirectory(training_runner.PROJECT_ROOT)
        penv = QProcessEnvironment.systemEnvironment()
        penv.insert("PYTHONIOENCODING", "utf-8")
        proc.setProcessEnvironment(penv)
        proc.readyReadStandardOutput.connect(self._on_dev_proc_out)
        proc.finished.connect(self._on_dev_proc_finished)
        self._dev_proc = proc
        proc.start(sys.executable, ["-c", auto_params.PROBE_SNIPPET])

    def _on_dev_proc_out(self) -> None:
        if self._dev_proc is None:
            return
        raw = self._dev_proc.readAllStandardOutput()
        data = bytes(raw).decode("utf-8", errors="replace")
        from ml.train import auto_params
        self._dev_info = auto_params.parse_env_output(data)

    def _on_dev_proc_finished(self, exit_code: int, exit_status: int) -> None:
        info = self._dev_info
        self._dev_proc = None
        if info is not None and info.has_gpu:
            self._train_dev_lb.setText(labels.TRAIN_DEVICE_TEMPLATE.format(
                avail="GPU", name=info.gpu_name, count=info.gpu_count, mem=info.gpu_mem_gb))
        else:
            self._train_dev_lb.setText(labels.TRAIN_DEVICE_CPU)
        self._update_auto_summary()
        cb = self._train_pending_cb
        self._train_pending_cb = None
        if cb is not None:
            cb()

    # -- 训练页 · 自动分配参数 -------------------------------------------------
    def _recompute_auto_params(self) -> None:
        """「重新评估」：重新探测环境并刷新推荐摘要。"""
        self._detect_device()

    def _update_auto_summary(self) -> None:
        """刷新自动分配推荐摘要（环境 + 数据集 + 推荐参数）。"""
        if self._dev_info is None:
            self._train_auto_summary.setText(labels.TRAIN_AUTO_WAIT)
            return
        rec = self._recommended_params()
        self._last_rec = rec
        self._train_auto_summary.setText(labels.TRAIN_AUTO_SUMMARY.format(
            phi=rec.phi, yep=rec.yolo_epochs, ybatch=rec.yolo_batch,
            cep=rec.cls_epochs, cbatch=rec.cls_batch))

    def _auto_notes_text(self) -> str:
        """自动分配说明（日志可读性）：设备 → 数据 → 参数。"""
        rec = self._last_rec
        if rec is None:
            rec = self._recommended_params()
            self._last_rec = rec
        env = self._dev_info
        lines = []
        if env is not None and env.has_gpu:
            lines.append(labels.TRAIN_AUTO_NOTE_GPU.format(
                name=env.gpu_name, mem=env.gpu_mem_gb))
        else:
            lines.append(labels.TRAIN_AUTO_NOTE_CPU)
        from ml.train import auto_params
        ds = auto_params.dataset_stats()
        if ds.train_imgs:
            lines.append(labels.TRAIN_AUTO_NOTE_DATA.format(
                n=ds.train_imgs, yep=rec.yolo_epochs, ybatch=rec.yolo_batch))
        else:
            lines.append(labels.TRAIN_AUTO_NOTE_EMPTY)
        lines.append(labels.TRAIN_AUTO_SUMMARY.format(
            phi=rec.phi, yep=rec.yolo_epochs, ybatch=rec.yolo_batch,
            cep=rec.cls_epochs, cbatch=rec.cls_batch))
        return "\n".join(lines)

    def _build_placeholder_page(self, title: str, body: str) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setAlignment(Qt.AlignCenter)
        accent = QLabel(f"// {title}")
        accent.setObjectName("dcTabPlaceholderAccent")
        text = QLabel(body)
        text.setObjectName("dcTabPlaceholder")
        text.setAlignment(Qt.AlignCenter)
        text.setWordWrap(True)
        lay.addWidget(accent, 0, Qt.AlignCenter)
        lay.addSpacing(self._s.DATA_PLACEHOLDER_GAP)
        lay.addWidget(text, 0, Qt.AlignCenter)
        lay.addStretch(1)
        return page

    # -- 数据标注页 ------------------------------------------------------------
    def _build_annotate_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, self._s.DATA_PAGE_SPACING, 0, 0)
        lay.setSpacing(self._s.DATA_PAGE_SPACING)
        lay.addWidget(self._build_category_bar())
        split = QSplitter(Qt.Horizontal)
        split.setObjectName("dataSplitter")
        split.setChildrenCollapsible(False)
        split.addWidget(self._build_image_sidebar())
        split.addWidget(self._build_canvas_panel())
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([self._s.DATA_SIDEBAR_W, self._s.DATA_SIDEBAR_W * 3])
        lay.addWidget(split, 1)
        lay.addWidget(self._build_footer())
        lay.addStretch(0)
        return page

    def _build_category_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("dcCategoryBar")
        bar.setFixedHeight(self._s.DATA_CATEGORY_BAR_H)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(
            self._s.DATA_CATEGORY_PAD, 0,
            self._s.DATA_CATEGORY_PAD, 0,
        )
        lay.setSpacing(self._s.DATA_CATEGORY_GAP)
        lay.setAlignment(Qt.AlignVCenter)
        label = QLabel(labels.ANNOT_CATEGORY_LABEL)
        label.setObjectName("dcBarLabel")
        lay.addWidget(label)
        self._category_group = QButtonGroup(self)
        self._category_group.setExclusive(True)
        self._active_category = None
        self._category_buttons = {}
        # 工具切换（绘制 / 编辑），互斥；导向画布模式
        tool_label = QLabel(labels.ANNOT_TOOL_LABEL)
        tool_label.setObjectName("dcBarLabel")
        lay.addWidget(tool_label)
        self._tool_group = QButtonGroup(self)
        self._tool_group.setExclusive(True)
        draw_btn = QPushButton(labels.ANNOT_TOOL_DRAW)
        draw_btn.setObjectName("dcChipBtn")
        draw_btn.setCheckable(True)
        draw_btn.setToolTip(labels.ANNOT_TOOL_DRAW_TIP)
        draw_btn.setChecked(True)
        draw_btn.clicked.connect(lambda _=False: self._on_tool_chosen(True))
        edit_btn = QPushButton(labels.ANNOT_TOOL_EDIT)
        edit_btn.setObjectName("dcChipBtn")
        edit_btn.setCheckable(True)
        edit_btn.setToolTip(labels.ANNOT_TOOL_EDIT_TIP)
        edit_btn.clicked.connect(lambda _=False: self._on_tool_chosen(False))
        self._tool_group.addButton(draw_btn)
        self._tool_group.addButton(edit_btn)
        self._tool_draw_btn = draw_btn
        lay.addWidget(draw_btn)
        lay.addWidget(edit_btn)
        # 类别芯片统一放入独立容器，便于「新增/删除类别」后整体重建
        self._chips_box = QFrame(self)
        self._chips_box.setObjectName("dcChipsBox")
        self._chips_lay = QHBoxLayout(self._chips_box)
        self._chips_lay.setContentsMargins(0, 0, 0, 0)
        self._chips_lay.setSpacing(self._s.DATA_CATEGORY_GAP)
        lay.addWidget(self._chips_box)
        self._rebuild_category_chips()
        add_btn = QPushButton(labels.ANNOT_CATEGORY_ADD)
        add_btn.setObjectName("dcChipAdd")
        add_btn.setCursor(Qt.PointingHandCursor)
        add_btn.clicked.connect(self._on_add_category)
        lay.addWidget(add_btn)
        manage = QPushButton(labels.ANNOT_CATEGORY_DELETE)
        manage.setObjectName("dcGhostBtn")
        manage.setCursor(Qt.PointingHandCursor)
        manage.clicked.connect(self._on_delete_category)
        lay.addWidget(manage)
        import_btn = QPushButton(labels.ANNOT_IMPORT_BTN)
        import_btn.setObjectName("dcPrimaryBtn")
        import_btn.clicked.connect(self._on_import_folder)
        lay.addWidget(import_btn)
        video_btn = QPushButton(labels.ANNOT_VIDEO_IMPORT_BTN)
        video_btn.setObjectName("dcPrimaryBtn")
        video_btn.clicked.connect(self._on_import_video)
        lay.addWidget(video_btn)
        return bar

    def _on_category_chosen(self, name: str) -> None:
        self._active_category = name
        if self._canvas is not None:
            self._canvas.set_active_category(name)
        # 选择类别即切换回「绘制」工具，便于立即连续标注
        if self._tool_draw_btn is not None:
            self._tool_draw_btn.setChecked(True)

    def _on_tool_chosen(self, is_draw: bool) -> None:
        """「绘制 / 编辑」工具切换：同步画布模式。"""
        if self._canvas is None:
            return
        mode = _ANNOT_MODE_CREATE if is_draw else _ANNOT_MODE_EDIT
        self._canvas.set_mode(mode)
        # 切换到绘制工具时，若有活动类别则确保画布指向它
        if is_draw and self._active_category:
            self._canvas.set_active_category(self._active_category)

    def _clear_chips(self) -> None:
        """清空类别芯片容器，并同步按钮组与画布当前类别。"""
        while self._chips_lay.count():
            item = self._chips_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        for btn in self._category_buttons.values():
            self._category_group.removeButton(btn)
        self._category_buttons.clear()

    def _rebuild_category_chips(self) -> None:
        """按注册表当前类别重建类别芯片按钮。"""
        self._clear_chips()
        for cat in self._category_names():
            btn = QPushButton(cat)
            btn.setObjectName("dcChipBtn")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _c=False, name=cat: self._on_category_chosen(name))
            self._category_group.addButton(btn)
            self._category_buttons[cat] = btn
            self._chips_lay.addWidget(btn)
        # 保持当前选中状态（若类别仍存在）
        if self._active_category in self._category_buttons:
            self._category_buttons[self._active_category].setChecked(True)
            if self._canvas is not None:
                self._canvas.set_active_category(self._active_category)
        elif not self._category_buttons:
            self._active_category = None
        elif self._category_buttons:
            # 之前选中的类别已被删除：切回第一个类别
            first = next(iter(self._category_buttons))
            self._on_category_chosen(first)
            self._category_buttons[first].setChecked(True)
        # 类别集合变化后同步画布（新增/删除类别时重配，保证配色与可用类别一致）
        if self._canvas is not None:
            self._configure_canvas(self._canvas)

    def _set_current_series(self, series: str) -> None:
        """设置当前图片系列，并刷新类别条 + 画布类别。"""
        series = series or ""
        if series == self._current_series:
            return
        self._current_series = series
        self._active_category = None
        self._rebuild_category_chips()

    def _infer_series_from_entries(self, entries) -> str:
        """从已有标注的类别名推断所属系列（文件夹结构写不出时的兜底）。

        取若干条带 XML 标注的条目，解析其中的类别名（如 ``A_CLIP_H``），
        用类别名前缀与注册表已有系列比对，返回第一个命中的系列名；
        全部无法识别时返回空串（此时类别条保持空，不误显示他系列）。
        """
        from ml.annotation_registry import get_registry, infer_series

        reg = get_registry()
        known = {s.upper() for s in reg.series}
        _, _, parse_annotation, _, _ = self._lazy_annotation_io()
        for entry in entries[:20]:
            if not entry.has_xml:
                continue
            try:
                objs = parse_annotation(entry.xml_path)["objects"]
            except Exception:
                continue
            for o in objs:
                prefix = infer_series(o["name"]).upper()
                if prefix in known:
                    return prefix
        return ""

    def _on_add_category(self) -> None:
        """「新增类别」：输入名称 + 类型 + 是否带亮灭，写回注册表后重建芯片。"""
        from app.ui.dialogs import confirm_yes_cancel

        from ml.annotation_registry import add_category

        name, ok = QInputDialog.getText(
            self, labels.ANNOT_CATEGORY_ADD_TITLE,
            labels.ANNOT_CATEGORY_NAME_PROMPT,
        )
        if not ok:
            return
        name = (name or "").strip()
        if not name:
            QMessageBox.warning(self, labels.ANNOT_CATEGORY_ADD_TITLE,
                                labels.ANNOT_CATEGORY_NAME_EMPTY)
            return
        # 若当前有图片系列，自动给类别名补上系列前缀（保持系列一致）
        if self._current_series:
            prefix = self._current_series.upper() + "_"
            if not name.upper().startswith(prefix):
                name = prefix + name
        # 类型选择
        kind_map = {
            labels.ANNOT_CATEGORY_KIND_LED: "led",
            labels.ANNOT_CATEGORY_KIND_AREA: "area",
        }
        kind_label, ok = QInputDialog.getItem(
            self, labels.ANNOT_CATEGORY_ADD_TITLE,
            labels.ANNOT_CATEGORY_KIND_PROMPT,
            [labels.ANNOT_CATEGORY_KIND_LED, labels.ANNOT_CATEGORY_KIND_AREA],
            editable=False,
        )
        if not ok:
            return
        kind = kind_map[kind_label]
        # 是否带亮灭（仅 led 类型询问）
        hl = False
        if kind == "led":
            hl = confirm_yes_cancel(
                self, labels.ANNOT_CATEGORY_ADD_TITLE,
                labels.ANNOT_CATEGORY_HL_PROMPT,
                labels.ANNOT_CATEGORY_HL_YES, labels.ANNOT_CATEGORY_HL_NO,
                icon=QMessageBox.Question, default_yes=True,
            )
        try:
            added = add_category(name, kind, hl)
        except ValueError as exc:
            QMessageBox.warning(self, labels.ANNOT_CATEGORY_ADD_TITLE, str(exc))
            return
        if not added:
            QMessageBox.information(self, labels.ANNOT_CATEGORY_ADD_TITLE,
                                    labels.ANNOT_CATEGORY_ADD_EXISTS.format(name=name))
            return
        QMessageBox.information(self, labels.ANNOT_CATEGORY_ADD_TITLE,
                                labels.ANNOT_CATEGORY_ADD_SUCCESS.format(name=name))
        self._rebuild_category_chips()

    def _on_delete_category(self) -> None:
        """「删除类别」：列出当前系列类别，选择后确认删除，删除后重建芯片。"""
        from app.ui.dialogs import confirm_yes_cancel

        from ml.annotation_registry import get_registry, remove_category

        reg = get_registry()
        names = reg.category_names_for_series(self._current_series)
        if not names:
            QMessageBox.information(self, labels.ANNOT_CATEGORY_DELETE_TITLE,
                                    labels.ANNOT_CATEGORY_DELETE_EMPTY_HINT)
            return
        name, ok = QInputDialog.getItem(
            self, labels.ANNOT_CATEGORY_DELETE_TITLE,
            labels.ANNOT_CATEGORY_DELETE_PROMPT,
            names, editable=False,
        )
        if not ok:
            return
        if not confirm_yes_cancel(
                self, labels.ANNOT_CATEGORY_DELETE_TITLE,
                labels.ANNOT_CATEGORY_REMOVE_CONFIRM.format(name=name),
                labels.ANNOT_CATEGORY_REMOVE_YES,
                labels.ANNOT_CANCEL_BTN,
        ):
            return
        if remove_category(name):
            QMessageBox.information(self, labels.ANNOT_CATEGORY_DELETE_TITLE,
                                    labels.ANNOT_CATEGORY_REMOVE_SUCCESS.format(name=name))
        else:
            QMessageBox.warning(self, labels.ANNOT_CATEGORY_DELETE_TITLE,
                                labels.ANNOT_CATEGORY_REMOVE_FAILED)
        self._rebuild_category_chips()

    def _build_image_sidebar(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("dcSidePanel")
        panel.setFixedWidth(self._s.DATA_SIDEBAR_W)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(
            self._s.DATA_SIDEBAR_PAD,
            self._s.DATA_SIDEBAR_PAD,
            self._s.DATA_SIDEBAR_PAD,
            self._s.DATA_SIDEBAR_PAD,
        )
        lay.setSpacing(self._s.DATA_SIDEBAR_GAP)
        title = QLabel(labels.ANNOT_IMAGE_LIST_TITLE)
        title.setObjectName("dcPanelTitle")
        lay.addWidget(title)
        # 筛选行：全部 / 已标注 / 未标注
        filt_row = QHBoxLayout()
        filt_row.setSpacing(self._s.DATA_SIDEBAR_NAV_GAP)
        filt_lb = QLabel(labels.ANNOT_FILTER_LABEL)
        filt_lb.setObjectName("dcPanelTitle")
        filt_row.addWidget(filt_lb)
        self._filter_combo = QComboBox()
        self._filter_combo.setObjectName("dcFilterCombo")
        self._filter_combo.addItems([
            labels.ANNOT_FILTER_ALL,
            labels.ANNOT_FILTER_MAPPED,
            labels.ANNOT_FILTER_UNMAPPED,
        ])
        self._filter_combo.currentIndexChanged.connect(self._on_filter_changed)
        filt_row.addWidget(self._filter_combo, 1)
        lay.addLayout(filt_row)
        self._stats_lb = QLabel(labels.ANNOT_STATS_TEMPLATE.format(
            total=0, mapped=0, unmapped=0))
        self._stats_lb.setObjectName("dcStatsLabel")
        lay.addWidget(self._stats_lb)
        self._image_list = QListWidget()
        self._image_list.setObjectName("dcList")
        self._image_list.currentItemChanged.connect(self._on_current_item_changed)
        empty_item = QListWidgetItem(labels.ANNOT_IMPORT_EMPTY)
        empty_item.setFlags(Qt.NoItemFlags)
        self._image_list.addItem(empty_item)
        lay.addWidget(self._image_list, 1)
        nav = QHBoxLayout()
        nav.setSpacing(self._s.DATA_SIDEBAR_NAV_GAP)
        prev = QPushButton(f"◀  {labels.ANNOT_PREV_BTN}")
        prev.setObjectName("dcGhostBtn")
        prev.clicked.connect(lambda: self._navigate_image(-1))
        nxt = QPushButton(f"{labels.ANNOT_NEXT_BTN}  ▶")
        nxt.setObjectName("dcGhostBtn")
        nxt.clicked.connect(lambda: self._navigate_image(1))
        nav.addWidget(prev)
        index_lb = QLabel(labels.ANNOT_INDEX_EMPTY)
        index_lb.setObjectName("dcZoomPct")
        index_lb.setAlignment(Qt.AlignCenter)
        self._index_lb = index_lb
        nav.addWidget(index_lb)
        nav.addWidget(nxt)
        lay.addLayout(nav)
        return panel

    def _build_canvas_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("dcCanvasOuter")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        canvas = QFrame()
        canvas.setObjectName("dcCanvas")
        canvas.setMinimumHeight(self._s.DATA_CANVAS_MIN_H)
        cl = QVBoxLayout(canvas)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        # 角标行（左上 CANVAS / 右上 □ □ □ ✕）
        top = QHBoxLayout()
        top.setContentsMargins(
            self._s.DATA_CANVAS_PAD_X,
            self._s.DATA_CANVAS_PAD_T,
            self._s.DATA_CANVAS_PAD_X,
            0,
        )
        top.setSpacing(self._s.DATA_CANVAS_GAP)
        corner_lt = QLabel(labels.ANNOT_CANVAS_CORNER_TEMPLATE.format(
            w=self._s.ANNOT_CANVAS_REF_W,
            h=self._s.ANNOT_CANVAS_REF_H,
            pct=self._s.ANNOT_ZOOM_PCT_DEFAULT,
        ))
        corner_lt.setObjectName("dcCanvasCorner")
        top.addWidget(corner_lt)
        top.addStretch(1)
        # 缩放控制条（− 百分比 +  |  1:1  适应）
        out_btn = QPushButton(labels.ANNOT_ZOOM_OUT)
        out_btn.setObjectName("dcZoomBtn")
        out_btn.setToolTip(labels.ANNOT_ZOOM_TOOLTIP_OUT)
        in_btn = QPushButton(labels.ANNOT_ZOOM_IN)
        in_btn.setObjectName("dcZoomBtn")
        in_btn.setToolTip(labels.ANNOT_ZOOM_TOOLTIP_IN)
        zoom_pct = QLabel(labels.ANNOT_ZOOM_PCT_TEMPLATE.format(
            pct=self._s.ANNOT_ZOOM_PCT_SCALE))
        zoom_pct.setObjectName("dcZoomPct")
        orig_btn = QPushButton(labels.ANNOT_ZOOM_ORIG)
        orig_btn.setObjectName("dcZoomBtn")
        orig_btn.setToolTip(labels.ANNOT_ZOOM_TOOLTIP_ORIG)
        fit_btn = QPushButton(labels.ANNOT_ZOOM_FIT)
        fit_btn.setObjectName("dcZoomBtn")
        fit_btn.setToolTip(labels.ANNOT_ZOOM_TOOLTIP_FIT)
        # 记录引用，待画布创建后接线
        self._zoom_buttons = (out_btn, in_btn, orig_btn, fit_btn)
        self._zoom_pct = zoom_pct
        top.addWidget(out_btn)
        top.addWidget(in_btn)
        top.addWidget(zoom_pct)
        top.addWidget(orig_btn)
        top.addWidget(fit_btn)
        cl.addLayout(top)
        # 中心区域：空状态提示 与 标注器（stack 切换）
        self._canvas_stack = QStackedWidget()
        self._canvas_stack.setObjectName("dcCanvasStack")
        # 空状态页
        empty = QWidget()
        empty.setObjectName("dcCanvasCenter")
        cc = QVBoxLayout(empty)
        cc.setAlignment(Qt.AlignCenter)
        cc.setSpacing(self._s.DATA_CANVAS_CENTER_GAP)
        accent = QLabel("// PHASE B  ·  ANNOTATOR")
        accent.setObjectName("dcCanvasHintAccent")
        hint = QLabel(labels.ANNOT_CANVAS_HINT)
        hint.setObjectName("dcCanvasHint")
        hint.setAlignment(Qt.AlignCenter)
        hint.setWordWrap(True)
        self._canvas_hint = hint
        cc.addWidget(accent, 0, Qt.AlignCenter)
        cc.addWidget(hint, 0, Qt.AlignCenter)
        self._canvas_stack.addWidget(empty)
        # 标注器页（懒加载创建）
        self._canvas_stack.addWidget(self._make_canvas())
        cl.addWidget(self._canvas_stack, 1)
        # 底角标
        bottom = QHBoxLayout()
        bottom.setContentsMargins(
            self._s.DATA_CANVAS_PAD_X,
            0,
            self._s.DATA_CANVAS_PAD_X,
            self._s.DATA_CANVAS_PAD_B,
        )
        bottom.setSpacing(self._s.DATA_CANVAS_GAP)
        corner_lb = QLabel("--  ·  -- OBJECTS  ·  READY")
        corner_lb.setObjectName("dcCanvasCorner")
        self._canvas_corner_lb = corner_lb
        bottom.addWidget(corner_lb)
        bottom.addStretch(1)
        corner_rb = QLabel("FPS  —  ZOOM  1.0×  ·  PX  0,0")
        corner_rb.setObjectName("dcCanvasCorner")
        bottom.addWidget(corner_rb)
        cl.addLayout(bottom)
        lay.addWidget(canvas, 1)
        return panel

    def _build_footer(self) -> QFrame:
        foot = QFrame()
        foot.setObjectName("dcFooter")
        foot.setMinimumHeight(self._s.DATA_FOOTER_MIN_H)
        lay = QVBoxLayout(foot)
        lay.setContentsMargins(
            self._s.DATA_FOOTER_PAD, 0,
            self._s.DATA_FOOTER_PAD, 0,
        )
        lay.setSpacing(self._s.DATA_FOOTER_GAP)
        # 标题行
        head = QHBoxLayout()
        head.setSpacing(self._s.DATA_FOOTER_HEAD_GAP)
        title = QLabel(labels.ANNOT_OBJECT_LIST_TITLE)
        title.setObjectName("dcFooterTitle")
        head.addWidget(title)
        head.addStretch(1)
        count = QLabel("0")
        count.setObjectName("dataHeaderStatus")
        self._footer_count = count
        head.addWidget(count)
        lay.addLayout(head)
        # 对象列表
        self._object_list = QListWidget()
        self._object_list.setObjectName("dcObjectList")
        self._object_list.addItem(labels.ANNOT_OBJECT_LIST_EMPTY)
        lay.addWidget(self._object_list, 1)
        # 操作按钮
        btns = QHBoxLayout()
        btns.setSpacing(self._s.DATA_FOOTER_BTN_GAP)
        btns.addStretch(1)
        delete_btn = QPushButton(labels.ANNOT_DELETE_SELECTED_BTN)
        delete_btn.setObjectName("dcGhostBtn")
        delete_btn.clicked.connect(self._on_delete_selected)
        cancel = QPushButton(labels.ANNOT_CANCEL_BTN)
        cancel.setObjectName("dcGhostBtn")
        save = QPushButton(f"💾  {labels.ANNOT_SAVE_BTN}")
        save.setObjectName("dcPrimaryBtn")
        save.clicked.connect(self._on_save_annotation)
        btns.addWidget(delete_btn)
        btns.addWidget(cancel)
        btns.addWidget(save)
        lay.addLayout(btns)
        return foot

    # -- 懒加载 annotation_io（切到标注页才 import，保持启动轻量） ---------------
    def _lazy_annotation_io(self):
        """懒加载 ml.annotation_io 模块。"""
        from ml.annotation_io import (
            ImageEntry, count_mapped, parse_annotation, scan_image_folder,
            write_annotation,
        )
        return ImageEntry, count_mapped, parse_annotation, scan_image_folder, write_annotation

    def _lazy_annotation_widget(self):
        """懒加载 ml.annotation_widget 模块。"""
        from ml.annotation_widget import AnnotationCanvas
        return AnnotationCanvas

    def _category_names(self):
        """返回当前图片系列下可标注的类别名（led 类展开为 H/L 亮灭）。

        设计：除 area 区域类外，所有 LED 类在标注时都要带 H/L 属性
        （如 ``FP_VPL_H`` / ``FP_VPL_L``），让标注阶段即保留亮/灭信息；
        训练侧 gen_merged_txt 会自动剥掉 H/L 后缀，故无需重复处理。

        未导入图片 / 系列未识别时返回空，避免错误地显示他系列类别。
        """
        from ml.annotation_registry import get_registry
        return get_registry().annotation_names_for_series(self._current_series)

    def _configure_canvas(self, canvas):
        """把当前系列的类别与配色注入画布（新增/删除类别或切换系列后重配）。"""
        canvas.configure(
            categories=self._category_names(),
            palette=DEFAULT_TOKENS.colors.ANNOT_BOX_PALETTE,
            selected_color=DEFAULT_TOKENS.colors.ANNOT_BOX_SELECTED,
            border_w=DEFAULT_TOKENS.sizing.ANNOT_BOX_BORDER_W,
            sel_border_w=DEFAULT_TOKENS.sizing.ANNOT_BOX_BORDER_W_SEL,
            min_size=DEFAULT_TOKENS.sizing.ANNOT_BOX_MIN_SIZE,
            padding=DEFAULT_TOKENS.sizing.ANNOT_PADDING_PX,
        )

    def _make_canvas(self):
        """创建（懒加载）标注画布并注入配置。"""
        AnnotationCanvas = self._lazy_annotation_widget()
        canvas = AnnotationCanvas()
        self._configure_canvas(canvas)
        canvas.annotations_changed.connect(self._on_annotations_changed)
        canvas.selection_changed.connect(self._on_annotations_changed)
        canvas.navigate_signal.connect(self._navigate_image)
        canvas.save_requested.connect(self._on_save_annotation)
        canvas.zoom_changed.connect(self._on_zoom_changed)
        # 接线缩放控制条
        out_btn, in_btn, orig_btn, fit_btn = self._zoom_buttons
        out_btn.clicked.connect(canvas.zoom_out)
        in_btn.clicked.connect(canvas.zoom_in)
        orig_btn.clicked.connect(canvas.zoom_to_original)
        fit_btn.clicked.connect(canvas.fit_to_view_trigger)
        self._canvas = canvas
        return canvas

    # -- 导入图片文件夹 + XML 映射 -------------------------------------------------
    def _on_import_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, labels.ANNOT_IMPORT_DIALOG_TITLE, "", QFileDialog.ShowDirsOnly,
        )
        if not folder:
            return
        self._load_entries_from_folder(folder)

    def _load_entries_from_folder(self, folder: str) -> None:
        """扫描图片文件夹 → 刷新主列表 + 系列类别 + 图片列表（含筛选）。"""
        _, _, _, scan_image_folder, _ = self._lazy_annotation_io()
        try:
            entries = scan_image_folder(folder)
        except FileNotFoundError as exc:
            self._canvas_hint.setText(str(exc))
            return
        self._all_entries = entries
        # 根据本次图片所属系列刷新类别条与画布类别（空系列则不显示类别）
        series = entries[0].series if entries else ""
        if not series:
            # 文件夹结构推断不出系列时，从已有标注类别名兜底推断
            series = self._infer_series_from_entries(entries)
        self._set_current_series(series)
        self._xml_dir = entries[0].xml_dir if entries else None
        self._refresh_image_list()

    def _on_filter_changed(self) -> None:
        """筛选下拉变化 → 重刷图片列表。"""
        self._refresh_image_list()

    def _current_filter(self) -> str:
        """当前筛选键："all" / "mapped" / "unmapped"。"""
        idx = self._filter_combo.currentIndex()
        return ("all", "mapped", "unmapped")[idx]

    def _refresh_image_list(self) -> None:
        """按筛选重建图片列表，并刷新统计标签。"""
        all_entries = getattr(self, "_all_entries", None) or []
        filt = self._current_filter()
        if filt == "mapped":
            entries = [e for e in all_entries if e.has_xml]
        elif filt == "unmapped":
            entries = [e for e in all_entries if not e.has_xml]
        else:
            entries = list(all_entries)
        self._entries = entries
        self._image_list.clear()
        for entry in entries:
            mark = labels.ANNOT_IMAGE_MAPPED_MARK if entry.has_xml else labels.ANNOT_IMAGE_UNMAPPED_MARK
            item = QListWidgetItem(labels.ANNOT_IMAGE_ENTRY.format(mark=mark, name=entry.image_name))
            item.setData(Qt.UserRole, entry)
            self._image_list.addItem(item)
        mapped = sum(1 for e in all_entries if e.has_xml)
        self._stats_lb.setText(labels.ANNOT_STATS_TEMPLATE.format(
            total=len(all_entries), mapped=mapped,
            unmapped=len(all_entries) - mapped,
        ))
        self._canvas_hint.setText(
            labels.ANNOT_IMPORT_SUMMARY.format(total=len(all_entries), mapped=mapped),
        )
        if entries:
            self._image_list.setCurrentRow(0)

    # -- 导入视频：自动抽帧 → 关联到对应系列 --------------------------------------
    def _on_import_video(self) -> None:
        """打开视频导入对话框；抽取完成后自动加载目标系列图片列表。"""
        dlg = VideoImportDialog(self)
        if dlg.exec_() != QDialog.Accepted:
            return
        result = dlg.result_info
        if not result:
            return
        target_dir = result.get("target_dir")
        if target_dir and os.path.isdir(target_dir):
            self._load_entries_from_folder(target_dir)
        narrative.event(
            "annot_video_imported", series=result.get("series", ""),
            saved=result.get("saved", 0),
            target=target_dir or "none",
            note="标注页：视频抽帧导入完成",
        )

    # -- 选中图片：加载到画布 + 显示标注框 + 刷新对象列表 --------------------------
    def _on_current_item_changed(self, current, previous) -> None:
        """图片列表选中变化。若当前图有未保存改动，先询问再切换。"""
        if self._skip_item_change:
            self._skip_item_change = False
            return
        if current is None:
            return
        row = self._image_list.row(current)
        # 有未保存改动且确实在切换：询问
        if (previous is not None
                and self._canvas is not None
                and self._canvas.is_dirty):
            name = self._current_entry.image_name if self._current_entry else ""
            ret = self._confirm_unsaved(name)
            if ret == QMessageBox.Cancel:
                # 取消：回退选中到上一张，但不触发回调
                self._skip_item_change = True
                self._image_list.setCurrentItem(previous)
                return
            if ret == QMessageBox.Discard:
                self._canvas.mark_saved()
            # Save 分支：先保存再切换
        self._load_image(row)

    def _load_image(self, row: int) -> None:
        """把指定行的图片加载到画布并刷新显示。"""
        canvas = self._canvas
        if canvas is None:
            return
        if not (0 <= row < len(self._entries)):
            self._canvas_corner_lb.setText("--  ·  -- OBJECTS  ·  READY")
            self._index_lb.setText(labels.ANNOT_INDEX_EMPTY)
            return
        entry = self._entries[row]
        self._current_entry = entry
        # 加载图片
        if not canvas.load_pixmap(entry.image_path):
            self._canvas_corner_lb.setText("IMAGE LOAD FAILED")
            return
        # 解析 XML 并显示框
        objs = []
        if entry.has_xml:
            _, _, parse_annotation, _, _ = self._lazy_annotation_io()
            try:
                data = parse_annotation(entry.xml_path)
                objs = data["objects"]
            except Exception:
                objs = []
        canvas.set_objects(objs)
        # 切到标注器页
        self._canvas_stack.setCurrentIndex(1)
        # 更新当前索引
        self._index_lb.setText(labels.ANNOT_INDEX_TEMPLATE.format(
            cur=row + 1, total=len(self._entries),
        ))
        self._refresh_annotation_view(objs)

    def _navigate_image(self, delta: int) -> None:
        """切换图片（按钮 / D / A 快捷键共用入口）。"""
        if not self._entries:
            return
        current = self._image_list.currentRow()
        new_row = (current + delta) % len(self._entries)
        self._image_list.setCurrentRow(new_row)

    def _confirm_unsaved(self, name: str) -> int:
        """弹出未保存提示，返回 QMessageBox 按钮。"""
        box = QMessageBox(self)
        box.setWindowTitle(labels.ANNOT_UNSAVED_TITLE)
        box.setText(labels.ANNOT_UNSAVED_PROMPT_TEMPLATE.format(name=name))
        box.setIcon(QMessageBox.Warning)
        box.addButton(labels.ANNOT_UNSAVED_DISCARD, QMessageBox.DestructiveRole)
        save_btn = box.addButton(labels.ANNOT_UNSAVED_SAVE, QMessageBox.AcceptRole)
        box.addButton(labels.ANNOT_UNSAVED_CANCEL, QMessageBox.RejectRole)
        box.setDefaultButton(save_btn)
        box.exec_()
        clicked = box.clickedButton()
        if clicked == save_btn:
            # 保存当前改动，再继续切换
            self._on_save_annotation()
            return QMessageBox.Save
        if box.buttonRole(clicked) == QMessageBox.DestructiveRole:
            return QMessageBox.Discard
        return QMessageBox.Cancel

    def _on_zoom_changed(self, zoom: float) -> None:
        """画布缩放变化时刷新百分比显示。"""
        self._zoom_pct.setText(labels.ANNOT_ZOOM_PCT_TEMPLATE.format(
            pct=int(round(zoom * self._s.ANNOT_ZOOM_PCT_SCALE)),
        ))

    def confirm_close(self) -> bool:
        """关闭应用前确认未保存标注。返回 True 表示允许关闭。"""
        if (self._canvas is None or self._current_entry is None
                or not self._canvas.is_dirty):
            return True
        ret = self._confirm_unsaved(self._current_entry.image_name)
        return ret != QMessageBox.Cancel

    # -- 画布对象变化：刷新对象列表与角标 ----------------------------------------
    def _on_annotations_changed(self) -> None:
        if self._current_entry is None:
            return
        objs = self._canvas.export_objects() if self._canvas else []
        self._refresh_annotation_view(objs)

    def _refresh_annotation_view(self, objs) -> None:
        entry = self._current_entry
        series = entry.series if entry else "--"
        n = len(objs)
        self._canvas_corner_lb.setText(
            "{series} · {n} OBJECTS · READY".format(series=series or "--", n=n),
        )
        self._footer_count.setText(str(n))
        self._object_list.clear()
        if objs:
            for o in objs:
                self._object_list.addItem(labels.ANNOT_OBJECT_ENTRY.format(
                    name=o["name"],
                    x1=o["xmin"], y1=o["ymin"],
                    x2=o["xmax"], y2=o["ymax"],
                ))
        else:
            self._object_list.addItem(labels.ANNOT_OBJECT_LIST_EMPTY)

    # -- 删除 / 保存 -----------------------------------------------------------
    def _on_delete_selected(self) -> None:
        if self._canvas is not None:
            self._canvas.delete_selected()

    def _on_save_annotation(self) -> None:
        if self._canvas is None or self._current_entry is None:
            return
        objs = self._canvas.export_objects()
        if not objs:
            self._canvas_hint.setText(labels.ANNOT_OBJECTS_EMPTY_SAVE)
            return
        entry = self._current_entry
        w, h = self._canvas.image_size
        xml_dir = self._xml_dir or os.path.dirname(entry.image_path)
        xml_path = os.path.join(xml_dir, entry.stem + ".xml")
        _, _, _, _, write_annotation = self._lazy_annotation_io()
        try:
            write_annotation(xml_path, entry.image_name, w, h, objs)
        except OSError as exc:
            self._canvas_hint.setText(labels.ANNOT_OBJECTS_SAVE_FAILED.format(reason=exc))
            self._canvas_corner_lb.setText("SAVE FAILED")
            return
        # 更新映射状态为已标注
        entry.xml_path = xml_path
        item = self._image_list.item(self._image_list.currentRow())
        if item is not None:
            item.setText(labels.ANNOT_IMAGE_ENTRY.format(
                mark=labels.ANNOT_IMAGE_MAPPED_MARK, name=entry.image_name))
        self._canvas_hint.setText(labels.ANNOT_OBJECTS_SAVED.format(path=xml_path))


class _VideoExtractWorker(QThread):
    """后台抽帧线程：把耗时抽取放到线程里，避免卡住 GUI 对话框。"""

    progress = pyqtSignal(int, int)   # done, total
    succeeded = pyqtSignal(dict)      # 抽取结果 dict
    failed = pyqtSignal(str)          # 失败原因

    def __init__(self, video_path: str, series: str, step: int, parent=None):
        super().__init__(parent)
        self._video_path = video_path
        self._series = series
        self._step = step

    def run(self) -> None:
        try:
            from ml import datasets_extract
            result = datasets_extract.extract_to_series(
                self._video_path, self._series, self._step,
                on_progress=lambda d, t: self.progress.emit(d, t),
            )
            self.succeeded.emit(result)
        except Exception as exc:  # noqa: BLE001 顶层兜底，失败原因上抛给 UI
            self.failed.emit(str(exc))


class VideoImportDialog(QDialog):
    """导入视频 → 按间隔抽帧 → 关联写入对应系列文件夹。

    对话框内选择视频（自动探测分辨率 / fps / 总帧数）、目标系列（A / FP）
    与抽帧间隔；点击「开始抽取」后由后台线程抽取，实时显示进度，
    完成后 `exec_()` 返回 Accepted，结果存于 `self.result_info`：
        {"saved": int, "target_dir": str, "prefix": str, "series": str}
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._s = DEFAULT_TOKENS.sizing
        self.result_info = None
        self._worker = None
        self._video_path = ""
        self._build_ui()

    # -- UI 构建 -------------------------------------------------------------
    def _build_ui(self) -> None:
        self.setWindowTitle(labels.ANNOT_VIDEO_DIALOG_TITLE)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(
            self._s.VIDEO_DIALOG_MARGIN, self._s.VIDEO_DIALOG_MARGIN,
            self._s.VIDEO_DIALOG_MARGIN, self._s.VIDEO_DIALOG_MARGIN,
        )
        lay.setSpacing(self._s.VIDEO_DIALOG_SPACING)

        # 视频文件行：只读输入框 + 浏览按钮
        file_row = QHBoxLayout()
        file_row.setSpacing(self._s.VIDEO_DIALOG_FIELD_GAP)
        file_lb = QLabel(labels.ANNOT_VIDEO_FILE_LABEL)
        file_lb.setObjectName("dcPanelTitle")
        file_row.addWidget(file_lb)
        self._file_edit = QLineEdit()
        self._file_edit.setObjectName("dcFilterCombo")
        self._file_edit.setReadOnly(True)
        self._file_edit.setPlaceholderText(labels.ANNOT_VIDEO_NO_FILE)
        file_row.addWidget(self._file_edit, 1)
        browse_btn = QPushButton(labels.ANNOT_VIDEO_BROWSE)
        browse_btn.setObjectName("dcGhostBtn")
        browse_btn.clicked.connect(self._on_browse)
        file_row.addWidget(browse_btn)
        lay.addLayout(file_row)

        # 视频信息预览（选择文件后自动探测填充）
        self._info_lb = QLabel(labels.ANNOT_VIDEO_NO_FILE)
        self._info_lb.setObjectName("dcTrainHint")
        lay.addWidget(self._info_lb)

        # 目标系列 + 抽帧间隔
        opt_row = QHBoxLayout()
        opt_row.setSpacing(self._s.VIDEO_DIALOG_FIELD_GAP)
        opt_row.addWidget(self._make_field_label(labels.ANNOT_VIDEO_SERIES_LABEL))
        self._series_combo = QComboBox()
        self._series_combo.setObjectName("dcFilterCombo")
        self._series_combo.addItems([
            labels.ANNOT_VIDEO_SERIES_A,
            labels.ANNOT_VIDEO_SERIES_FP,
        ])
        opt_row.addWidget(self._series_combo)
        opt_row.addSpacing(self._s.VIDEO_DIALOG_OPT_GAP)
        opt_row.addWidget(self._make_field_label(labels.ANNOT_VIDEO_STEP_LABEL))
        self._step_spin = QSpinBox()
        self._step_spin.setObjectName("dcFilterCombo")
        self._step_spin.setRange(
            self._s.VIDEO_STEP_MIN, self._s.VIDEO_STEP_MAX)
        self._step_spin.setValue(self._s.VIDEO_STEP_DEFAULT)
        opt_row.addWidget(self._step_spin, 1)
        lay.addLayout(opt_row)

        # 进度条（抽取中显示）
        self._progress = QProgressBar()
        self._progress.setObjectName("dcTrainProgress")
        self._progress.setRange(0, self._s.VIDEO_PROGRESS_MAX)
        self._progress.setValue(0)
        self._progress.setVisible(False)
        lay.addWidget(self._progress)

        # 按钮行：开始抽取 / 取消
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self._start_btn = QPushButton(labels.ANNOT_VIDEO_START)
        self._start_btn.setObjectName("dcPrimaryBtn")
        self._start_btn.clicked.connect(self._on_start)
        btn_row.addWidget(self._start_btn)
        self._cancel_btn = QPushButton(labels.ANNOT_CANCEL_BTN)
        self._cancel_btn.setObjectName("dcGhostBtn")
        self._cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self._cancel_btn)
        lay.addLayout(btn_row)

    @staticmethod
    def _make_field_label(text: str) -> QLabel:
        lb = QLabel(text)
        lb.setObjectName("dcPanelTitle")
        return lb

    # -- 交互 ----------------------------------------------------------------
    def _on_browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, labels.ANNOT_VIDEO_DIALOG_TITLE, "",
            "Video (*.mp4 *.avi *.mkv *.mov *.flv);;All (*.*)",
        )
        if not path:
            return
        self._video_path = path
        self._file_edit.setText(os.path.basename(path))
        self._probe_info()

    def _probe_info(self) -> None:
        from ml import datasets_extract
        try:
            info = datasets_extract.probe_video(self._video_path)
        except Exception as exc:  # noqa: BLE001 视频解析失败仅提示，不崩溃
            self._info_lb.setText(labels.ANNOT_VIDEO_PROBE_FAILED.format(reason=exc))
            return
        self._info_lb.setText(labels.ANNOT_VIDEO_INFO_TEMPLATE.format(**info))

    def _on_start(self) -> None:
        if not self._video_path:
            self._info_lb.setText(labels.ANNOT_VIDEO_NO_FILE)
            return
        step = self._step_spin.value()
        if step < 1:
            self._info_lb.setText(labels.ANNOT_VIDEO_EMPTY_STEP)
            return
        series = ("A", "FP")[self._series_combo.currentIndex()]
        self._start_btn.setEnabled(False)
        self._cancel_btn.setEnabled(False)
        self._progress.setVisible(True)
        self._progress.setValue(0)
        self._info_lb.setText(labels.ANNOT_VIDEO_RUNNING.format(done=0, total=0))
        self._worker = _VideoExtractWorker(self._video_path, series, step, self)
        self._worker.progress.connect(self._on_progress)
        self._worker.succeeded.connect(self._on_succeeded)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_progress(self, done: int, total: int) -> None:
        if total > 0:
            self._progress.setValue(
                int(done * self._s.VIDEO_PROGRESS_MAX // total))
        self._info_lb.setText(labels.ANNOT_VIDEO_RUNNING.format(done=done, total=total))

    def _on_succeeded(self, result: dict) -> None:
        self.result_info = result
        self._info_lb.setText(labels.ANNOT_VIDEO_DONE.format(
            saved=result.get("saved", 0), dir=result.get("target_dir", "")))
        self.accept()

    def _on_failed(self, reason: str) -> None:
        self._start_btn.setEnabled(True)
        self._cancel_btn.setEnabled(True)
        self._progress.setVisible(False)
        self._info_lb.setText(labels.ANNOT_VIDEO_PROBE_FAILED.format(reason=reason))