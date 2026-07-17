# 主页面批量控制（多选 + 批量按钮）

## Context（背景与动机）

当前主页面右侧 4 个按钮（开始/暂停/恢复/结束）**全部作用于"当前选中的单一 cell"**，用户无法：
- 一次性启动多台设备
- 一次性暂停多台设备
- 一次性结束多台设备

每次都要逐个点击 72 个 cell 切换状态是低效的。

**目标**：在主页面增加多选机制 + 4 个批量按钮（`全选` / `全部开始` / `全部暂停` / `全部结束`），让用户可以一键操作任意子集或全部 72 台。

**用户已确认**：
- 方案 C：多选 + 复用 4 个原按钮 + 新增 4 个批量按钮（混合方案）
- 全部结束需要二次确认

---

## 设计

### 1. 选区模型重构

**`DataCell` 改为纯被动**：
- 删除 `mousePressEvent` 中的 toggle 逻辑
- 新增信号 `clicked = pyqtSignal(int, Qt.KeyboardModifiers)`，传入 `cid` 和按键 modifier
- `set_selected(bool)` 保留，由 MainWindow 调用
- `selected_changed` 信号保留（暂不删除，避免破坏其他可能的监听者；实际目前只 MainWindow 消费，但保留以防外部模块需要）

**`MainWindow` 集中处理选区**：
- 替换 `_selected_channel_id: Optional[int]` → `_selected_cids: Set[int]`
- 连接 `DataCell.clicked(cid, mods)`：
  - **无 modifier**：清空选区，加入 `cid`（保留单选体验）
  - **Ctrl**：toggle 该 `cid`（增减）
  - **Shift**：v1 不支持（Plan agent 指出 9x8 列优先布局下区间语义反直觉，Ctrl+全选 已覆盖 95% 场景）
- 调用每个受影响 cell 的 `set_selected` 同步视觉

### 2. 4 个原按钮 → 作用于选区（permissive + 计数 badge）

**Enable 矩阵（permissive 模式）**：
| 按钮 | 启用条件（任一选中 cell 满足） |
|------|------------------------------|
| 开始 | 存在 `STOPPED` |
| 暂停 | 存在 `RUNNING` |
| 恢复 | 存在 `PAUSED` |
| 结束 | 存在非 `STOPPED` |

无选中 → 4 个按钮全禁用。

**Label 加计数 badge**（Plan agent B 建议）：
- 单选时 label 保持原样（避免 `开始检测 (1/1)` 这种噪音）
- 多选时显示 `开始检测 (3/5)`：表示 5 台选中里 3 台可开始
- 在 MainWindow 维护 `self._action_counts: List[int]`，每次选区/状态变化后重算

**Action 作用于子集**：
- 点"开始"：仅对选区里 `STOPPED` 的 cell 执行 `RUNNING`
- 点"暂停"：仅对选区里 `RUNNING` 的执行 `PAUSED`
- 点"恢复"：仅对选区里 `PAUSED` 的执行 `RUNNING`
- 点"结束"：对选区里非 `STOPPED` 的执行 `STOPPED`

### 3. 新增 4 个批量按钮（始终作用于全部 72 台，与选区无关）

| 按钮 | 行为 | 是否确认 |
|------|------|----------|
| ☑ 全选 | `_selected_cids = set(range(1, 73))`，更新所有 cell 视觉 | 否 |
| ▶▶ 全部开始 | 所有 `STOPPED` → `RUNNING` | 否 |
| ⏸⏸ 全部暂停 | 所有 `RUNNING` → `PAUSED` | 否 |
| ■■ 全部结束 | 所有非 `STOPPED` → `STOPPED` | **是，QMessageBox** |

加一行帮助文本 `作用于全部 {N} 台，与选区无关`，明确语义（Plan agent C 建议）。

### 4. 全部结束的二次确认（Plan agent D 建议）

确认对话框展示影响面：
```
将停止全部 12 台设备：
  • 7 台运行中
  • 5 台已暂停
  • 3 个倒计时进行中
  • 2 个详情页已打开

此操作不可撤销，是否继续？
```

- 从 `self._cell_states` 统计 running/paused
- 从 `self._detail_windows` 统计 open
- 从各 `DetailWindow._countdown` 统计进行中（如果可行；否则省略倒计时行）

### 5. 右侧面板布局（自顶向下）

