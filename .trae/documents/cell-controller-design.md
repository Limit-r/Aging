# CellController 拆解设计分析

> 文档版本：v1  ·  2026-07-11  ·  待审阅
> 配套报告：[optimization-analysis-2026-07-11.md](file:///d:/Aging/.trae/documents/optimization-analysis-2026-07-11.md) §3.1

---

## 0. 目标

把 `main_window.py` 中的**状态机 + 转移表 + 计数器**独立到 `app/services/cell_controller.py`，
让 MainWindow 只剩 UI 编排，业务核心可单测。

---

## 1. 当前职责盘点

| 职责 | 位置（行号） | 类型 |
|------|-------------|------|
| `DetectionState` 枚举 | [main_window.py:61-64](file:///d:/Aging/app/ui/main_window.py#L61-L64) | 纯数据 |
| `_STATE_TRANSITIONS` 表 | [L72-80](file:///d:/Aging/app/ui/main_window.py#L72-L80) | 纯数据 |
| `_ACTION_STATUS` 映射 | [L83-88](file:///d:/Aging/app/ui/main_window.py#L83-L88) | 纯数据（但耦合 ChannelStatus）|
| `self._cell_states` 真理源 | [L102-104](file:///d:/Aging/app/ui/main_window.py#L102-L104) | 业务状态 |
| `_apply_action` 状态机执行 | [L607-656](file:///d:/Aging/app/ui/main_window.py#L607-L656) | 业务逻辑 + UI 副作用 |
| `_count_actionable` 选区校验 | [L683-691](file:///d:/Aging/app/ui/main_window.py#L683-L691) | 业务逻辑 |
| `_update_buttons_by_state` 按钮 enabled | [L668-682](file:///d:/Aging/app/ui/main_window.py#L668-L682) | UI 副作用 |
| `_refresh_status_bar` 状态栏统计 | [L188-205](file:///d:/Aging/app/ui/main_window.py#L188-L205) | UI 副作用 + O(n) 扫描 |
| 倒计时联动（start/cancel）| [L644-650](file:///d:/Aging/app/ui/main_window.py#L644-L650) | 跨服务副作用 |
| `_on_countdown_expired` 归零闪烁 | [L768-786](file:///d:/Aging/app/ui/main_window.py#L768-L786) | 跨服务副作用 |
| 详情页状态通知 | `_notify_detail_state` | UI 副作用 |

**5 类职责**在同一方法 `_apply_action` 里混着。

---

## 2. 拆分原则

| 留在 CellController | 留在 MainWindow |
|-------------------|-----------------|
| 状态枚举 / 转移表 | 4 个检测按钮 + 4 个批量按钮的 UI 回调 |
| `cell_states` 真理源 | 选区管理（`_selected_cids`）|
| 状态计数器（n_running/n_paused/n_stopped）| cell 视觉更新（border/header）|
| `apply(action, cids) → List[int]` 状态机执行 | 倒计时联动（start/cancel）|
| `count_actionable / actionable_cids` 选区校验 | 详情页状态通知 |
| `state_changed` 信号 | 按钮 enabled / 状态栏刷新 |
| | `_on_countdown_expired` 归零闪烁 |

**判断标准**：能否在 `QApplication` 启动后**不创建任何 widget** 即可测试？能则入 Controller，否则留 MainWindow。

---

## 3. CellController 公开 API

```python
# app/services/cell_controller.py
from enum import Enum
from typing import Dict, Iterable, List, Optional
from PyQt5.QtCore import QObject, pyqtSignal


class DetectionState(Enum):
    STOPPED = "stopped"
    RUNNING = "running"
    PAUSED = "paused"


# 转移表：哪些 (action, 当前状态) 是合法的
# 命中则转为右侧状态；未命中 = 该 cell 对此 action 无效
_STATE_TRANSITIONS: Dict[str, Dict[DetectionState, DetectionState]] = {
    "start":  {DetectionState.STOPPED: DetectionState.RUNNING},
    "pause":  {DetectionState.RUNNING: DetectionState.PAUSED},
    "resume": {DetectionState.PAUSED:  DetectionState.RUNNING},
    "stop":   {
        DetectionState.RUNNING: DetectionState.STOPPED,
        DetectionState.PAUSED:  DetectionState.STOPPED,
    },
}


class CellController(QObject):
    """72 cell 状态机的真理源。纯业务，可脱离 GUI 单测。"""

    # cid, old.value, new.value
    state_changed = pyqtSignal(int, str, str)

    def __init__(self, total: int, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._total = total
        self._states: Dict[int, DetectionState] = {
            cid: DetectionState.STOPPED for cid in range(1, total + 1)
        }
        self._counts = {"running": 0, "paused": 0, "stopped": total}

    # -- 查询 API ----------------------------------------------------------
    @property
    def total(self) -> int:
        return self._total

    def state_of(self, cid: int) -> DetectionState:
        return self._states.get(cid, DetectionState.STOPPED)

    def n_running(self) -> int: return self._counts["running"]
    def n_paused(self) -> int:  return self._counts["paused"]
    def n_stopped(self) -> int: return self._counts["stopped"]

    def count_actionable(self, action: str, cids: Iterable[int]) -> int:
        """cids 中可被 action 转移的 cell 数。"""
        valid = set(_STATE_TRANSITIONS.get(action, {}).keys())
        return sum(1 for cid in cids if self._states.get(cid) in valid)

    def actionable_cids(self, action: str, cids: Iterable[int]) -> List[int]:
        """cids 中可被 action 转移的子集。"""
        valid = set(_STATE_TRANSITIONS.get(action, {}).keys())
        return [cid for cid in cids if self._states.get(cid) in valid]

    # -- 写 API ------------------------------------------------------------
    def apply(self, action: str, cids: Iterable[int]) -> List[int]:
        """对 cids 执行 action。返回成功转移的 cid 列表。

        每次成功转移 emit state_changed(cid, old.value, new.value)。
        """
        transitions = _STATE_TRANSITIONS.get(action, {})
        transitioned: List[int] = []
        for cid in cids:
            old = self._states.get(cid)
            if old is None:
                continue
            new = transitions.get(old)
            if new is None or new == old:
                continue
            self._states[cid] = new
            self._update_counts(old, new)
            self.state_changed.emit(cid, old.value, new.value)
            transitioned.append(cid)
        return transitioned

    # -- 内部 --------------------------------------------------------------
    def _update_counts(self, old: DetectionState, new: DetectionState) -> None:
        self._counts[old.value] -= 1
        self._counts[new.value] += 1
```

---

## 4. 状态变更后的副作用处理

### 4.1 现状（一锅烩）

```python
# main_window.py _apply_action
def _apply_action(self, action, cids, countdown_seconds=None):
    transitions = ...
    n = 0
    for cid in cids:
        if 转移合法:
            self._cell_states[cid] = new
            self._cells[cid - 1].update_status(new_status)   # UI
            self._cells[cid - 1].set_expired_pending(False)   # UI
            self._notify_detail_state(cid)                    # UI
            if action == "start": started_cids.append(cid)
            if action == "stop":  stopped_cids.append(cid)
            n += 1
    for cid in started_cids:
        self._countdown.start(cid, default_seconds)           # 服务
    for cid in stopped_cids:
        self._countdown.cancel(cid)                           # 服务
    self._update_button_labels_for_selection()                # UI
    self._update_buttons_by_state()                           # UI
    return n
```

### 4.2 新设计（解耦）

**CellController 不知道 UI / 倒计时的存在**，只发信号。
**MainWindow 用 1 个 slot 集中处理所有副作用**：

```python
# main_window.py
def __init__(self):
    ...
    self._controller = CellController(total=72, parent=self)
    self._controller.state_changed.connect(self._on_cell_state_changed)
    # MainWindow 不再持有 self._cell_states 真理源（只持有 _controller 引用）

def _on_cell_state_changed(self, cid: int, old: str, new: str) -> None:
    """cell state_changed → 集中处理所有 UI/服务副作用。"""
    new_state = DetectionState(new)

    # 1) Cell 视觉状态（border + header text）
    status = _STATE_TO_CELL_STATUS.get(new_state)
    if status is not None:
        self._cells[cid - 1].update_status(status)

    # 2) 清除"归零闪烁"标记（操作人已介入）
    self._cells[cid - 1].set_expired_pending(False)

    # 3) 详情页通知
    self._notify_detail_state(cid)

    # 4) 倒计时联动
    if new_state == DetectionState.RUNNING:
        seconds = self._pending_countdown.pop(
            cid, config.DEFAULT_COUNTDOWN_SECONDS_MAIN
        )
        self._countdown.start(cid, seconds)
    elif new_state == DetectionState.STOPPED:
        self._countdown.cancel(cid)
    # PAUSED: 倒计时继续

    # 5) 按钮 enabled / 标签 / 状态栏
    self._update_button_labels_for_selection()
    self._update_buttons_by_state()
    self._refresh_status_bar()

# 旧 API 仍保留但瘦身：
def _apply_action(self, action, cids, countdown_seconds=None) -> int:
    """MainWindow 薄壳：准备 pending + 调用 controller + 返回计数。"""
    if countdown_seconds is not None:
        for cid in cids:
            self._pending_countdown[cid] = countdown_seconds
    return len(self._controller.apply(action, cids))
```

**关键差异**：

- Controller 完全不知道有 cell 视觉 / 倒计时
- 所有副作用集中 1 个 slot，**先验逻辑只写 1 处**
- `countdown_seconds` 用 `self._pending_countdown` 字典传递（仍是"调用前准备"模式）
- 4 个检测按钮 + 4 个批量按钮的 handler 不变（仍调 `_apply_action`）

---

## 5. 数据流对比

### 5.1 旧：直接修改 + 散落副作用

```
button.clicked
  → _on_button_clicked(idx)
    → _apply_action("start", [cid])
      ├─ mutate self._cell_states[cid]
      ├─ cells[cid-1].update_status(ONLINE)     [UI 副作用 1]
      ├─ cells[cid-1].set_expired_pending(...)  [UI 副作用 2]
      ├─ _notify_detail_state(cid)              [UI 副作用 3]
      ├─ countdown.start(cid, 7200)             [服务副作用 4]
      ├─ _update_buttons_by_state()             [UI 副作用 5]
      └─ (return n)
```

### 5.2 新：Controller + 集中 slot

```
button.clicked
  → _on_button_clicked(idx)
    → _apply_action("start", [cid])           [薄壳：maybe set pending]
      → controller.apply("start", [cid]) → [cid]   [纯业务]
        ├─ mutate self._states[cid]
        ├─ update_counts(STOPPED, RUNNING)
        └─ emit state_changed(cid, "stopped", "running")

state_changed(cid, "stopped", "running")
  → _on_cell_state_changed(slot)             [集中处理所有副作用]
    ├─ cells[cid-1].update_status(ONLINE)    [UI 1]
    ├─ cells[cid-1].set_expired_pending(F)   [UI 2]
    ├─ _notify_detail_state(cid)             [UI 3]
    ├─ countdown.start(cid, seconds)         [服务 4]
    ├─ _update_buttons_by_state()            [UI 5]
    └─ _refresh_status_bar()                 [UI 6]
```

**优点**：副作用只在 slot 里，状态机只管状态。改 UI 不动 Controller，改业务不动 MainWindow。

---

## 6. 关键决策点

### 决策 1：DetectionState / 转移表放在哪里？

| 方案 | 评估 |
|------|------|
| **A. 放进 `cell_controller.py`** | 单文件自包含，main_window `from ... import`。✓ 推荐 |
| B. 单独 `state_machine.py` | 90 行单文件就为 1 个 enum + 1 个 dict，过度拆分 |

**推荐 A**。

### 决策 2：`_ACTION_STATUS`（action → ChannelStatus 映射）放哪？

| 方案 | 评估 |
|------|------|
| **A. 留 MainWindow** | 它是 UI 概念（决定 cell 显示什么颜色/文字），不是状态机概念 |
| B. 进 CellController | 强迫 Controller 依赖 protocol.py 的 ChannelStatus |

**推荐 A**。但 Controller 只 emit `state_changed` 含 new_state，MainWindow 自己从 new_state 推 ChannelStatus：

```python
_STATE_TO_CELL_STATUS = {
    DetectionState.STOPPED: ChannelStatus.NO_DATA,
    DetectionState.RUNNING: ChannelStatus.ONLINE,
    DetectionState.PAUSED:  ChannelStatus.ONLINE,
}

# slot 内：
status = _STATE_TO_CELL_STATUS.get(new_state)
if status is not None:
    self._cells[cid - 1].update_status(status)
```

### 决策 3：倒计时联动放哪？

| 方案 | 评估 |
|------|------|
| **A. slot 内根据 new_state 调 countdown** | 干净解耦，Controller 不知 CountdownService 存在 |
| B. Controller 接受 CountdownService 依赖 | 状态机自己联动倒计时 |

**推荐 A**。理由：未来"持久化"时，Controller 可独立于 CountdownService 序列化。

### 决策 4：迁移策略

| 方案 | 评估 |
|------|------|
| **A. 大爆炸**：一次 commit 全切 | 改动机械，有 controller 测试保护，**风险中** |
| B. Strangler：先建 Controller 不用，再逐步迁 | 多个 commit，渐进但慢 |

**推荐 A**（你项目目前是单 dev 单 commit 风格，且 controller 有 17 个测试兜底）。

### 决策 5：是否把 `_pending_countdown: Dict[int, int]` 公开 API？

| 方案 | 评估 |
|------|------|
| **A. MainWindow 私有字典 + `request_start_with_countdown` 设置** | 调用方不用关心 |
| B. Controller 接受 `apply(action, cids, countdown_seconds=)` 参数 | 污染 Controller 概念（它不懂倒计时） |

**推荐 A**。语义清晰："倒计时 override 是 UI 编排层的细节"。

---

## 7. 测试计划（17 用例，全部 pytest-qt）

```python
# tests/test_cell_controller.py

# 1. 初始状态
def test_initial_state_all_stopped(qapp): ...

# 2. state_of 未知 cid 返回 STOPPED
def test_state_of_unknown_cid_returns_stopped(qapp): ...

# 3. apply 转移成功计数
def test_apply_start_from_stopped_returns_one(qapp): ...
def test_apply_start_from_stopped_changes_state(qapp): ...
def test_apply_start_from_running_is_noop(qapp): ...
def test_apply_pause_from_running_changes_to_paused(qapp): ...
def test_apply_pause_from_stopped_is_noop(qapp): ...
def test_apply_resume_from_paused_changes_to_running(qapp): ...
def test_apply_resume_from_stopped_is_noop(qapp): ...
def test_apply_stop_from_running_changes_to_stopped(qapp): ...
def test_apply_stop_from_paused_changes_to_stopped(qapp): ...
def test_apply_stop_from_stopped_is_noop(qapp): ...

# 4. 计数器
def test_counts_after_start_one_running(qapp): ...
def test_counts_after_pause_one_paused(qapp): ...
def test_counts_after_stop_one_stopped(qapp): ...

# 5. 选区校验
def test_count_actionable_filters_invalid(qapp): ...
def test_actionable_cids_returns_subset(qapp): ...

# 6. 信号
def test_state_changed_emitted_with_old_and_new(qapp): ...
def test_state_changed_not_emitted_on_noop(qapp): ...

# 7. 边界
def test_apply_empty_cids_returns_empty(qapp): ...
def test_apply_unknown_cid_silently_skipped(qapp): ...
```

**全部 ~30min 写完 + 5min 跑通**。

---

## 8. 落地步骤（Strangler 3 步，2 个 commit）

> **测试文件策略**：测试用完即删，不入库（按用户要求）。

### Step 0：检查 pytest 环境

```bash
python -c "import pytest" || pip install pytest
```

### Step 1：建 CellController + 17 测试（不入 commit，临时验证）

| 步 | 改动 | 验证 |
|----|------|------|
| 1.1 | 新建 `app/services/cell_controller.py` | import 不报错 |
| 1.2 | 临时建 `test_cell_controller.py`（在 root，不进 `tests/`）| - |
| 1.3 | 跑 `python -m pytest test_cell_controller.py -v` | **17/17 PASS** |
| 1.4 | **删除 `test_cell_controller.py`** | 文件消失 |

### Commit 1：MainWindow 引入 Controller（旧字典并存）

| 步 | 改动 | 验证 |
|----|------|------|
| 2.1 | `main_window.py` 加 `self._controller = CellController(total, self)` | - |
| 2.2 | connect `state_changed → _on_cell_state_changed` | - |
| 2.3 | `_apply_action` 改薄壳：调 `controller.apply()`，**保留 `self._cell_states` 同步更新** | - |
| 2.4 | slot 集中处理 6 类副作用 | 跑 `python Main.py` 完整流程手测 |
| 2.5 | commit: "refactor: 引入 CellController，旧 _cell_states 保留并存" | - |

### Commit 2：清理旧字典 + 旧枚举定义

| 步 | 改动 | 验证 |
|----|------|------|
| 3.1 | grep `self._cell_states` → 全部改 `self._controller.state_of(cid)` | 5 处替换 |
| 3.2 | 计数器改用 `self._controller.n_running()` 等 | 3 处替换 |
| 3.3 | 移除 `DetectionState` / `_STATE_TRANSITIONS` / `_ACTION_STATUS` 定义，改 `from app.services.cell_controller import DetectionState` | import 不冲突 |
| 3.4 | 跑 `python Main.py` 完整流程 + 批量操作 + 倒计时 | ✓ |
| 3.5 | commit: "refactor: 移除 _cell_states，统一使用 CellController" | - |

**预估总时间**：1.5-2h（含 30min 写测试 + 30min 改代码 + 30min 手动验证 + 30min 清理）。

---

## 9. 风险与缓解

| 风险 | 缓解 |
|------|------|
| Slot 调用顺序错误（先 update cells 再 emit → cell 视觉延迟一帧）| Qt signal 是同步直连（不是 queued），所以 slot 在 emit 返回前已跑完，**不会**延迟 |
| 批量操作 72 cell × 多步骤 slot 慢 | 单次 slot < 1ms，72 个 ≈ 几十 ms，可接受；后续可加批量合帧 |
| `_pending_countdown` 漏 pop 造成内存泄漏 | 走 `dict.pop(cid, default)`，pop 后即清；且仅 start 路径有 |
| `state_changed` 在 Controller 内部递归触发 | 当前设计无递归（apply 不在 slot 内调 apply）|
| 旧 `_cell_states` 残留引用 | 第 5 步 grep + 替换确保清零 |

---

## 10. 不在本次范围

- 持久化（独立 spike）
- BlinkCoordinator 抽取（独立 PR）
- CellController 公开给多窗口使用（目前只有 MainWindow）
- 状态机可视化（debug 工具）

---

## 11. 待用户裁断

| # | 问题 | 我的建议 |
|---|------|---------|
| Q1 | 决策 1-5 的方案都 OK 吗？ | 都按推荐方案 |
| Q2 | 落地步骤是 7 步一次性 commit，还是拆 2-3 个 commit？ | 一次性（项目当前风格） |
| Q3 | 是否需要先单独跑 `pytest tests/test_cell_controller.py` 验证 Controller 后再改 main_window？ | **是**——分两步走更稳 |
| Q4 | 17 个测试用例全做，还是先做 5-6 个核心 + 后续补？ | 17 个全做（30min 写完） |

**审阅签字**：________________  日期：________________
