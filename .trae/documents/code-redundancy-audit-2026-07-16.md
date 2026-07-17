# 代码冗余结构审查报告

> 文档版本：v1 · 2026-07-16 · 待审阅
> 审查范围：`d:\Aging\app/` 全部 16 个 Python 源文件（不含 `__init__.py`），共 ~3863 行
> 审查维度：重复代码 / 死代码 / 职责重叠 / 逻辑重复
> 审查方式：静态分析（Read + Grep），未运行代码

---

## 0. 摘要

| 等级 | 数量 | 含义 |
|------|------|------|
| **CRITICAL** | 2 | 必修，影响代码整洁度或维护安全 |
| **MAJOR** | 7 | 应修，明显的冗余或职责越界 |
| **MINOR** | 7 | 可选，改进项，不影响功能 |
| **INFO** | 3 | 仅供参考，未来扩展时再考虑 |
| **合计** | 19 | |

**TOP 5 优先修复**总工作量约 1 小时，预计减少 ~200-300 行重复代码。

---

## 1. CRITICAL（必修）

### C1. `_restyle` 工具函数 4 处复制

- **维度**：重复代码 / 职责重叠
- **位置**：
  - [app/ui/main_window.py:50-54](file:///d:/Aging/app/ui/main_window.py#L50-L54)
  - [app/ui/widgets/countdown_widget.py:38-41](file:///d:/Aging/app/ui/widgets/countdown_widget.py#L38-L41)
  - [app/widgets/control_button.py:7-10](file:///d:/Aging/app/widgets/control_button.py#L7-L10)
  - [app/widgets/data_cell.py:32-36](file:///d:/Aging/app/widgets/data_cell.py#L32-L36)
- **问题**：同一个 3 行的 `widget.style().unpolish/polish/update` 工具函数在 4 个模块里逐字复制
- **证据**：
  ```python
  def _restyle(widget):
      widget.style().unpolish(widget)
      widget.style().polish(widget)
      widget.update()
  ```
- **建议**：提升到 [app/ui/qss_utils.py](file:///d:/Aging/app/ui/qss_utils.py) 公开 `refresh_qss(widget)`，删除 4 份拷贝
- **工作量**：15 分钟

### C2. `debug_legend.py` 是被遗忘的开发试验品

- **维度**：死代码
- **位置**：[app/ui/debug_legend.py](file:///d:/Aging/app/ui/debug_legend.py)（全文 66 行）
- **问题**：
  - 模块顶部 `"""debug 3: 模拟 detail_window 的内部结构"""`
  - 独立的 `_BaseTimeChart` 桩 + `DetailSim` 模拟器 + `QApplication` 启动代码
  - 全工程无任何模块 import（已 grep 确认）
- **证据**：
  ```python
  """debug 3: 模拟 detail_window 的内部结构"""
  import sys
  from PyQt5.QtWidgets import QApplication
  app = QApplication(sys.argv)
  ...
  d.show()
  app.processEvents()
  sys.exit(app.exec_())
  ```
- **建议**：直接删除该文件
- **工作量**：1 分钟

---

## 2. MAJOR（应修）

### M1. `_on_countdown_finished` legacy 空槽方法残留

- **维度**：死代码
- **位置**：[app/ui/main_window.py:754-759](file:///d:/Aging/app/ui/main_window.py#L754-L759)
- **问题**：`@safe_call(context="_on_countdown_finished")` 装饰的方法仅打 1 条 debug，实际由 `CountdownService.expired` 驱动 `_on_countdown_expired`。该 slot 从未被任何信号 connect（grep 仅命中自身 docstring 与函数定义）
- **证据**：
  ```python
  def _on_countdown_finished(self, channel_id: int) -> None:
      """兼容 detail window 的 countdown_finished 信号（已废弃）。"""
      _log.debug("legacy countdown_finished for CH-%02d (ignored)", channel_id)
  ```
- **建议**：删除方法与文件顶部 docstring 中相关描述
- **工作量**：5 分钟

### M2. `_apply_streaming_overlay` 永远 pass 的占位

- **维度**：死代码
- **位置**：[app/ui/detail_window.py:279-286](file:///d:/Aging/app/ui/detail_window.py#L279-L286)
- **问题**：方法体为 `pass`，docstring 明确写 "Step 1 占位 ... Step 2 在此实现 QFrame 覆盖层 + QSS"。Step 2 看起来已不会再做
- **证据**：
  ```python
  def _apply_streaming_overlay(self, streaming: bool) -> None:
      """Step 1 占位：方法签名已就绪，Step 2 实现 QFrame + QSS。
      当前为空实现，曲线已通过 on_reading gate 冻结；视觉反馈待 Step 2。"""
      pass
  ```
- **建议**：要么实现，要么删除调用点 [detail_window.py:173](file:///d:/Aging/app/ui/detail_window.py#L173) + 该方法 + "Step 1/Step 2" 注释
- **工作量**：5 分钟

### M3. QMessageBox 确认弹窗模式重复

- **维度**：逻辑重复
- **位置**：
  - [app/ui/main_window.py:500-530](file:///d:/Aging/app/ui/main_window.py#L500-L530)（"全部结束"二次确认）
  - [app/ui/detail_window.py:203-211](file:///d:/Aging/app/ui/detail_window.py#L203-L211)（详情页"取消"二次确认）
- **问题**：两处都手动构造 `QMessageBox` + `addButton` 自定义文案 + `setDefaultButton` + `clickedButton() is yes_btn` 判定；逻辑骨架一致，但按钮文案 / role / icon 略不同
- **证据**：
  ```python
  # main_window.py
  box = QMessageBox(self)
  box.setIcon(QMessageBox.Warning)
  yes_btn = box.addButton(labels.CONFIRM_STOP_ALL_OK, QMessageBox.YesRole)
  cancel_btn = box.addButton(labels.CONFIRM_STOP_ALL_CANCEL, QMessageBox.RejectRole)
  box.exec_()
  if box.clickedButton() is not yes_btn: ...
  ```
- **建议**：抽到 [app/ui/dialogs.py](file:///d:/Aging/app/ui/dialogs.py) 暴露 `confirm_yes_cancel(parent, title, text, yes_label, cancel_label) -> bool`
- **工作量**：20 分钟

### M4. 通道 ID 格式化 `f"CH-{cid:02d}"` 13 处硬编码

- **维度**：逻辑重复
- **位置**：
  - [app/core/labels.py:53,99,101,148,149](file:///d:/Aging/app/core/labels.py)
  - [app/observability/narrative.py:129](file:///d:/Aging/app/observability/narrative.py#L129)
  - [app/widgets/data_cell.py:171](file:///d:/Aging/app/widgets/data_cell.py#L171)
  - [app/ui/detail_window.py:207,238](file:///d:/Aging/app/ui/detail_window.py)
  - [app/ui/main_window.py:604,774,781,787,799,804,826](file:///d:/Aging/app/ui/main_window.py)
- **问题**：`CH-{n:02d}` 散落 13 处，与 `narrative.format_cids` 内同款 `f"CH-{int(c):02d}"` 重复；任意一处改格式都要全局搜
- **证据**：
  ```python
  f"CH-{cid:02d}"        # main_window.py 6 处
  f"CH-{cell_id:02d}"    # data_cell.py
  ```
- **建议**：在 [app/core/formatting.py](file:///d:/Aging/app/core/formatting.py) 集中加 `def format_cid(cid: int) -> str: return f"CH-{int(cid):02d}"`，所有调用点统一替换
- **工作量**：30 分钟

### M5. `countdown.py` 重复 import `get_logger`

- **维度**：重复代码
- **位置**：[app/services/countdown.py:36,38](file:///d:/Aging/app/services/countdown.py#L36)
- **问题**：同 import 出现两次（**已知 bug，未修**）
- **证据**：
  ```python
  from app.observability import get_logger, narrative
  from app.observability.log_signals import LogLevel
  from app.observability import get_logger        # ← 重复
  ```
- **建议**：删除第 38 行的重复 import
- **工作量**：1 分钟

### M6. 时间格式 `divmod(3600)` 两套实现

- **维度**：逻辑重复
- **位置**：
  - [app/observability/narrative.py:105-117](file:///d:/Aging/app/observability/narrative.py#L105-L117)（`format_duration`，输出中文 "30分钟 (1800s)"）
  - [app/ui/widgets/countdown_widget.py:44-51](file:///d:/Aging/app/ui/widgets/countdown_widget.py#L44-L51)（`_fmt_remaining`，输出 "H:MM:SS"）
- **问题**：都基于 `divmod(s, 3600)` + `divmod(rem, 60)`，但输出格式不同
- **证据**：
  ```python
  # narrative.py
  h, rem = divmod(seconds, 3600); m, s = divmod(rem, 60)
  # countdown_widget.py
  h, rem = divmod(remain_s, 3600); m, s = divmod(rem, 60)
  ```
- **建议**：把 `_fmt_remaining` 重命名 `format_hms(remain, total)` 放到 [app/core/formatting.py](file:///d:/Aging/app/core/formatting.py)，与 `narrative.format_duration` 共享一个 `divmod3600()` 内核
- **工作量**：15 分钟

### M7. 状态→文本/视觉 3 套独立映射

- **维度**：职责重叠 / 逻辑重复
- **位置**：
  - [app/data/protocol.py:21-26](file:///d:/Aging/app/data/protocol.py#L21-L26)（`ChannelStatus` enum，4 态）
  - [app/services/cell_controller.py:17-20](file:///d:/Aging/app/services/cell_controller.py#L17-L20)（`DetectionState` enum，3 态业务）
  - [app/widgets/data_cell.py:194-197](file:///d:/Aging/app/widgets/data_cell.py#L194-L197)（`STATUS_*` 4 个类常量）
  - [app/widgets/data_cell.py:286-301](file:///d:/Aging/app/widgets/data_cell.py#L286-L301)（4 个 if/elif 链映射 4 个状态到颜色+文本）
  - [app/ui/detail_window.py:158-163](file:///d:/Aging/app/ui/detail_window.py#L158-L163)（`state_text` 3 键 dict）
  - [app/core/labels.py:38-41,45-47](file:///d:/Aging/app/core/labels.py)（6 个中文字符串常量）
  - [app/ui/main_window.py:61-65](file:///d:/Aging/app/ui/main_window.py#L61-L65)（`_STATE_TO_CELL_STATUS` dict）
- **问题**：
  1. 同一组语义被 3 个 enum/常量描述：`DetectionState`（3 态业务）vs `ChannelStatus`（4 态视觉）vs `DataCell.STATUS_*`（4 个字符串类属性），三者之间还有 2 个映射 dict
  2. `detail_window.state_text` 只覆盖 3 键（缺 OFFLINE / ANOMALY），跟 `data_cell` 的 4 态不一致；新增状态极易漏改
  3. `data_cell.set_status` 用 4 个 `if/elif` 而非 dict，扩展性差
- **证据**：
  ```python
  # data_cell.py
  if status == self.STATUS_ONLINE:  self._header.set_status_text(..., c.TEXT_NEON_GREEN)
  elif status == self.STATUS_ANOMALY: ...
  elif status == self.STATUS_NO_DATA: ...
  else: ...                                                # → 4 个硬编码

  # detail_window.py
  return {"stopped":..., "running":..., "paused":...}.get(...)  # → 仅 3 键
  ```
- **建议**：合并为单一 `StatusPresentation` 数据类（在 `app/core/`）含 `(display_text, color_token_key, cell_status_str)`；删 `DataCell.STATUS_*` 类属性（直接用 `ChannelStatus` 字符串值）
- **工作量**：45 分钟（**较大重构，可拆为 2 步**）

---

## 3. MINOR（可选）

### m1. `CellController.count_actionable` 与 `actionable_cids` 高度相似

- **维度**：逻辑重复
- **位置**：[app/services/cell_controller.py:67-75](file:///d:/Aging/app/services/cell_controller.py#L67-L75)
- **问题**：两方法都用同一段 `valid = set(_STATE_TRANSITIONS.get(action, {}).keys())` + 遍历 `cids` + 比对；只是返回 sum 还是 list
- **证据**：
  ```python
  def count_actionable(self, action, cids):
      valid = set(_STATE_TRANSITIONS.get(action, {}).keys())
      return sum(1 for cid in cids if self._states.get(cid) in valid)
  def actionable_cids(self, action, cids):
      valid = set(_STATE_TRANSITIONS.get(action, {}).keys())
      return [cid for cid in cids if self._states.get(cid) in valid]
  ```
- **建议**：用 `len(self.actionable_cids(action, cids))` 复用，或合并为 `_filter_actionable(self, action, cids) -> Iterator[int]`
- **工作量**：5 分钟

### m2. 日志 fmt 字符串重复

- **维度**：重复代码
- **位置**：[app/observability/logger.py:43-46 与 52-55](file:///d:/Aging/app/observability/logger.py)
- **问题**：`"%(asctime)s | %(levelname)-7s | %(name)-15s | %(message)s"` 在 file/console 两个 handler 的 Formatter 中逐字重复
- **证据**：
  ```python
  file_handler.setFormatter(logging.Formatter(
      fmt="%(asctime)s | %(levelname)-7s | %(name)-15s | %(message)s",
      datefmt="%Y-%m-%d %H:%M:%S",
  ))
  console.setFormatter(_ColorFormatter(
      fmt="%(asctime)s | %(levelname)-7s | %(name)-15s | %(message)s",
      datefmt="%H:%M:%S",
  ))
  ```
- **建议**：抽 `DEFAULT_LOG_FMT` 常量复用
- **工作量**：3 分钟

### m3. `_STATE_TO_CELL_STATUS` 应属于 CellController

- **维度**：职责重叠
- **位置**：[app/ui/main_window.py:61-65](file:///d:/Aging/app/ui/main_window.py#L61-L65)
- **问题**：状态机→视觉状态映射被放在 UI 模块，但 `CellController` 才是状态机的真理源；该映射属于"业务规则"应在 services 层
- **证据**：
  ```python
  _STATE_TO_CELL_STATUS: Dict[DetectionState, Optional[ChannelStatus]] = {
      DetectionState.STOPPED: ChannelStatus.NO_DATA,
      DetectionState.RUNNING: ChannelStatus.ONLINE,
      DetectionState.PAUSED:  None,
  }
  ```
- **建议**：迁到 `CellController` 作为 `cell_status_of(cid) -> ChannelStatus` 方法
- **工作量**：15 分钟

### m4. `_pending_countdown` 字典可去掉

- **维度**：职责重叠
- **位置**：[app/ui/main_window.py:93-94, 629-631, 665-668](file:///d:/Aging/app/ui/main_window.py)
- **问题**：MainWindow 维护 `_pending_countdown: Dict[int, int]`，仅用于在 `apply()` 调用前暂存详情页自定义秒数
- **证据**：
  ```python
  if countdown_seconds is not None:
      for cid in cids:
          self._pending_countdown[cid] = countdown_seconds
  ...
  seconds = self._pending_countdown.pop(cid, config.DEFAULT_COUNTDOWN_SECONDS_MAIN)
  ```
- **建议**：把 countdown_seconds 作为 `apply()` 参数，state_changed 携带新签名
- **工作量**：20 分钟（**接口变更**）

### m5. `logger.py` 顶部重复导入 `os` / `pathlib`

- **维度**：INFO
- **位置**：[app/observability/logger.py:5-6](file:///d:/Aging/app/observability/logger.py)
- **问题**：`os.path.join` 与 `Path.mkdir` 都用于拼接日志目录
- **建议**：统一 `Path(log_dir) / "app.log"`，去掉 `import os`
- **工作量**：2 分钟

### m6. `templates.py` 数据网格 NO_DATA 态用硬编码 hex

- **维度**：职责重叠
- **位置**：[app/styles/templates.py:160](file:///d:/Aging/app/styles/templates.py#L160)
- **问题**：`background-color: #161616;` 是裸 hex，绕开 token 体系（其它路径全部走 `t.colors.*`）
- **证据**：
  ```css
  QWidget#dataCell[status="no_data"] QWidget#dataGrid {
      background-color: #161616;
  ```
- **建议**：在 `tokens.Colors` 增加 `BG_DATAGRID_NO_DATA: str = "#161616"` 替代
- **工作量**：5 分钟

### m7. `_closing` 与 `closeEvent` 内 try/except RuntimeError 双重防御

- **维度**：职责重叠
- **位置**：
  - [main_window.py:131](file:///d:/Aging/app/ui/main_window.py#L131) `self._closing = False`
  - [main_window.py:180-181](file:///d:/Aging/app/ui/main_window.py#L180-L181) `_refresh_status_bar` 内的 `if _closing: return`
  - [main_window.py:738-746](file:///d:/Aging/app/ui/main_window.py#L738-L746) `_on_detail_closed` 内 `try/except RuntimeError`
  - [main_window.py:851-862](file:///d:/Aging/app/ui/main_window.py#L851-L862) `closeEvent` 内手动 `disconnect state_changed`
- **问题**：`_closing` 标记 + `_refresh_status_bar` 内的 gate + `_on_detail_closed` 内 try/except + `closeEvent` 内 disconnect 共 4 道保护墙
- **建议**：把 `state_changed.disconnect` 提前到 `closeEvent` 开头（已做），删除 `_on_detail_closed` 的 RuntimeError 兜底（status_bar 已被 gate 保护）
- **工作量**：5 分钟

---

## 4. INFO（仅供参考）

### I1. `narrative._ACTOR_ZH` 14 条目手写映射
- **位置**：[app/observability/narrative.py:70-86](file:///d:/Aging/app/observability/narrative.py#L70-L86)
- **观察**：14 个 actor 中 9 个只是 `user_*` 前缀 + 动作名拼接，可用 `{prefix}-{action}` 模板自动生成

### I2. `CellController` 的 `apply()` 末尾两段互斥 event
- **位置**：[app/services/cell_controller.py:107-138](file:///d:/Aging/app/services/cell_controller.py#L107-L138)
- **观察**：`if transitioned:` 块和 `if not transitioned:` 块分别在成功/失败时打 event，可读性可优化

### I3. `_BaseTimeChart` 子类 `_setup_plot` 几乎逐字相同
- **位置**：[app/ui/charts.py:465-479（CurrentChart）与 503-517（TempChart）](file:///d:/Aging/app/ui/charts.py)
- **观察**：两处 `_setup_plot` 只差在 `setYRange` 和 `setLabel("left", ...)`，可由类属性 + 基类方法覆盖

---

## 5. TOP 5 优先修复

| # | 等级 | 文件 | 摘要 | 工作量 |
|---|------|------|------|--------|
| 1 | CRITICAL | [app/ui/debug_legend.py](file:///d:/Aging/app/ui/debug_legend.py) | 删除整个 debug 实验文件 | 1 分钟 |
| 2 | CRITICAL | 4 处 `_restyle` 复制 | 抽到 `app/ui/qss_utils.py` 统一 | 15 分钟 |
| 3 | MAJOR | [main_window.py:754](file:///d:/Aging/app/ui/main_window.py#L754) + [detail_window.py:279](file:///d:/Aging/app/ui/detail_window.py#L279) | 删除 `_on_countdown_finished` 与 `_apply_streaming_overlay` 两个空方法 | 5 分钟 |
| 4 | MAJOR | 13 处 `f"CH-{cid:02d}"` + 状态映射 3 套 | 集中到 `app/core/formatting.py` 公共 helper | 30 分钟 |
| 5 | MAJOR | [countdown.py:38](file:///d:/Aging/app/services/countdown.py#L38) + [cell_controller.py:67-75](file:///d:/Aging/app/services/cell_controller.py#L67-L75) | 删重复 import、合并 `count_actionable`/`actionable_cids` | 10 分钟 |

**总工作量**：~1 小时，减少 ~200-300 行重复代码。

---

## 6. 建议实施路径

按依赖关系分 3 批：

### 批 1：低风险清理（10 分钟，无新文件）

1. **C2**: 删除 `app/ui/debug_legend.py`
2. **M1**: 删除 `main_window._on_countdown_finished`
3. **M2**: 删除 `detail_window._apply_streaming_overlay` + 调用点
4. **M5**: 删除 `countdown.py:38` 重复 import
5. **m5**: 清理 `logger.py` 重复导入
6. **m2**: 抽 `DEFAULT_LOG_FMT` 常量

### 批 2：公共 helper 抽离（45 分钟，新建 1 个文件）

1. **C1**: 新建 `app/ui/qss_utils.py`，4 处 `_restyle` 替换
2. **M4**: 新建 `app/core/formatting.py::format_cid`，13 处替换
3. **M6**: 抽 `divmod3600()` 公共内核
4. **m1**: `CellController` 用 `len(actionable_cids)` 复用
5. **m6**: `tokens.Colors.BG_DATAGRID_NO_DATA`

### 批 3：职责/接口重构（1+ 小时，较大改动）

1. **M3**: 抽 `confirm_yes_cancel` 公共 dialog helper
2. **M7**: 合并状态映射为 `StatusPresentation`（**最大改动**）
3. **m3**: `_STATE_TO_CELL_STATUS` 迁到 CellController
4. **m4**: 去掉 `_pending_countdown` 字典（接口变更）
5. **m7**: 清理 closeEvent 4 道保护墙

---

## 7. 风险评估

| 风险项 | 涉及问题 | 影响 |
|--------|---------|------|
| **删除误判**：M1 / M2 的方法确认是死代码？| M1, M2 | 删错会破坏功能（建议 grep 信号 connect 二次确认）|
| **接口变更**：m4 的 `apply()` 签名变更 | m4 | 影响 `_apply_action` 调用方，需要同步改 |
| **大重构**：M7 状态映射合并 | M7 | 跨 5 个文件，约 200 行改动；需有完整测试 |
| **无测试覆盖**：所有改动都靠人工测试 | 全部 | 仓库无 pytest 套件（用户偏好）|

---

## 8. 待用户决策

- [ ] 是否同意按 TOP 5 顺序执行？
- [ ] 批 3 的较大重构（M3/M7/m3/m4/m7）是否本轮处理？
- [ ] 删除 `app/ui/debug_legend.py` 前是否需要备份？
- [ ] 是否需要先 git commit 当前状态作为基线？