```
┌────────────────────────┐
│ 功能区  //  CONTROL     │  (BUTTON_AREA_TITLE)
│ 已选 5 / 72 台          │  ← 大字（行1）
│ RUN 2 / PAUSED 1 / ...  │  ← 小字（行2，dim 颜色）
│ ── 批量 ──              │  ← 段落标题
│ ☑  全选                  │  (QPushButton[role="batch"])
│ ▶▶ 全部开始              │
│ ⏸⏸ 全部暂停              │
│ 作用于全部 72 台        │  ← 帮助文本（小灰字）
│ ── 检测控制 ──           │  ← 段落标题
│ ▶  开始检测              │  (QPushButton — 原4个，多选语义)
│ ⏸  暂停检测              │
│ ▶  恢复暂停              │
│ ■  结束检测              │
│ ⤴ (stretch)              │
│ ── 危险 ──               │  ← 段落标题（红色）
│ ■■ 全部结束              │  (QPushButton[role="danger"])
│ AGING CONSOLE           │  (footer)
│ v2.0.0 / ...            │
└────────────────────────┘
```

按钮宽度：`BUTTON_AREA_WIDTH` 从 240 提到 260。

### 6. QSS 扩展

**`templates.button()` 增加 dynamic property 分支**：
```qss
QPushButton[role="batch"] {
    border: 1px solid {c.BORDER_PRIMARY};  /* 比主按钮细一档 */
    padding: 8px 12px;
    /* 字体稍小 */
}
QPushButton[role="batch"]:hover {
    background-color: qlineargradient(...);  /* 略亮 */
}
QPushButton[role="danger"] {
    border: 2px solid {c.BORDER_DANGER};
    color: {c.TEXT_DANGER};
    background-color: qlineargradient(...);
}
QPushButton[role="danger"]:hover {
    background-color: {c.BORDER_DANGER};
    color: {c.BG_DEEP};
}
```

**新增 `templates.batch_section()`**：段落标题（小灰字 + 上下边线）
```qss
QLabel#batchSectionTitle {
    color: {c.TEXT_DIM};
    font-family: ...;
    font-size: 9pt;
    font-weight: bold;
    letter-spacing: 1px;
    padding: 6px 0 2px 0;
    border-bottom: 1px dashed {c.BORDER_PRIMARY};  /* 可选 */
}
QLabel#batchSectionTitle[danger="true"] {
    color: {c.TEXT_DANGER};
    border-bottom-color: {c.BORDER_DANGER};
}
```

**新增 `templates.panel_selection()`**：选中标签（双行）
```qss
QLabel#panelSelectionPrimary {
    color: {c.BORDER_PRIMARY};
    font-family: ...;
    font-size: 12pt;
    font-weight: bold;
}
QLabel#panelSelectionSecondary {
    color: {c.TEXT_DIM};
    font-family: ...;
    font-size: 9pt;
}
```

### 7. `SciFiButton` 扩展

添加 `set_role(name: str)` 方法，封装 `setProperty("role", name) + _restyle()`：
```python
def set_role(self, role: str) -> None:
    if self.property("role") != role:
        self.setProperty("role", role)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()
```

### 8. 选中标签（双行布局）

用 2 个 QLabel 而不是 1 个：
- `self._selection_primary`：大字 `已选 5 / 72 台`
- `self._selection_secondary`：小字 `RUN 2 / PAUSED 1 / STOP 2`

无选中时 primary 显示 `（请先点击数据卡片）`，secondary 隐藏。

---

## 关键文件

### 需要修改

1. **`d:\Aging\app\ui\main_window.py`** — 主要改动：
   - `_selected_channel_id` → `_selected_cids: Set[int]`
   - 新增 `_batch_buttons: List[SciFiButton]`
   - 新增 `_action_counts: List[int]`
   - `_build_right_panel` 重构为段落式布局
   - `_on_cell_selected` 重构为基于 `clicked(cid, mods)` 信号的处理
   - `_action_start/_action_pause/_action_resume/_action_stop` 重构为接受 `cids: Iterable[int]`
   - `_update_buttons_by_state` 改为 permissive + 计数 + label 更新
   - `_update_button_labels_for_selection` 改为双行
   - 新增 `_on_select_all / _on_start_all / _on_pause_all / _on_stop_all`
   - 新增 `_confirm_stop_all` 弹 QMessageBox
   - `_refresh_status_bar` 增加 `SEL {n_sel}` 字段
   - `_on_countdown_finished` 适配新签名（传 `[cid]`）

2. **`d:\Aging\app\widgets\data_cell.py`** — 较小的改动：
   - `mousePressEvent` 改为只 emit `clicked(cid, mods)`，不再 toggle
   - 新增 `clicked = pyqtSignal(int, Qt.KeyboardModifiers)`

3. **`d:\Aging\app\widgets\control_button.py`** — 扩展：
   - 新增 `set_role(name: str)` 方法

