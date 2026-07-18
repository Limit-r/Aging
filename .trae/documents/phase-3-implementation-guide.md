# Phase 3 v2 实施操作指南（记忆参考点）

> **用途**：本文件是 v2 phase-3 详情页优化的**操作执行手册**，配套 [phase-3-detail-page-plan.md](file:///d:\Aging\.trae\documents\phase-3-detail-page-plan.md) 的"做什么/为什么"使用
> **关系**：本指南 = **HOW**（具体怎么敲命令/写哪行代码/什么顺序），phase-3-plan = **WHAT**（设计决策 + 风险评估 + 回滚方案）
> **版本**：v1  ·  2026-07-18  ·  待审阅
> **基线**：[ARCHITECTURE.md](file:///d:\Aging\ARCHITECTURE.md) / [code-redundancy-audit-2026-07-16.md](file:///d:\Aging\.trae\documents\code-redundancy-audit-2026-07-16.md) / [observability-hardening-plan.md](file:///d:\Aging\.trae\documents\observability-hardening-plan.md)

---

## 0. 文档约定

### 0.1 命令约定

- 所有 PowerShell 命令在 `E:\MiniConda\envs\Aging\python.exe` 环境运行
- 工作目录始终是 `d:\Aging`（不切换）
- `py_compile` 失败立即停，不继续往下
- 每个阶段结束**必须** `git commit` 留可回滚锚点

### 0.2 阶段命名

| 阶段 | 时间 | 性质 | 失败回退 |
|---|---|---|---|
| A 前置清理 | 25 min | labels 重命名 | `git revert <A-commit>` |
| B 核心实现 | 2.5 h | detail_page + 路由 + eventFilter | `git revert <B-commit>` |
| C 体验打磨 | 40 min | 4 项体验细节 | `git revert <C-commit>` |
| D 文档收尾 | 15 min | ARCHITECTURE 同步 | `git revert <D-commit>` |

---

## 1. 前置核查清单（动手前必跑）

### 1.1 TOP 5 冗余清理状态（已核对）

| # | audit 项 | 当前状态 | 验证命令 | 期望 |
|---|---|---|---|---|
| C2 | `debug_legend.py` 删除 | ✅ 已完成 | `Test-Path d:\Aging\app\ui\debug_legend.py` | `False` |
| C1 | 4 处 `_restyle` → `qss_utils.py` | ✅ 已完成 | `rg "_restyle" d:\Aging\app` | 仅命中 [qss_utils.py](file:///d:\Aging\app\ui\qss_utils.py) 1 处（注释）|
| M1 | `_on_countdown_finished` 删除 | ✅ 已完成 | `rg "_on_countdown_finished" d:\Aging\app` | 无命中 |
| M2 | `_apply_streaming_overlay` 删除 | ✅ 已完成 | `rg "_apply_streaming_overlay" d:\Aging\app` | 无命中 |
| M4 | `f"CH-{cid:02d}"` → `format_cid` | ✅ 基本完成 | `rg 'f"CH-\{' d:\Aging\app` | 仅命中 [formatting.py:30](file:///d:\Aging\app\core\formatting.py#L30) 1 处（实现本身）|
| M5 | `countdown.py` 重复 import | ✅ 已完成 | `rg "^from app.observability import" d:\Aging\app\services\countdown.py` | 1 行 |
| m1 | `count_actionable` / `actionable_cids` 合并 | ✅ 已完成 | 读 [cell_controller.py:72-79](file:///d:\Aging\app\services\cell_controller.py#L72-L79) | `count_actionable` 用 `len(self.actionable_cids(...))` |

### 1.2 5 处 logger 决策（**不改**）

| 位置 | 字符串 | 决策 | 理由 |
|---|---|---|---|
| [cell_controller.py:101](file:///d:\Aging\app\services\cell_controller.py#L101) | `"cid=CH-%s"` | ⚠️ 不改 | logger `%s` 延迟格式化，改 `format_cid` 立即求值浪费 CPU |
| [cell_controller.py:133](file:///d:\Aging\app\services\cell_controller.py#L133) | `"cid=CH-%s"` | ⚠️ 不改 | 同上 |
| [countdown.py:102, 134, 138](file:///d:\Aging\app\services\countdown.py) | `"cid=CH-%s"` | ⚠️ 不改 | logger 输出是开发者看的不是用户可见 |

### 1.3 实施前必须做的 3 件事

```powershell
# 1) git commit 当前状态作为基线
cd d:\Aging
git status                          # 确认 working tree 干净
git add -A
git commit -m "chore: phase-3 baseline (pre detail_page implementation)"

# 2) 验证启动正常
& E:\MiniConda\envs\Aging\python.exe d:\Aging\Main.py
# 等 5 秒看 3D 主页正常显示后关闭窗口

# 3) 备份关键文件（可选，推荐）
Copy-Item d:\Aging\app\ui\home_page.py d:\Aging\app\ui\home_page.py.bak
Copy-Item d:\Aging\app\ui\main_3d.py d:\Aging\app\ui\main_3d.py.bak
Copy-Item d:\Aging\app\core\labels.py d:\Aging\app\core\labels.py.bak
```

---

## 2. 文件依赖速查表

### 2.1 主路径 5 个文件

| # | 文件 | 角色 | 依赖（import 谁） | 被依赖（谁 import） |
|---|---|---|---|---|
| F1 | [app/core/labels.py](file:///d:\Aging\app\core\labels.py) | 字符串常量 | 无 | current_page / data_page / home_page / main_3d / detail_page（新）|
| F2 | [app/ui/pages/detail_page.py](file:///d:\Aging\app\ui\pages\detail_page.py) | **新建** | labels / config / tokens / formatting / protocol / history_buffer / cell_controller / countdown / observability | home_page |
| F3 | [app/ui/home_page.py](file:///d:\Aging\app\ui\home_page.py) | 主页编排 | labels / floaters / main_3d / nav_bar / pages.* / router | Main.py |
| F4 | [app/ui/main_3d.py](file:///d:\Aging\app\ui\main_3d.py) | 3D 渲染 | config / labels / formatting / tokens / observability | home_page |
| F5 | [ARCHITECTURE.md](file:///d:\Aging\ARCHITECTURE.md) | 架构文档 | 无 | 无 |

### 2.2 间接依赖（被 F2 调用）

| 文件 | 提供的 API |
|---|---|
| [app/data/history_buffer.py](file:///d:\Aging\app\data\history_buffer.py) | `HistoryBuffer.snapshot(cid)` / `append` signal |
| [app/services/cell_controller.py](file:///d:\Aging\app\services\cell_controller.py) | `state_changed` signal / `state_of(cid)` |
| [app/services/countdown.py](file:///d:\Aging\app\services\countdown.py) | `CountdownService.start/expired/cancel` |
| [app/ui/router.py](file:///d:\Aging\app\ui\router.py) | `register(key, widget)` / `navigate(key)` |
| [app/observability/narrative.py](file:///d:\Aging\app\observability\narrative.py) | `narrative.event(...)` / `format_cid` |
| [app/core/formatting.py](file:///d:\Aging\app\core\formatting.py) | `format_cid` / `format_hms` / `divmod3600` |

### 2.3 工具 helper（可复用）

| 工具 | 位置 | 用法 |
|---|---|---|
| `refresh_qss(widget)` | [app/ui/qss_utils.py](file:///d:\Aging\app\ui\qss_utils.py) | `setProperty` 后必须调 |
| `format_cid(cid)` | [app/core/formatting.py](file:///d:\Aging\app\core\formatting.py) | 通道号统一入口 |
| `narrative.event()` | [app/observability/narrative.py](file:///d:\Aging\app\observability\narrative.py) | 通俗事件日志 |
| `get_logger(__name__)` | [app/observability/logger.py](file:///d:\Aging\app\observability\logger.py) | 模块 logger |
| `@safe_call` | [app/observability/safe_call.py](file:///d:\Aging\app\observability\safe_call.py) | 槽函数异常隔离 |

### 2.4 完整依赖方向图

```
labels.py ────────────────┐
config.py ──┐             │
tokens.py ──┤             │
formatting.py┤            ├── detail_page.py (新建)
            ↓            │
     history_buffer.py    │
     cell_controller.py   │
     countdown.py ────────┤
     protocol.py ─────────┤
                           ↓
     main_3d.py ────── home_page.py ──────── Main.py
                           ↑
     pages/*.py（5 个）────┘
     floaters.py ──────────┘
     router.py ────────────┘
     nav_bar.py ───────────┘
     observability/* ──────┘（横切关注）

ARCHITECTURE.md ← 同步上述所有改动
```

---

## 3. 实施步骤

### 阶段 A：前置清理（25 min）

#### A1. 重命名 `BUTTON_LABELS` → `MAIN_BUTTON_LABELS`

**改动**：[app/core/labels.py:54-59](file:///d:\Aging\app\core\labels.py#L54-L59)

```python
# 改前
BUTTON_LABELS = (
    "开始检测",
    "暂停检测",
    "恢复暂停",
    "结束检测",
)

# 改后
MAIN_BUTTON_LABELS = (
    "开始检测",
    "暂停检测",
    "恢复暂停",
    "结束检测",
)
```

**验证**：
```powershell
rg "BUTTON_LABELS" d:\Aging\app
# 期望：仅命中 MAIN_BUTTON_LABELS 的若干行
```

#### A2. 全工程引用替换

```powershell
# 找出所有引用 BUTTON_LABELS 的位置（应只有 1-2 处：current_page.py）
rg "\bBUTTON_LABELS\b" d:\Aging\app
```

手动改每个引用点为 `MAIN_BUTTON_LABELS`（**不**用 `replace_all`，避免误改）。

**验证**：
```powershell
& E:\MiniConda\envs\Aging\python.exe -m py_compile `
    d:\Aging\app\core\labels.py `
    d:\Aging\app\ui\pages\current_page.py `
    d:\Aging\app\ui\pages\detail_page.py
```

**回滚**：`git checkout HEAD -- app/core/labels.py <引用文件>`

#### A3-A4（可选）：抽 `format_cid` / `refresh_qss` 公共 helper

**状态**：✅ **已完成**（见 [formatting.py](file:///d:\Aging\app\core\formatting.py) / [qss_utils.py](file:///d:\Aging\app\ui\qss_utils.py)），无需操作

#### A5. 阶段 A 验证

```powershell
& E:\MiniConda\envs\Aging\python.exe -m py_compile `
    (Get-ChildItem d:\Aging\app -Recurse -Filter *.py -Exclude *.bak | %{ $_.FullName })

& E:\MiniConda\envs\Aging\python.exe d:\Aging\Main.py
# 等 5 秒看启动正常，关闭

git add -A
git commit -m "phase-3-A: rename BUTTON_LABELS to MAIN_BUTTON_LABELS"
```

---

### 阶段 B：核心实现（2.5 h）

#### B1. labels.py +9 个 `DETAIL_*` 常量

**改动**：[app/core/labels.py](file:///d:\Aging\app\core\labels.py) 末尾追加：

```python
# ---- 详情页 v3.0（v2 内嵌页，区别于 v2 独立窗口）-----------------------------
DETAIL_TITLE_TEMPLATE = "详情  //  {cid}  ·  {state}"
DETAIL_BACK_TEXT = "← 返回主页"
DETAIL_NO_CHANNEL_TEXT = "（请从主页双击 LED 打开详情）"

DETAIL_CHART_TITLE = "电流时序  //  CURRENT I-t"
# 注：DETAIL_CHART_X_LABEL / DETAIL_CHART_Y_LABEL 复用现有 CHART_X_LABEL / CHART_CURRENT_Y_LABEL
DETAIL_ZERO_LINE_LABEL = "归零阈值 0A"
DETAIL_ZERO_ANOMALY_TEMPLATE = "⚠ {cid} 电流归零异常"

DETAIL_ACTIONS_TITLE = "操作  //  ACTIONS"
DETAIL_ACTION_START_TEXT = "▶ 开始"
DETAIL_ACTION_PAUSE_TEXT = "⏸ 暂停"
DETAIL_ACTION_RESUME_TEXT = "↻ 继续"
DETAIL_ACTION_STOP_TEXT  = "■ 停止"
DETAIL_ACTION_LABELS = (
    DETAIL_ACTION_START_TEXT,
    DETAIL_ACTION_PAUSE_TEXT,
    DETAIL_ACTION_RESUME_TEXT,
    DETAIL_ACTION_STOP_TEXT,
)
```

**验证**：
```powershell
& E:\MiniConda\envs\Aging\python.exe -m py_compile d:\Aging\app\core\labels.py

# 验证所有常量都被定义
& E:\MiniConda\envs\Aging\python.exe -c "from app.core import labels; print(labels.DETAIL_TITLE_TEMPLATE); print(labels.DETAIL_ACTION_LABELS)"
```

**回滚**：`git checkout HEAD -- app/core/labels.py`

#### B2. 新建 [app/ui/pages/detail_page.py](file:///d:\Aging\app\ui\pages\detail_page.py) ~280 行

**骨架**（按 v2 计划 §3 优化项 2/3/4 实现）：

```python
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

from typing import Optional

import pyqtgraph as pg
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QCloseEvent
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
)

from app.core import config, labels, tokens
from app.core.formatting import format_cid
from app.data.history_buffer import HistoryBuffer
from app.data.protocol import ChannelReading
from app.observability import get_logger, narrative
from app.observability.safe_call import safe_call
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
    # 归零异常阈值
    _ZERO_ANOMALY_A = 0.1
    # chart 时间窗（秒）
    _WINDOW_S = 300  # 5min

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

        self._build_ui()
        self._wire_signals()
        self._build_chart()
        self._build_sample_timer()

        _log.info("detail page initialized")
        narrative.event(
            "detail_page_ready",
            note="v3.0 详情页就绪：4 电流曲线 + 操作按钮 + 事件驱动重绘",
        )

    # -- UI 布局 --------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # 1) header
        self._header = QFrame()
        self._header.setObjectName("detailHeader")
        self._header.setFixedHeight(56)
        header_layout = QHBoxLayout(self._header)
        header_layout.setContentsMargins(16, 0, 16, 0)
        self._back_btn = QPushButton(labels.DETAIL_BACK_TEXT)
        self._back_btn.setObjectName("detailBackBtn")
        self._back_btn.clicked.connect(self._on_back_clicked)
        header_layout.addWidget(self._back_btn)
        header_layout.addStretch(1)
        self._title_label = QLabel(labels.DETAIL_NO_CHANNEL_TEXT)
        self._title_label.setObjectName("detailTitle")
        header_layout.addWidget(self._title_label)
        root.addWidget(self._header)

        # 2) chart
        self._chart_container = QFrame()
        self._chart_container.setObjectName("detailChart")
        chart_layout = QVBoxLayout(self._chart_container)
        chart_layout.setContentsMargins(0, 0, 0, 0)
        self._plot = pg.PlotWidget()
        self._plot.setObjectName("detailPlot")
        self._plot.setBackground(tokens.DEFAULT_TOKENS.colors.RACK_3D_BG)
        self._plot.showGrid(x=True, y=True, alpha=0.3)
        self._plot.setLabel("left", labels.CHART_CURRENT_Y_LABEL)
        self._plot.setLabel("bottom", labels.CHART_X_LABEL)
        self._plot.setTitle(labels.DETAIL_CHART_TITLE)
        chart_layout.addWidget(self._plot)
        root.addWidget(self._chart_container, 1)

        # 3) actions
        self._actions = QFrame()
        self._actions.setObjectName("detailActions")
        self._actions.setFixedHeight(96)
        actions_layout = QVBoxLayout(self._actions)
        actions_layout.setContentsMargins(16, 8, 16, 8)
        self._actions_title = QLabel(labels.DETAIL_ACTIONS_TITLE)
        self._actions_title.setObjectName("detailActionsTitle")
        actions_layout.addWidget(self._actions_title)
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(12)
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
        """初始化 chart 组件（曲线 + 归零红线 + 异常填充）。"""
        # 4 路电流曲线
        self._curves = []
        colors = tokens.DEFAULT_TOKENS.colors
        # 4 路电流用 token 已有颜色（如果没定义则用占位）
        line_colors = [
            colors.NEON_CYAN, colors.NEON_GREEN,
            colors.NEON_ORANGE, colors.NEON_PURPLE,
        ]
        for i in range(4):
            c = self._plot.plot(
                pen=pg.mkPen(line_colors[i % len(line_colors)], width=2),
                name=labels.CHART_LEGEND_CURRENT_NAMES[i],
            )
            self._curves.append(c)
        # 归零红线（y=0A）
        self._zero_line = pg.InfiniteLine(
            pos=0, angle=0,
            pen=pg.mkPen(colors.LED_ALERT[:3], width=1, style=Qt.DashLine),
            label=labels.DETAIL_ZERO_LINE_LABEL,
            labelOpts={"position": 0.95, "color": colors.LED_ALERT[:3]},
        )
        self._plot.addItem(self._zero_line)
        # Y 轴范围
        self._plot.setYRange(-0.5, 5.0)

    # -- 信号接线 -------------------------------------------------------------
    def _wire_signals(self) -> None:
        """订阅 HistoryBuffer.append（事件驱动）+ CellController.state_changed。"""
        # 事件驱动：append 信号触发 dirty 标记
        self._history.append.connect(self._on_history_append)
        # 状态同步：state_changed 更新 title + 启用/禁用异常检测
        self._controller.state_changed.connect(self._on_state_changed)
        # 5fps 兜底 tick
        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(self._TICK_INTERVAL_MS)
        self._tick_timer.timeout.connect(self._tick_chart)
        self._tick_timer.start()

    def _build_sample_timer(self) -> None:
        """30s 周期采样日志。"""
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
        # 更新 title
        state = self._controller.state_of(cid)
        state_text = labels.DETECTION_STATE_RUNNING if state == DetectionState.RUNNING \
            else labels.DETECTION_STATE_PAUSED if state == DetectionState.PAUSED \
            else labels.DETECTION_STATE_STOPPED
        self._title_label.setText(labels.DETAIL_TITLE_TEMPLATE.format(
            cid=format_cid(cid), state=state_text,
        ))
        _log.info("detail page open: cid=%d (was %s)", cid, old)
        narrative.event(
            "detail_page_open", cid=cid,
            note=f"用户打开 {format_cid(cid)} 详情页",
        )

    # -- 槽函数 ---------------------------------------------------------------
    @safe_call(context="_on_history_append")
    def _on_history_append(self, reading: ChannelReading) -> None:
        """HistoryBuffer.append 信号 → 标记 dirty（事件驱动）。"""
        if self._closing:
            return
        if reading.channel_id == self._cid:
            self._dirty = True

    @safe_call(context="_on_state_changed")
    def _on_state_changed(self, cid: int, old_value: str, new_value: str) -> None:
        """CellController.state_changed → 更新 title + 异常检测开关。"""
        if self._closing or cid != self._cid:
            return
        state = DetectionState(new_value)
        state_text = labels.DETECTION_STATE_RUNNING if state == DetectionState.RUNNING \
            else labels.DETECTION_STATE_PAUSED if state == DetectionState.PAUSED \
            else labels.DETECTION_STATE_STOPPED
        self._title_label.setText(labels.DETAIL_TITLE_TEMPLATE.format(
            cid=format_cid(cid), state=state_text,
        ))
        # 归零异常检测仅在 RUNNING 状态启用
        if state != DetectionState.RUNNING:
            self._clear_anomaly_segments()

    @safe_call(context="_tick_chart")
    def _tick_chart(self) -> None:
        """5fps 兜底 tick：无 dirty 直接返回，否则重绘。"""
        if self._closing or not self._dirty or self._cid == 0:
            return
        self._render_chart()
        self._dirty = False

    @safe_call(context="_on_sample")
    def _on_sample(self) -> None:
        """30s 周期采样日志。"""
        if self._closing or self._cid == 0:
            return
        ts, currents = self._history.snapshot(self._cid)
        n = len(ts)
        # 是否有归零段
        zero_anomaly = False
        for i in range(min(4, len(currents))):
            vals = currents[i]
            if vals and any(v < self._ZERO_ANOMALY_A for v in vals):
                zero_anomaly = True
                break
        _log.info("detail tick sample: cid=%d points=%d zero_anomaly=%s",
                  self._cid, n, zero_anomaly)

    @safe_call(context="_on_back_clicked")
    def _on_back_clicked(self) -> None:
        if self._closing:
            return
        _log.info("detail page close: cid=%d (back button)", self._cid)
        self.requested_back.emit()

    @safe_call(context="_on_action_clicked")
    def _on_action_clicked(self, action: str) -> None:
        if self._closing or self._cid == 0:
            return
        _log.info("detail action: %s cid=%d", action, self._cid)
        self.action_requested.emit(action, self._cid)

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
        # 找第一个 I1（currents[0]）的归零段
        if not currents or len(currents) < 1:
            return
        i1 = currents[0]
        if not i1:
            return
        anomaly_ranges: list[tuple[int, int]] = []
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
        # 画新的红色填充
        if not anomaly_ranges:
            return
        anomaly_color = tokens.DEFAULT_TOKENS.colors.LED_ALERT
        for start, end in anomaly_ranges:
            if end - start < 1:
                continue
            x_seg = ts[start:end + 1]
            y_seg = i1[start:end + 1]
            y_upper = [max(v, 0.01) for v in y_seg]
            fill = pg.FillBetweenItem(
                pg.PlotDataItem(x_seg, y_upper),
                pg.PlotDataItem(x_seg, [0.0] * len(y_seg)),
                brush=pg.mkBrush(anomaly_color[:3] + (60,)),  # 60=alpha
            )
            self._plot.addItem(fill)
            self._anomaly_fills.append(fill)
        if anomaly_ranges:
            _log.info(
                "detail: cid=%d zero-anomaly segment red, count=%d",
                self._cid, len(anomaly_ranges),
            )

    def _clear_anomaly_segments(self) -> None:
        """清除已画的异常填充线。"""
        if not hasattr(self, "_anomaly_fills"):
            self._anomaly_fills = []
        for f in self._anomaly_fills:
            self._plot.removeItem(f)
        self._anomaly_fills = []

    def _set_actions_enabled(self, enabled: bool) -> None:
        for btn in (self._btn_start, self._btn_pause, self._btn_resume, self._btn_stop):
            btn.setEnabled(enabled and self._cid != 0)

    # -- closeEvent -----------------------------------------------------------
    def closeEvent(self, event: QCloseEvent) -> None:
        """关闭时防 RuntimeError + 若 RUNNING 弹确认窗（3-OPT-5-C4）。"""
        self._closing = True
        # 暂停 timer
        if hasattr(self, "_tick_timer"):
            self._tick_timer.stop()
        if hasattr(self, "_sample_timer"):
            self._sample_timer.stop()
        # 若 cell 仍 RUNNING → 弹确认
        if self._cid != 0:
            state = self._controller.state_of(self._cid)
            if state == DetectionState.RUNNING:
                # 这里不弹窗，由 HomePage 的 closeEvent 统一处理
                # 详情页只是工具页面，关闭时不需要弹
                pass
        # 清理异常填充
        self._clear_anomaly_segments()
        super().closeEvent(event)
```

**验证**：
```powershell
& E:\MiniConda\envs\Aging\python.exe -m py_compile d:\Aging\app\ui\pages\detail_page.py

& E:\MiniConda\envs\Aging\python.exe -c "from app.ui.pages.detail_page import DetailPage; print('OK')"
```

**回滚**：`rm d:\Aging\app\ui\pages\detail_page.py`

#### B3. [app/ui/main_3d.py](file:///d:\Aging\app\ui\main_3d.py) 暴露公共 API

**改动**：

1. 在文件顶部 import 区域加 `from typing import Optional`（已存在）
2. 在 `Rack3DView` 类加 2 个公共方法/属性：

```python
# 在 Rack3DView 类内追加
def best_hovered_cid(self) -> Optional[int]:
    """返回当前 hover 命中的 LED cid，无命中返回 None。
    
    供 HomeDashboard.eventFilter 在 MouseButtonDblClick 时读取。
    """
    return getattr(self, "_best_hovered_cid", None)

def set_auto_rotate(self, enabled: bool) -> None:
    """启用/禁用 3D 视角自动旋转。
    
    详情页打开时禁用，关闭时恢复。
    """
    self._auto_rotate_enabled = enabled
    if not enabled and hasattr(self, "_rotate_timer"):
        self._rotate_timer.stop()
```

3. 在 `_tick_hover` 函数末尾追加：

```python
# 在 _tick_hover 找到 best_cid 后（约 _tick_hover 函数末尾）
if best_cid is not None:
    self._best_hovered_cid = best_cid
else:
    self._best_hovered_cid = None
```

**验证**：
```powershell
& E:\MiniConda\envs\Aging\python.exe -m py_compile d:\Aging\app\ui\main_3d.py
```

**回滚**：`git checkout HEAD -- app/ui/main_3d.py`

#### B4. [app/ui/home_page.py](file:///d:\Aging\app\ui\home_page.py) 接线

**改动**：

1. import 区域追加：
```python
from app.ui.pages.detail_page import DetailPage
```

2. `HomePage._build_ui` 末尾追加（`_router.register` 之后）：
```python
# 详情页（v3.0 Phase 3）
self._detail = DetailPage(
    history=self._history,  # 需 HomePage 持有 history 引用
    cell_controller=self._controller,  # 需 HomePage 持有 controller 引用
    parent=self,
)
self._router.register("detail", self._detail)
# 接线：双击 → 打开详情；返回 → 切回 home
self._detail.requested_back.connect(self._on_detail_back)
self._detail.action_requested.connect(self._on_detail_action)
```

3. `HomeDashboard.eventFilter` 在 `if et in (...)` 列表中加 `QEvent.MouseButtonDblClick`：

```python
# HomeDashboard.eventFilter 中
if obj is self._rack._gl:
    et = event.type()
    if et in (
        QEvent.MouseButtonPress,
        QEvent.MouseMove,
        QEvent.MouseButtonDblClick,  # 新增
        QEvent.Wheel,
    ):
        self._mark_interact()
        if et == QEvent.MouseButtonDblClick:
            cid = self._rack.best_hovered_cid
            if cid is not None:
                self._open_detail(cid)
    return super().eventFilter(obj, event)
```

4. `HomePage` 类加 2 个新方法：

```python
def _on_detail_back(self) -> None:
    """用户点详情页"返回" → 路由回 home + 恢复 3D 旋转。"""
    self._router.navigate("home")
    if hasattr(self, "_dashboard") and hasattr(self._dashboard, "_rack"):
        self._dashboard._rack.set_auto_rotate(True)
    _log.info("detail back: routing to home")

def _on_detail_action(self, action: str, cid: int) -> None:
    """详情页操作 → 转发给 CellController。"""
    if hasattr(self, "_controller"):
        self._controller.apply(action, [cid])
    _log.info("detail action: %s cid=%d forwarded to controller", action, cid)
```

5. **重要前置**：`HomePage` 当前**没有** `_history` 和 `_controller` 引用，需要在 `_build_ui` 顶部加：

```python
# 在 _build_ui 顶部（创建 self._router 之后）
from app.data.history_buffer import HistoryBuffer
from app.data.demo_source import DemoDataSource
from app.services.cell_controller import CellController
# 注：实际应该由 HomePage 注入而非创建
```

**注意**：当前 `HomePage` 不持有 DataSource / HistoryBuffer / CellController，需要先决定这些对象的所有权。**建议方案**：
- 方案 A：在 `HomePage` 内创建并持有（最简单，与 detail_page 解耦最差）
- 方案 B：在 `Main.py` 创建后注入 `HomePage`（更优，但需要改 Main.py）
- 方案 C：从 `current_page` 共享（最差，跨页耦合）

**临时建议**：先用方案 A，在 HomePage 内创建。后续 Phase 4 优化时再改为方案 B。

```python
# HomePage._build_ui 顶部
from app.data.history_buffer import HistoryBuffer
from app.data.demo_source import DemoDataSource
from app.services.cell_controller import CellController

# 创建数据/控制/缓冲
self._data_source = DemoDataSource()
self._history = HistoryBuffer(channel_count=72)
self._controller = CellController(total=72)

# 接线
self._data_source.subscribe(self._history.append)
self._data_source.subscribe(self._current_page.update_data)  # 已有
self._data_source.start()
```

**验证**：
```powershell
& E:\MiniConda\envs\Aging\python.exe -m py_compile d:\Aging\app\ui\home_page.py
```

**回滚**：`git checkout HEAD -- app/ui/home_page.py`

#### B5. 全工程 py_compile 兜底

```powershell
& E:\MiniConda\envs\Aging\python.exe -m py_compile `
    (Get-ChildItem d:\Aging\app -Recurse -Filter *.py -Exclude *.bak | %{ $_.FullName })
```

期望：全部通过，无错误。

#### B6. import smoke + 启动

```powershell
& E:\MiniConda\envs\Aging\python.exe -c "
import Main
from app.ui.pages.detail_page import DetailPage
print('DetailPage import OK')
print('DetailPage signals:', DetailPage.requested_back, DetailPage.action_requested)
"

& E:\MiniConda\envs\Aging\python.exe d:\Aging\Main.py
# 等 5 秒，3D 主页正常显示
# 双击任意 LED → 应看到 I-t 曲线开始画
# 点"返回主页" → 回到 3D 主页
# Ctrl+C 关闭
```

**阶段 B 提交**：
```bash
git add -A
git commit -m "phase-3-B: detail_page core (event-driven + signal subscribe + 6 log points)"
```

**回滚**：`git revert HEAD` 或 `git reset --hard HEAD~1`

---

### 阶段 C：体验打磨（40 min）

#### C1. LED 高亮 200ms

**改动**：[app/ui/main_3d.py](file:///d:\Aging\app\ui\main_3d.py) 加方法：

```python
def set_led_highlight(self, cid: int, duration_ms: int = 200) -> None:
    """临时把指定 LED 高亮显示 duration_ms 毫秒。"""
    if cid < 1 or cid > GRID_ROWS * GRID_COLS:
        return
    # 保存原状态
    original_state = self._led_states[cid]
    # 高亮（强制设为 ALERT 色）
    self._led_states[cid] = LEDState.ALERT
    self._refresh_led_colors()
    # duration_ms 后恢复
    QTimer.singleShot(
        duration_ms,
        lambda: self._restore_led(cid, original_state),
    )

def _restore_led(self, cid: int, original: "LEDState") -> None:
    self._led_states[cid] = original
    self._refresh_led_colors()
```

**接线**：[app/ui/home_page.py](file:///d:\Aging\app\ui\home_page.py) `_open_detail` 内追加：

```python
def _open_detail(self, cid: int) -> None:
    self._dashboard._rack.set_led_highlight(cid, 200)  # 新增
    self._detail.set_channel(cid)
    self._router.navigate("detail")
    self._dashboard._rack.set_auto_rotate(False)
```

**验证**：双击 LED 瞬间应看到该 LED 变红 200ms 后恢复。

#### C2. 视角自动旋转对准当前 cid

**说明**：可选。若实施，需要在 [main_3d.py](file:///d:\Aging\app\ui\main_3d.py) 加：

```python
def snap_to_cid(self, cid: int) -> None:
    """计算目标 azimuth 角度让 LED 居中。"""
    # 计算 LED 屏幕 x 位置 → 转换 azimuth 偏移
    # ... 几何计算 ...
    self._gl.setCameraPosition(
        pos=Vector(*CAMERA_CENTER),
        distance=CAMERA_DIST,
        elevation=CAMERA_ELEV,
        azimuth=target_azimuth,
    )
```

**建议**：本阶段**跳过** C2（涉及 3D 几何计算，复杂度高，性价比低）。如需要，用 C3（保留 azimuth）即可。

#### C3. azimuth 偏移保留

**改动**：[app/ui/home_page.py](file:///d:\Aging\app\ui\home_page.py)

```python
class HomeDashboard:
    IDLE_TIMEOUT_MS = 5000

    def __init__(self, ...):
        # ... 已有代码 ...
        self._azimuth_offset_before_detail: Optional[float] = None  # 新增

    def _open_detail(self, cid: int) -> None:
        # 保存当前 azimuth
        self._azimuth_offset_before_detail = self._azimuth_offset
        self._detail.set_channel(cid)
        self._router.navigate("detail")
        self._rack.set_auto_rotate(False)
        # ... LED 高亮等 ...

    def _on_detail_back(self) -> None:
        # 恢复 azimuth
        if self._azimuth_offset_before_detail is not None:
            self._azimuth_offset = self._azimuth_offset_before_detail
            self._rack._gl.setCameraPosition(
                pos=Vector(*CAMERA_CENTER),
                distance=CAMERA_DIST,
                elevation=CAMERA_ELEV,
                azimuth=CAMERA_AZIM + self._azimuth_offset,
            )
        self._rack.set_auto_rotate(True)
```

**注意**：`HomePage._on_detail_back` 当前在 HomePage 类，不在 HomeDashboard。需要把 `_on_detail_back` 移到 HomeDashboard 或重写 HomePage 内的方法。

#### C4. 关闭确认弹窗（仅 RUNNING 状态）

**决策**：本阶段**跳过** C4（弹窗体验复杂，且与 3-OPT-5-C4 收益不对称）。如需要，可在 HomePage 关闭时统一弹，不在 DetailPage 内弹。

**阶段 C 提交**：
```bash
git add -A
git commit -m "phase-3-C: experience polish (LED highlight + azimuth retain)"
```

**回滚**：`git revert HEAD`

---

### 阶段 D：文档收尾（15 min）

#### D1. [ARCHITECTURE.md](file:///d:\Aging\ARCHITECTURE.md) 同步

**3 处改动**：

1. §2 目录树在 `app/ui/pages/` 下加 `detail_page.py`：
```
│   ├── pages/
│   │   ├── current_page.py
│   │   ├── video_page.py
│   │   ├── data_page.py
│   │   ├── settings_page.py
│   │   └── detail_page.py        # ← 新增
```

2. §4 文件职责表加 1 行：
```
| [app/ui/pages/detail_page.py](file:///d:\Aging/app/ui/pages/detail_page.py) | 单 channel 详情（双击 LED 进入）| `DetailPage` |
```

3. §6.6 二次开发步骤加 1 段：
```
### 6.6.1 新增内嵌详情页（非 nav 项）

1. 在 [app/ui/pages/](file:///d:\Aging/app/ui/pages/) 新建 `*_detail.py`
2. 继承 QWidget，实现 `set_channel(cid)` 方法
3. 在 [app/ui/home_page.py](file:///d:\Aging/app/ui/home_page.py) `__init__` 实例化 + `router.register("xxx_detail", widget_instance)`
4. 双击事件 → `set_channel(cid)` + `router.navigate("xxx_detail")`
5. 在 `app/core/labels.py` 加 `*_DETAIL_*` 常量
```

**验证**：
```powershell
git diff ARCHITECTURE.md
# 应看到 3 处新增内容
```

#### D2. 全工程差异 review

```bash
git diff --stat
# 期望：~435 行改动（5 个文件）
```

#### D3. 完整验证流程

按 §4 跑一遍所有验证命令。

**阶段 D 提交**：
```bash
git add -A
git commit -m "phase-3-D: ARCHITECTURE.md sync"
```

---

## 4. 关键约束（**严禁违反**）

| # | 约束 | 违反后果 | 检测命令 |
|---|---|---|---|
| 1 | detail_page.py 不写裸 hex | 绕开 token 体系 | `rg "#[0-9a-fA-F]{6}" d:\Aging\app\ui\pages\detail_page.py` 应无命中 |
| 2 | detail_page.py 不写 `f"CH-{n:02d}"` | 绕开 format_cid | `rg 'f"CH-\{' d:\Aging\app\ui\pages\detail_page.py` 应无命中 |
| 3 | detail_page.py 不调 `random.uniform` | UI 与数据耦合 | `rg "random\." d:\Aging\app\ui\pages\detail_page.py` 应无命中 |
| 4 | detail_page.py 不调 `setStyleSheet()` | 绕开 StylesheetBuilder | `rg "setStyleSheet\(" d:\Aging\app\ui\pages\detail_page.py` 应无命中 |
| 5 | 用户可见中文字符串走 `labels.X` | 散落难维护 | 视觉验证 |
| 6 | 事件描述走 `narrative.event()` | 日志不友好 | 视觉验证 |
| 7 | eventFilter 放 HomeDashboard 不放 Rack3DView | 违反单一职责 | 读 main_3d.py 确认无 eventFilter |
| 8 | 关闭时设 `_closing = True` 防 RuntimeError | 段错误 | 读 closeEvent 确认有 gate |
| 9 | 60fps 路径用 `_dirty` 短路 | 抢 CPU | 读 `_tick_chart` 确认有 `if not self._dirty: return` |
| 10 | 不在 detail_page 写 QSS 模板，模板放 `app/styles/templates.py` | 违反模板统一 | 读 templates.py 确认 detail_page 段存在 |

---

## 5. 验证流程（每阶段必跑）

### 5.1 py_compile 兜底

```powershell
& E:\MiniConda\envs\Aging\python.exe -m py_compile `
    (Get-ChildItem d:\Aging\app -Recurse -Filter *.py -Exclude *.bak | %{ $_.FullName })
```

### 5.2 import smoke

```powershell
& E:\MiniConda\envs\Aging\python.exe -c "
import Main
from app.ui.pages.detail_page import DetailPage
print('DetailPage import OK')
print('Signals:', [s for s in dir(DetailPage) if 'requested' in s or 'action' in s])
"
```

### 5.3 启动验证

```powershell
& E:\MiniConda\envs\Aging\python.exe d:\Aging\Main.py
# 等 5 秒看启动正常
# 双击任意 LED → 应进入详情页
# 点"返回主页" → 应回到 3D 主页
# Ctrl+C 关闭
```

### 5.4 交互 9 步

| # | 操作 | 期望 | 验证 |
|---|---|---|---|
| 1 | 启动应用 | 主页 3D 渲染、5 路由就绪 | 视觉 |
| 2 | 双击 LED（如 cid=5）| 路由切到 detail、I-t 曲线开始画、归零红线可见 | 视觉 |
| 3 | 等待 30s | `detail tick sample` 日志出现 1 条 | `Get-Content logs\app.log -Tail 50 \| Select-String "detail"` |
| 4 | 主页启动 cid=1 → 立即双击 cid=1 | 详情页显示 RUNNING | 视觉 |
| 5 | 详情页点"开始" | 主页对应 LED 变绿 | 视觉 |
| 6 | 详情页点"返回" | 路由回 home、3D 视野连续 | 视觉 |
| 7 | 点空白处（非 LED）| 不进入 detail | 视觉 |
| 8 | 连续双击不同 LED | 详情页切换 channel | 视觉 |
| 9 | 关闭窗口 | 5s 内干净退出 | `Get-Content logs\app.log -Tail 20` 看无 RuntimeError |

### 5.5 硬编码自检

```powershell
# 4 条 rg 应全部无命中
rg "#[0-9a-fA-F]{6}" d:\Aging\app\ui\pages\detail_page.py
rg 'f"CH-\{' d:\Aging\app\ui\pages\detail_page.py
rg "random\." d:\Aging\app\ui\pages\detail_page.py
rg "setStyleSheet\(" d:\Aging\app\ui\pages\detail_page.py
```

### 5.6 日志验证

```powershell
# 启动后查看 logs\app.log，应包含：
Get-Content d:\Aging\logs\app.log -Tail 50 | Select-String "detail"
```

期望命中：
- `detail page initialized`
- `detail page open: cid=N`
- `detail tick sample: cid=N points=N`（30s 后）
- `detail: cid=N zero-anomaly segment red`（异常时）
- `detail page close: cid=N`

---

## 6. 回滚机制（按粒度）

### 6.1 单文件回滚

| 文件 | 回滚命令 |
|---|---|
| detail_page.py（新建）| `rm d:\Aging\app\ui\pages\detail_page.py` |
| home_page.py | `git checkout HEAD -- app/ui/home_page.py` |
| main_3d.py | `git checkout HEAD -- app/ui/main_3d.py` |
| labels.py | `git checkout HEAD -- app/core/labels.py` |
| ARCHITECTURE.md | `git checkout HEAD -- ARCHITECTURE.md` |

### 6.2 阶段回滚

| 阶段 | commit 标识 | 回滚命令 |
|---|---|---|
| A | `phase-3-A: rename BUTTON_LABELS` | `git revert <A-hash>` |
| B | `phase-3-B: detail_page core` | `git revert <B-hash>` |
| C | `phase-3-C: experience polish` | `git revert <C-hash>` |
| D | `phase-3-D: ARCHITECTURE.md sync` | `git revert <D-hash>` |

### 6.3 整体回滚

```bash
git log --oneline -10  # 找 phase-3 起点 commit
git reset --hard <phase-3-start>
# 或
git revert <start>..HEAD
```

### 6.4 紧急回滚脚本

```powershell
# emergency-rollback-phase3.ps1
$root = "d:\Aging"
if (Test-Path "$root\app\ui\pages\detail_page.py") {
    Remove-Item "$root\app\ui\pages\detail_page.py" -Force
    Write-Host "✓ 删除 detail_page.py" -ForegroundColor Yellow
}
git -C $root checkout HEAD -- app/ui/home_page.py app/ui/main_3d.py app/core/labels.py
Write-Host "✓ 还原 labels/home_page/main_3d" -ForegroundColor Yellow

& E:\MiniConda\envs\Aging\python.exe -m py_compile `
    $root\app\core\labels.py `
    $root\app\ui\home_page.py `
    $root\app\ui\main_3d.py `
    $root\app\ui\router.py

& E:\MiniConda\envs\Aging\python.exe $root\Main.py
# 等 5 秒看 3D 主页能正常启动
```

### 6.5 验证可回滚性（每阶段后）

```powershell
# 1) 备份当前
Copy-Item d:\Aging\app\ui\pages\detail_page.py d:\Aging\app\ui\pages\detail_page.py.bak

# 2) 模拟回滚
git stash
& E:\MiniConda\envs\Aging\python.exe d:\Aging\Main.py
# 应正常启动（无 detail 功能）

# 3) 恢复
git stash pop
Remove-Item d:\Aging\app\ui\pages\detail_page.py.bak
```

---

## 7. 风险登记表（实施时实时更新）

| 风险 | 等级 | 缓解 | 触发时操作 | 状态 |
|---|---|---|---|---|
| pyqtgraph ABI 不兼容 | 中 | 已验证环境 | import smoke 失败 → 检查 PyQt5/pyqtgraph 版本 | 待观察 |
| 双击 ray-pick 误判 | 中 | 仅 best_cid ≠ None 时 emit | 双击空白进入 detail → 调整 28px 阈值 | 待观察 |
| chart 闪烁 | 中 | 事件驱动 + 5fps 兜底 | 视觉看到闪烁 → 改回 30fps | 待观察 |
| HomeDashboard 旋转状态被 detail 干扰 | 中 | 保留 azimuth + set_auto_rotate | 视野跳跃 → 改 _on_detail_back | 待观察 |
| 5 处 logger 性能 | 低 | 不改 | （决策已定）| 已规避 |
| BUTTON_LABELS 重命名遗漏 | 中 | 阶段 A grep 验证 | py_compile 失败 → grep 补改 | 待观察 |
| _state 镜像双源 | 中 | 订阅 state_changed | 主页和详情页状态不同步 → 检查订阅 | 待观察 |
| closeEvent RuntimeError | 低 | _closing 门控 | 关闭时崩溃 → 检查 _closing 设置 | 待观察 |

---

## 8. 决策点 checklist（实施时打勾）

### 8.1 实施前

- [ ] git status 干净
- [ ] git commit 当前状态作为基线
- [ ] 备份关键文件（.bak）
- [ ] 启动 Main.py 正常（5s 内显示 3D 主页）

### 8.2 阶段 A

- [ ] BUTTON_LABELS → MAIN_BUTTON_LABELS 重命名
- [ ] 全工程引用替换（grep 验证 0 命中）
- [ ] py_compile 全过
- [ ] 启动 Main.py 正常
- [ ] git commit A

### 8.3 阶段 B

- [ ] labels.py +9 个 `DETAIL_*` 常量
- [ ] detail_page.py 新建（按 B2 骨架）
- [ ] main_3d.py 暴露 `best_hovered_cid` + `set_auto_rotate`
- [ ] home_page.py eventFilter + DblClick case + 路由注册 + 接线
- [ ] HomePage 持有 _data_source / _history / _controller
- [ ] py_compile 全过
- [ ] import smoke 通过
- [ ] 启动 Main.py 正常
- [ ] 双击 LED 进入 detail 成功
- [ ] 详情页点返回回 home 成功
- [ ] git commit B

### 8.4 阶段 C

- [ ] C1 LED 高亮 200ms 实现
- [ ] C3 azimuth 保留实现
- [ ] C2 / C4 **跳过**（已在文档标记）
- [ ] 视觉验证
- [ ] git commit C

### 8.5 阶段 D

- [ ] ARCHITECTURE.md §2 目录树加 detail_page.py
- [ ] ARCHITECTURE.md §4 职责表加 1 行
- [ ] ARCHITECTURE.md §6.6 加 6.6.1 内嵌详情页流程
- [ ] git diff --stat 看到 ~435 行
- [ ] 完整验证流程（§5.1-5.6）全部通过
- [ ] git commit D

### 8.6 实施后

- [ ] 4 条硬编码自检全部无命中
- [ ] 30s 周期采样日志可见
- [ ] 5fps 兜底 tick 正常工作
- [ ] 关闭应用无 RuntimeError
- [ ] git log 看到 phase-3-A/B/C/D 4 个 commit

---

## 9. 相关文档索引

| 文档 | 用途 |
|---|---|
| [phase-3-detail-page-plan.md](file:///d:\Aging\.trae\documents\phase-3-detail-page-plan.md) | 设计决策 + 风险评估 + 回滚方案（**WHAT**）|
| **本文件** | 操作步骤 + 验证命令 + 代码骨架（**HOW**）|
| [ARCHITECTURE.md](file:///d:\Aging\ARCHITECTURE.md) | 总体架构（实施 D 阶段要同步）|
| [code-redundancy-audit-2026-07-16.md](file:///d:\Aging\.trae\documents\code-redundancy-audit-2026-07-16.md) | TOP 5 已清的依据 |
| [observability-hardening-plan.md](file:///d:\Aging\.trae\documents\observability-hardening-plan.md) | 6 个日志点的规范来源 |
| [project-restructure-4-phases.md](file:///d:\Aging\.trae\documents\project-restructure-4-phases.md) | git commit 节奏的参考 |

---

## 10. 版本历史

| 版本 | 日期 | 改动 |
|---|---|---|
| v1 | 2026-07-18 | 初版：操作指南（4 阶段 + 10 约束 + 6 类验证 + 5 类回滚）|

---

*待用户审阅后按 §8 checklist 逐项执行*