4. **`d:\Aging\app\core\labels.py`** — 新增常量：
   ```python
   BUTTON_BATCH_LABELS = ("全选", "全部开始", "全部暂停", "全部结束")
   BUTTON_BATCH_GLYPHS = ("☑", "▶▶", "⏸⏸", "■■")
   BATCH_SECTION_TITLE = "── 批量 ──"
   DETECTION_SECTION_TITLE = "── 检测控制 ──"
   DANGER_SECTION_TITLE = "── 危险 ──"
   BATCH_HELP_TEXT_TEMPLATE = "作用于全部 {total} 台 · 与选区无关"
   PANEL_SELECTION_PRIMARY_EMPTY = "（请先点击数据卡片）"
   PANEL_SELECTION_PRIMARY_TEMPLATE = "已选 {n_sel} / {total} 台"
   PANEL_SELECTION_SECONDARY_TEMPLATE = (
       "RUN {running} / PAUSED {paused} / STOP {stopped}"
   )
   CONFIRM_STOP_ALL_TITLE = "确认全部结束？"
   CONFIRM_STOP_ALL_TEXT_TEMPLATE = (
       "将停止全部 {total} 台设备：\n"
       "  • {running} 台运行中\n"
       "  • {paused} 台已暂停\n"
       "  • {countdown} 个倒计时进行中\n"
       "  • {detail} 个详情页已打开\n"
       "\n此操作不可撤销，是否继续？"
   )
   STATUS_BAR_NORMAL_TEMPLATE = (  # 扩展
       "● SYSTEM ONLINE   ::   SEL {n_sel}  ::   "
       "RUN {running}  PAUSED {paused}  ::   "
       "REFRESH {refresh_ms}ms   ::   DETAIL OPEN {open_detail}"
   )
   ```

5. **`d:\Aging\app\core\config.py`** — 调整：
   - `BUTTON_COUNT` 改为 8（或拆为 `CONTROL_BUTTON_COUNT=4` + `BATCH_BUTTON_COUNT=4`）
   - `BUTTON_AREA_WIDTH` 240 → 260

6. **`d:\Aging\app\styles\templates.py`** — 扩展：
   - `button()` 增加 `[role="batch"]` 和 `[role="danger"]` 分支
   - 新增 `batch_section()` 函数（段落标题 QSS）
   - 新增 `panel_selection()` 函数（选中标签 QSS）

7. **`d:\Aging\app\styles\stylesheet.py`** — 装配：
   - 在 `StylesheetBuilder.render` 中加入 `batch_section()` 和 `panel_selection()`

### 可选/可省略

- 新建 `app/observability/dialogs.py` 封装 `QMessageBox`（可内联在 MainWindow，v1 不单独抽）

---

## 复用现有模式

- **动态属性 + QSS selector**：dataCell 的 `status/hovered/selected`、countdownBigTime 的 `state` 都是用 `setProperty` + `[name="value"]` 选择器。`role` 属性沿用同一模式（`templates.py:68-101` 有先例）。
- **Glyph prefix 模式**：`main_window.py:251` 的 `f"{glyph}  {label}"` 直接复用。
- **@safe_call 包装**：新加的 slot（`_on_select_all` 等）继续用 `@safe_call(context="...")` 装饰。
- **state 转移表**：`_action_*` 4 个方法几乎对称，可以压缩为：
  ```python
  _STATE_TRANSITION = {
      ("start", STOPPED): RUNNING,
      ("pause", RUNNING): PAUSED,
      ("resume", PAUSED): RUNNING,
      ("stop", RUNNING): STOPPED,
      ("stop", PAUSED): STOPPED,
  }
  def _apply_action(self, action: str, cids: Iterable[int]) -> int:
      n = 0
      for cid in cids:
          old = self._cell_states[cid]
          new = _STATE_TRANSITION.get((action, old))
          if new is not None:
              self._cell_states[cid] = new
              self._on_state_changed(cid, new)  # 视觉+详情页通知
              n += 1
      return n
  ```
  把 4 个方法合并为 1 个 + 配置表，可读性反而更高（Plan agent E 建议）。

---

## 实施阶段（保持每步可运行）

| 阶段 | 改动 | 验证点 | 风险 |
|------|------|--------|------|
| **1. DataCell + 选区模型** | DataCell 加 `clicked` 信号、mousePressEvent 改 emit；MainWindow 加 `_selected_cids: Set[int]`、`_on_cell_clicked` handler；单选行为保持 | 点 cell → 选中；再点另一 cell → 切换 | 低，纯重构 |
| **2. 全选按钮** | 加 `_batch_buttons[0]`（☑ 全选）和 `_on_select_all`；选区 label 暂时单行 | 点全选 → 72 个 cell 全部高亮 | 低 |
| **3. 选中标签双行化** | 加 `panel_selection` QSS；拆为 primary + secondary 两个 QLabel | 视觉验证 | 低 |
| **4. _action_* 重构** | 合并为 `_apply_action(action, cids)` 状态转移表；`_update_buttons_by_state` 改 permissive + 计数 + label | 单选/多选时按钮 enable 正确 | 中，需细致 |
| **5. 全部开始/全部暂停** | 加 `_batch_buttons[1/2]`、`_on_start_all/_on_pause_all`、加 `batch_section` QSS 和帮助文本 | 点全部开始 → 所有 STOPPED → RUNNING | 中 |
| **6. 全部结束 + 二次确认** | 加 `_batch_buttons[3]`、`_on_stop_all`、`_confirm_stop_all`（QMessageBox）、`danger` QSS、bump `BUTTON_AREA_WIDTH=260`、bump `BUTTON_COUNT=8` | 触发 → 弹框 → 确认 → 所有非 STOPPED → STOPPED | 中，弹框可能影响焦点 |
| **7. 状态栏 + footer 同步** | `STATUS_BAR_NORMAL_TEMPLATE` 加 `SEL {n_sel}` | 状态栏显示选区数 | 极低 |
| **8. 收尾 + labels 集中** | 把硬编码字符串全部迁到 labels.py | grep 确认无裸字符串 | 低 |

每完成一个阶段立即重启 `Main.py` 跑通，再进入下一阶段。

---

## 验证

### 单元 / 集成
- 重启命令：`& E:\MiniConda\envs\Aging\python.exe d:\Aging\Main.py`
- 启动日志应无 `ImportError` / `AttributeError` / `TypeError`

### 端到端功能验证

| 场景 | 步骤 | 期望 |
|------|------|------|
| 单选回归 | 点击 CH-05 | 选中标签显示 `CH-05 // 已停止`；开始按钮启用 |
| 多选 | Ctrl+点击 CH-05、CH-10、CH-15 | 三个 cell 同时高亮；标签显示 `已选 3 / 72 台 / RUN 1 / PAUSED 0 / STOP 2` |
| 多选计数 badge | 选中 3 台 STOPPED + 2 台 RUNNING，按钮 label 变 `开始检测 (3/5)` | label 正确 |
| 多选执行 | 选中 5 台，1 RUNNING + 4 STOPPED，点开始 | 仅 4 台 STOPPED → RUNNING；按钮 label 重算 |
| 全选 | 点 ☑ 全选 | 72 个 cell 全部高亮 |
| 全部开始 | 关闭几个 cell 让有 STOPPED，点 ▶▶ 全部开始 | 所有 STOPPED → RUNNING；状态栏 RUN 数字变化 |
| 全部暂停 | 点 ⏸⏸ 全部暂停 | 所有 RUNNING → PAUSED；状态栏 PAUSED 数字变化 |
| 全部结束 - 取消 | 点 ■■ 全部结束 → 弹框 → 取消 | 无变化 |
| 全部结束 - 确认 | 点 ■■ 全部结束 → 弹框 → 是 | 所有非 STOPPED → STOPPED；状态栏 RUN/PAUSED 归 0 |
| 详情页联动 | 双击 CH-05 打开详情页 → 回到主页 → 全部开始 | CH-05 详情页倒计时按钮、状态同步更新 |
| 状态栏 SEL 字段 | 选中 5 台 | 状态栏显示 `SEL 5` |
| 视觉一致 | 全程 | 段落标题、按钮、危险按钮与系统整体风格一致 |

### 回归
- 双击 cell 打开详情页（既有功能）
- 详情页倒计时归零联动结束（既有功能，需要适配新 `_apply_action` 签名）
- 图例多选（上一轮已实现）
- QSS 主题不变

---

## 关键风险与缓解

| 风险 | 缓解 |
|------|------|
| `set_selected` 当前在 `DataCell.mousePressEvent` 中被自己调用，重构后必须由 MainWindow 统一调度，否则选区状态混乱 | Phase 1 完成后立即在 MainWindow 单步调试一次单选回归 |
| 4 个原按钮的 enable 矩阵改动可能让单 cell 控制行为退化 | 保留 permissive 逻辑的同时，强制覆盖 1 台选中时按钮 label 不加 `(X/Y)` 后缀（避免 `开始检测 (1/1)`） |
| 全部结束 弹框时主窗口可能失焦 | `QMessageBox` 默认 modal + parent=self，应能正常 |
| `BUTTON_AREA_WIDTH` 改动可能让 footer 文本溢出 | 视觉验证；必要时再 +20 |
| Shift 区间选择不在 v1 范围 | 明确写在 plan 中；用户后续反馈再加 |
| 详情页 `_on_countdown_finished` 调用 `_action_stop(cid)` 旧签名 | 适配为 `_apply_action("stop", [cid])` |

---

## 暂不在 v1 范围

- Shift+click 区间多选
- 框选（marquee）
- 批量恢复按钮（4 个原按钮里的"恢复暂停"已可对选区生效）
- 选中数量上限限制
- 选区持久化（重启后保留）
- 跨窗口的"选区同步"（如主页面选中，详情页高亮）
- 键盘快捷键（如 Esc 清空选区，Ctrl+A 全选）
