# Phase 3 实施计划：详情页（v3.0 LED 双击 → 电流+倒计时 实时页）

> **版本**：v2（含 8 项优化分析、文件依赖矩阵、分阶段流程、回滚机制）
> **更新时间**：2026-07-18
> **状态**：待审阅（v1 → v2 增量见 §11）
> **基线文档**：[ARCHITECTURE.md](file:///d:\Aging\ARCHITECTURE.md) / [project-restructure-4-phases.md](file:///d:\Aging\.trae\documents\project-restructure-4-phases.md) / [observability-hardening-plan.md](file:///d:\Aging\.trae\documents\observability-hardening-plan.md) / [code-redundancy-audit-2026-07-16.md](file:///d:\Aging\.trae\documents\code-redundancy-audit-2026-07-16.md)

---

## 0. 文档元信息

### 0.1 目标

闭合 v3.0 主页交互闭环 —— **双击 3D 机柜 LED** → **进入单 channel 内嵌详情页** → **看实时 I-t 曲线 + 倒计时 + 操作** → **返回主页**。

### 0.2 用户已确认的设计决策（v1）

| 维度 | 决策 | 备注 |
|---|---|---|
| 形态 | **内嵌页**（PageRouter key=`detail`） | 暂不进 nav bar，纯瞬时页 |
| 模式 | **单开**（点其他 LED → set_channel 切换） | 不支持同时多开 |
| 图表库 | pyqtgraph 0.14.0 `PlotWidget` | 已用，性能 30fps+ |
| 数据维度 | 电流 I-t（4 路）+ 倒计时面板 | **不**含温度 |
| 异常参考线 | y=0A 横线（红色虚线） | 归零 = 运行中电流跌至 0 |
| 异常填充 | current < 0.1A 且 state=RUNNING → 曲线段标红 | 复用 DetectionState |
| 时间窗 | 5min 滚动（180 帧 @ 2s/帧 × 4 路 × 1 主电流）| 复用 HistoryBuffer |
| 渲染节奏 | 30fps throttle（33ms tick）| 避免 60fps 抢 CPU |

### 0.3 v1 → v2 改动摘要（详见 §3）

| # | v1 做法 | v2 优化 | 采纳决策 |
|---|---|---|---|
| 3-OPT-1 | main_3d.py 加 `led_double_clicked` signal + DblClick case | HomeDashboard.eventFilter 统一监听 4 个 case（含 DblClick）| 待确认 |
| 3-OPT-2 | detail_page 内置本地 `_ring: deque(maxlen=150)` | 复用全局 `HistoryBuffer`，取消本地 ring | 待确认 |
| 3-OPT-3 | 33ms QTimer 持续轮询 | 事件驱动（append 信号触发 dirty）+ 5fps 兜底重绘 | 待确认 |
| 3-OPT-4 | `_state: DetectionState` 字段镜像 | 订阅 `CellController.state_changed` signal | 待确认 |
| 3-OPT-5 | 计划未列体验细节 | 补 4 项：LED 高亮 / 视角对准 / azimuth 保留 / 关闭确认 | 待确认 |
| 3-OPT-6 | 计划标注"重命名避免歧义" | 立即执行：`BUTTON_LABELS` → `MAIN_BUTTON_LABELS` | 待确认 |
| 3-OPT-7 | 计划未列文档同步 | ARCHITECTURE.md §2 §4 §6.6 同步更新 | 待确认 |
| 3-OPT-8 | 计划未列可观测性 | 补 6 个关键日志点（init/set_channel/tick/zero_anomaly/back/sample） | 待确认 |

---

## 1. 现状审计

### 1.1 已有资产（可直接复用）

| 资产 | 位置 | 复用方式 |
|---|---|---|
| 路由机制 | [app/ui/router.py](file:///d:\Aging\app\ui\router.py) | `router.register("detail", widget)` 一行接入 |
| 3D ray-pick | [app/ui/main_3d.py:343-389](file:///d:\Aging\app\ui\main_3d.py#L343-L389) `_tick_hover` | 暴露 `best_hovered_cid` 属性供双击事件读取 |
| 全局历史缓冲 | [app/data/history_buffer.py](file:///d:\Aging\app\data\history_buffer.py) | `snapshot(cid)` 替代本地 ring |
| 业务状态机 | [app/services/cell_controller.py](file:///d:\Aging\app\services\cell_controller.py) | `state_changed` signal 替代 _state 镜像 |
| 倒计时服务 | [app/services/countdown.py](file:///d:\Aging\app\services\countdown.py) | 详情页右侧"倒计时"面板直接调 `countdown.start(cid, dur_s)` |
| LED 辉光呼吸 | [app/ui/home_page.py:241-252](file:///d:\Aging\app\ui\home_page.py#L241-L252) | 30fps 经验可借鉴（见 3-OPT-3） |
| 通道号格式化 | [app/observability/narrative.py:129](file:///d:\Aging\app\observability\narrative.py#L129) `format_cid` | 详情页所有 CH-NN 文本走它，禁止 `f"CH-{n:02d}"` |
| 30s 周期采样日志 | [app/data/history_buffer.py:51-74](file:///d:\Aging\app\data\history_buffer.py#L51-L74) | 详情页 30s 采样模式直接对齐 |
| 状态栏 error badge | [app/core/config.py:56](file:///d:\Aging\app\core\config.py#L56) | 详情页错误提示走 `STATUS_BAR_ERROR_BADGE` |
| narrate 工具 | [app/observability/narrative.py](file:///d:\Aging\app\observability\narrative.py) | "用户双击打开详情 cid=5" 等事件用 `narrative.event()` |

### 1.2 待新建/修改文件清单

| # | 文件 | 类型 | 优先级 | 优化关联 |
|---|---|---|---|---|
| F1 | [app/core/labels.py](file:///d:\Aging\app\core\labels.py) | 改 | P0 | 3-OPT-6：消歧 + 8 个新 `DETAIL_*` 常量 |
| F2 | [app/ui/pages/detail_page.py](file:///d:\Aging\app\ui\pages\detail_page.py) | **新建** | P0 | 3-OPT-2/3/4：核心实现 + 事件驱动 + signal 订阅 |
| F3 | [app/ui/home_page.py](file:///d:\Aging\app\ui\home_page.py) | 改 | P0 | 3-OPT-1：eventFilter 加 DblClick + 路由注册 + 信号接线 |
| F4 | [app/ui/main_3d.py](file:///d:\Aging\app\ui\main_3d.py) | 改 | P1 | 暴露 `set_auto_rotate(bool)` 公共 API + `best_hovered_cid` 属性 |
| F5 | [ARCHITECTURE.md](file:///d:\Aging\ARCHITECTURE.md) | 改 | P1 | 3-OPT-7：§2 目录树 / §4 职责表 / §6.6 二次开发步骤 |
| F6 | [app/core/formatting.py](file:///d:\Aging\app\core\formatting.py) | 可能新建 | P2 | 如果 §A 阶段 C2 "format_cid 抽公共" 执行，则新建 |
| F7 | [app/ui/qss_utils.py](file:///d:\Aging\app\ui\qss_utils.py) | 改 | P2 | 如果 §A 阶段 C1 "_restyle 抽公共" 执行，新增样式模板 |

### 1.3 命名冲突清单（必须处理）

| 冲突项 | 现有 | 计划新增 | 处理方案 |
|---|---|---|---|
| 通道详情标题 | `DETAIL_WINDOW_TITLE_TEMPLATE`（v2 独立窗口残留） | `DETAIL_TITLE_TEMPLATE`（v3 内嵌页）| 保留 v2 为 legacy，**不删**；v3 走新名 |
| 按钮 label 元组 | `BUTTON_LABELS`（4 元素 tuple，已被电流页用）| `DETAIL_ACTION_LABELS`（同样 4 元素）| **重命名现有**为 `MAIN_BUTTON_LABELS`；新名按规划 |
| 单个按钮 label 字符串 | （无）| `DETAIL_ACTION_START` 等 4 个 | 命名加 `_TEXT` 后缀 → `DETAIL_ACTION_START_TEXT` |
| 倒计时到期提示 | `COUNTDOWN_EXPIRED_TEXT`（已有）| `DETAIL_ZERO_ANOMALY_TEMPLATE`（归零异常，**不同语义**）| 保持区分，按规划 |
| 图表 y 轴 | `CHART_CURRENT_Y_LABEL`（已有）| `DETAIL_CHART_Y_LABEL`（规划）| 复用现有的 `CHART_CURRENT_Y_LABEL`，**不**新增 |

### 1.4 架构契合点 vs 风险点

| 维度 | 契合 | 风险 |
|---|---|---|
| 路由层 | router.py 已就绪 | 无 |
| 数据层 | HB + CellController + Countdown 都支持订阅 | 本地 ring 重复（3-OPT-2 解决） |
| UI 层 | QSS 模板化、nav_bar 60px 风格统一 | 双击检测在两处都有，需明确归属（3-OPT-1 解决） |
| 状态层 | signal 广播模式 | _state 镜像造成双源不一致（3-OPT-4 解决） |
| 渲染层 | pyqtgraph 0.14 + 30fps 经验 | 持续轮询抢 CPU（3-OPT-3 解决） |
| 文档层 | ARCHITECTURE.md 流程清晰 | 计划没列同步更新（3-OPT-7 解决） |
| 可观测层 | 30s 采样模式成熟 | 详情页无 logger（3-OPT-8 解决） |

---

## 2. 文件改动清单（含依赖）

### 2.1 完整文件矩阵

| 文件 | 改动量 | 新增 | 修改 | 删除 | 依赖（谁会被影响） | 反向影响（谁会被影响） |
|---|---|---|---|---|---|---|
| [app/core/labels.py](file:///d:\Aging\app\core\labels.py) | ~30 行 | 9 个 `DETAIL_*` 常量；1 个 `MAIN_BUTTON_LABELS` 重命名 | 现有 `BUTTON_LABELS` → `MAIN_BUTTON_LABELS` | 无 | 所有引用 `BUTTON_LABELS` 的文件（电流页等）| [current_page.py](file:///d:\Aging\app\ui\pages\current_page.py) 需同步改 import |
| [app/ui/pages/detail_page.py](file:///d:\Aging\app\ui\pages\detail_page.py)（新建）| ~280 行 | 1 个 `DetailPage(QWidget)` 类 | 无 | 无 | labels / config / tokens / HistoryBuffer / CellController / DataSource | home_page 引用 / router 注册 |
| [app/ui/home_page.py](file:///d:\Aging\app\ui\home_page.py) | ~40 行 | 1 个 `_open_detail(cid)` 私有方法；1 个 `_on_detail_back()` | `eventFilter` 加 1 case（DblClick）；`__init__` 末尾注册 detail | 无 | detail_page（新建）/ main_3d（暴露 best_hovered_cid）| _open_detail 影响 3D 旋转暂停逻辑 |
| [app/ui/main_3d.py](file:///d:\Aging\app\ui\main_3d.py) | ~15 行 | `set_auto_rotate(bool)` 公共方法；`best_hovered_cid` 只读属性 | 私有方法 `_auto_rotate_active` 改为属性 | 无 | 无 | home_page 调 `set_auto_rotate` |
| [ARCHITECTURE.md](file:///d:\Aging\ARCHITECTURE.md) | ~25 行 | §2 目录树加 detail_page.py；§4 职责表加 1 行；§6.6 二次开发步骤加 1 段 | §2 目录树；§4 职责表；§6.6 步骤 | 无 | 无 | 无 |
| [app/core/formatting.py](file:///d:\Aging\app\core\formatting.py)（可能新建）| ~10 行 | `format_cid()` 公共 helper | 无 | 无 | 无 | 13 处 `f"CH-{n:02d}"` 调用点 |

### 2.2 依赖关系图（影响方向）

```
labels.py (F1)              formatting.py (F6, 可选)
    ↓                            ↓
detail_page.py (F2, 新建) ◀─── 引用 format_cid
    ↓                            ↓
home_page.py (F3)          detail_page.py
    ↓                            ↓
main_3d.py (F4)            main_3d.py (提供 best_hovered_cid)
    ↑                            ↓
    └──── home_page 调 set_auto_rotate
                                 ↓
ARCHITECTURE.md (F5)  ←─── 同步上述所有改动
```

**依赖顺序（编译时 / 运行时）**：
- F1（labels）→ F2（detail_page）→ F3（home_page）→ F4（main_3d）→ F5（文档）
- F6（formatting）独立可前置；F7（qss_utils）独立可前置

### 2.3 改动行数与时长预估（含优化项）

| 阶段 | 文件 | 行数 | 时长 |
|---|---|---|---|
| 阶段 A 前置清理 | F1（labels）+ 1 处电流页 import | ~35 行 | 25 min |
| 阶段 B 核心 | F2（detail_page 新建）| ~280 行 | 1.5 h |
| 阶段 B 编排 | F3（home_page）+ F4（main_3d）| ~55 行 | 40 min |
| 阶段 C 体验 | detail_page 内 4 项细节 | ~40 行 | 40 min |
| 阶段 D 文档 | F5（ARCHITECTURE.md）| ~25 行 | 15 min |
| 验证 | py_compile + import + 启动 | — | 15 min |
| **合计** | **5 个文件** | **~435 行** | **~3.5 h** |

---

## 3. 优化项详细说明

### 3.1 【架构】eventFilter 双击检测应放 HomeDashboard

**问题**：
- v1 plan §5 把 `led_double_clicked` signal 放在 Rack3DView 内部
- 违反 [main_3d.py:18-23](file:///d:\Aging\app\ui\main_3d.py#L18-L23) docstring 原则"单一职责：只管 3D 渲染"
- Rack3DView 跨层依赖 HomePage/PageRouter

**v2 做法**：
- Rack3DView 暴露 `best_hovered_cid: Optional[int]` 只读属性（已经在 _tick_hover 中计算）
- HomeDashboard.eventFilter 增加 `QEvent.MouseButtonDblClick` case
- HomeDashboard 私有信号 `led_double_clicked = pyqtSignal(int)` → connect 到 `self._open_detail`

**涉及文件**：F3（home_page.py）+ F4（main_3d.py 暴露 best_hovered_cid）

**风险**：低，eventFilter 是单点维护；缓解：plan §7 已识别"双击 ray-pick 不准"风险，仅 `best_cid ≠ None` 时 emit

**回滚**：删除 eventFilter 新增 case，删除 led_double_clicked 私有信号

---

### 3.2 【数据】复用全局 HistoryBuffer，取消本地 ring

**问题**：
- v1 plan §3.1 `_ring: deque(maxlen=150)` 是本地缓冲
- 已有 [HistoryBuffer](file:///d:\Aging\app\data\history_buffer.py) 全局共享，72 通道都索引好了
- 本地 ring 造成**双份数据**：详情页视图 vs 全局视图，状态不一致风险

**v2 做法**：
```python
class DetailPage(QWidget):
    def __init__(self, ..., history: HistoryBuffer, ...):
        # 删 _ring；改用 history.snapshot(self._cid)
        pass
    def _on_append(self, reading: ChannelReading):
        if reading.channel_id == self._cid:
            self._dirty = True  # 事件驱动
```

**涉及文件**：F2（detail_page.py）

**风险**：低，HistoryBuffer 已有 5min × 72 容量。缓解：snapshot() 是 O(N) 读取，每 2s 1 次 N=150，无性能压力

**回滚**：恢复本地 ring 字段，重新订阅 DataSource（不再订阅 HistoryBuffer.append）

---

### 3.3 【渲染】30fps 重绘 → 事件驱动 + 5fps 兜底

**问题**：
- v1 plan §3.2 `33ms QTimer` 持续轮询，无新数据也重绘
- 持续 setData 抢 CPU，闪烁风险（plan §7 已识别"中"级风险）

**v2 做法**：
```python
# 主路径：事件驱动
def _on_append(self, reading: ChannelReading):
    if reading.channel_id == self._cid:
        self._dirty = True

def _tick_chart(self):
    if not self._dirty:
        return  # 无新数据，跳过
    self._render()
    self._dirty = False

# 兜底：5fps 心跳（200ms）防止 signal 丢失导致"卡死"
self._tick_timer = QTimer(self)
self._tick_timer.setInterval(200)  # 5fps 兜底
```

**涉及文件**：F2（detail_page.py）

**风险**：低，事件驱动是 Qt 推荐模式。缓解：5fps 兜底防 signal 丢失

**回滚**：把 `setInterval(200)` 改回 `setInterval(33)`，删除 `_dirty` 短路

---

### 3.4 【状态】`_state` 镜像 → 订阅 state_changed

**问题**：
- v1 plan §3.1 `_state: DetectionState` 字段镜像
- [CellController](file:///d:\Aging\app\services\cell_controller.py) 已有 `state_changed` signal
- 镜像字段造成双源：主页 3D LED 显示 RUNNING，但详情页 _state 还显示 STOPPED

**v2 做法**：
```python
def __init__(self, ..., cell_controller: CellController, ...):
    self._controller = cell_controller
    # 订阅而非镜像
    self._controller.state_changed.connect(self._on_state_changed)

def _on_state_changed(self, cid: int, new_state: DetectionState):
    if cid == self._cid:
        # 更新详情页右侧"状态"标签 + 决定是否启用异常检测
        pass
```

**涉及文件**：F2（detail_page.py）

**风险**：中，状态同步逻辑可能漏改某 UI 元素。缓解：所有 `_state.X` 引用替换为订阅回调内的局部变量

**回滚**：恢复 `_state` 字段，删除 state_changed 订阅，改用 `controller.state_of(cid)` 拉取

---

### 3.5 【体验】补 4 个细节（plan 漏列）

| 细节 | 涉及位置 | 时长 |
|---|---|---|
| 双击 hover 时 LED **高亮 200ms**（让用户知道点中了）| F2（detail_page 通过 home_page 触发）| 10 min |
| 进入 detail 时**视角自动旋转对准当前 cid**（不丢锚点）| F4（main_3d 加 `set_auto_rotate` + 视角锁定）| 15 min |
| 返回主页时**保留进入前的 azimuth 偏移**（用户视野连续）| F3（home_page 暂存 `_azimuth_offset_before_detail`）| 5 min |
| 详情页关闭时**若 cell 仍 RUNNING → 确认弹窗**（防误关）| F2（detail_page closeEvent）| 10 min |

**风险**：低，纯体验层；缓解：每项都可在 5 min 内回滚

---

### 3.6 【命名】`BUTTON_LABELS` 重命名消歧

**问题**：
- v1 plan §4 末尾注释"需重命名避免歧义"
- [labels.py:54-59](file:///d:\Aging\app\core\labels.py#L54-L59) 已有 `BUTTON_LABELS`（4 元素 tuple，被电流页用）
- 新增的 `DETAIL_ACTION_LABELS` 与之同名空间冲突

**v2 做法**：
```python
# labels.py
- BUTTON_LABELS = ("开始检测", "暂停检测", "恢复暂停", "结束检测")
+ MAIN_BUTTON_LABELS = ("开始检测", "暂停检测", "恢复暂停", "结束检测")
+ DETAIL_ACTION_LABELS = ("DETAIL_ACTION_START_TEXT", ...)
+ DETAIL_ACTION_START_TEXT = "▶ 开始"
+ DETAIL_ACTION_PAUSE_TEXT = "⏸ 暂停"
+ DETAIL_ACTION_RESUME_TEXT = "↻ 继续"
+ DETAIL_ACTION_STOP_TEXT  = "■ 停止"
```

**涉及文件**：F1（labels.py）+ 所有引用 `BUTTON_LABELS` 的文件（搜索替换）

**风险**：中，rename 影响多文件。**缓解**：用 `grep -r "BUTTON_LABELS" d:/Aging/app/` 先建清单逐条改

**回滚**：rename 反向操作；labels.py git diff 一行 revert 即可

---

### 3.7 【文档】ARCHITECTURE.md 同步更新

**问题**：
- [ARCHITECTURE.md §11](file:///d:\Aging\ARCHITECTURE.md) 变更流程要求"先改本文档，再改代码"
- 计划文档未列同步更新

**v2 做法**（按 [ARCHITECTURE.md §11](file:///d:\Aging\ARCHITECTURE.md) 流程）：

1. §2 目录树 `app/ui/pages/` 下加 `detail_page.py`
2. §4 文件职责表加 1 行：
   ```
   | [app/ui/pages/detail_page.py](file:///d:\Aging/app/ui/pages/detail_page.py) | 单 channel 详情 | `DetailPage` |
   ```
3. §6.6 二次开发步骤加 1 段"内嵌页（非 nav 项）"流程

**涉及文件**：F5（ARCHITECTURE.md）

**风险**：无，文档改动

**回滚**：git diff 还原

---

### 3.8 【可观测性】6 个关键日志点

按 [observability-hardening-plan.md §2.2](file:///d:\Aging\.trae\documents\observability-hardening-plan.md) 规范：

| 日志点 | 级别 | 格式 | 节流 |
|---|---|---|---|
| `__init__` | INFO | `"detail page initialized"` | 一次性 |
| `set_channel(cid)` | INFO | `"detail page open: cid={cid}"` | 一次性 |
| `_tick_chart` 重绘 | DEBUG | （高频，**不**打）| — |
| 归零异常检测触发 | INFO | `"detail: cid={cid} zero-anomaly segment red, range=[{t1}s, {t2}s]"` | 事件触发 |
| `requested_back` emit | INFO | `"detail page close: cid={cid}"` | 一次性 |
| 30s 采样 | INFO | `"detail tick sample: cid={cid} points={n} zero_anomaly={bool}"` | 30s 周期 |

**涉及文件**：F2（detail_page.py）+ logger 初始化

**风险**：低，与 [history_buffer.py:51-74](file:///d:\Aging\app\data\history_buffer.py#L51-L74) 30s 采样对齐

**回滚**：删除 logger 初始化 + 6 个 log 调用

---

## 4. 实施流程（分阶段）

```
┌──────────────────────────────────────────────────────────────┐
│ 阶段 A：前置清理（25 min，可选）                              │
│   A1. labels.py 重命名 BUTTON_LABELS → MAIN_BUTTON_LABELS   │
│   A2. 全工程 grep + 替换引用                                  │
│   A3. （可选）抽 format_cid 公共 helper                     │
│   A4. （可选）抽 _restyle 公共 helper                        │
├──────────────────────────────────────────────────────────────┤
│ 阶段 B：核心实现（2.5 h）                                    │
│   B1. labels.py +9 个 DETAIL_* 常量                         │
│   B2. detail_page.py 新建（核心 280 行）                     │
│   B3. main_3d.py 暴露 set_auto_rotate + best_hovered_cid   │
│   B4. home_page.py eventFilter + 路由注册 + 信号接线         │
│   B5. py_compile 兜底                                        │
│   B6. import smoke + 启动 Main.py                            │
├──────────────────────────────────────────────────────────────┤
│ 阶段 C：体验打磨（40 min）                                    │
│   C1. LED 高亮 200ms                                         │
│   C2. 视角自动旋转对准当前 cid                                │
│   C3. azimuth 偏移保留                                       │
│   C4. 关闭确认弹窗（仅 RUNNING 状态）                        │
│   C5. 启动 Main.py 实操验证                                  │
├──────────────────────────────────────────────────────────────┤
│ 阶段 D：文档收尾（15 min）                                    │
│   D1. ARCHITECTURE.md §2 §4 §6.6 同步更新                   │
│   D2. 整体 git diff review                                  │
│   D3. 完整验证流程跑一遍                                      │
└──────────────────────────────────────────────────────────────┘
```

### 4.1 阶段 A 详细步骤（前置清理）

| 步骤 | 命令/操作 | 验证 |
|---|---|---|
| A1 | 编辑 [labels.py:54-59](file:///d:\Aging\app\core\labels.py#L54-L59) `BUTTON_LABELS` → `MAIN_BUTTON_LABELS` | `rg "BUTTON_LABELS" d:/Aging/app/` 仅剩新名 |
| A2 | 全工程替换引用：`current_page.py` / `data_page.py` 等 | `py_compile` 全过 |
| A3（可选）| 新建 [formatting.py](file:///d:\Aging\app\core\formatting.py) 加 `format_cid()` | `rg 'f"CH-\{' d:/Aging/app/` 命中数从 13 降到 0 |
| A4（可选）| 编辑 [qss_utils.py](file:///d:\Aging\app\ui\qss_utils.py) 暴露 `refresh_qss()` | 4 处 `_restyle` 复制删除 |

### 4.2 阶段 B 详细步骤（核心实现）

按 v1 plan §9 顺序，每完成一步立即 `py_compile` 兜底：

| 步骤 | 改动 | 验证 |
|---|---|---|
| B1 | [labels.py](file:///d:\Aging\app\core\labels.py) +9 个 `DETAIL_*` 常量 | `py_compile app/core/labels.py` |
| B2 | [detail_page.py](file:///d:\Aging\app\ui\pages\detail_page.py) 新建 ~280 行 | `py_compile app/ui/pages/detail_page.py` |
| B3 | [main_3d.py](file:///d:\Aging\app\ui\main_3d.py) 暴露 `set_auto_rotate` + `best_hovered_cid` | `py_compile app/ui/main_3d.py` |
| B4 | [home_page.py](file:///d:\Aging\app\ui\home_page.py) eventFilter + 路由 + 接线 | `py_compile app/ui/home_page.py` |
| B5 | 全工程 `py_compile` | 见 §6.1 |
| B6 | `import Main` + 启动 | 见 §6.2-6.3 |

### 4.3 阶段 C 详细步骤（体验打磨）

每项可独立完成 + 独立回滚：

| 步骤 | 改动 | 验证 |
|---|---|---|
| C1 | `Rack3DView.set_led_highlight(cid, duration_ms)` 公共方法 | 双击 → 200ms 高亮可见 |
| C2 | `Rack3DView.snap_to_cid(cid)` 自动计算相机角度对准 | 进入 detail → LED 居中 |
| C3 | `HomeDashboard._azimuth_offset_before_detail` 暂存 | 反复进出 → 视野保留 |
| C4 | `DetailPage.closeEvent` 检查 `state_of(cid) == RUNNING` → 弹窗 | RUNNING 状态关闭 → 弹窗出现 |

### 4.4 阶段 D 详细步骤（文档收尾）

| 步骤 | 改动 | 验证 |
|---|---|---|
| D1 | [ARCHITECTURE.md](file:///d:\Aging\ARCHITECTURE.md) §2/§4/§6.6 | `git diff ARCHITECTURE.md` 内容核对 |
| D2 | `git diff --stat` 全工程差异 review | 改动行数 ≈ 435 行 |
| D3 | 完整跑 §6 验证流程 | 全部通过 |

---

## 5. 依赖说明

### 5.1 内部模块依赖（导入方向）

```
DetailPage 依赖：
├── app.core.config           (WINDOW_SIZE, GRID_*, COUNTDOWN_*)
├── app.core.tokens           (DEFAULT_TOKENS, Colors, Sizing)
├── app.core.labels           (DETAIL_*, MAIN_BUTTON_LABELS, STATUS_*)
├── app.core.formatting       (format_cid, format_hms) [可选，若 A3 执行]
├── app.data.protocol         (ChannelReading)
├── app.data.history_buffer   (HistoryBuffer.snapshot, append signal)
├── app.services.cell_controller (CellController.state_changed, state_of)
├── app.services.countdown    (CountdownService, 可选内置或外部传入)
├── app.observability         (get_logger, narrative.event, safe_call)
└── pyqtgraph + PyQt5         (PlotWidget, QWidget, QTimer, pyqtSignal)
```

```
HomePage 依赖（增量）：
├── app.ui.pages.detail_page  (DetailPage)
└── app.ui.main_3d            (Rack3DView.set_auto_rotate, best_hovered_cid)
```

```
Rack3DView 依赖（增量）：
└── 无新依赖（仅暴露已有方法/属性）
```

### 5.2 外部包依赖（environment.yml 锁定）

| 包 | 版本 | 用途 |
|---|---|---|
| PyQt5 | 5.15.11 | 基础 GUI（QWidget / QTimer / pyqtSignal / eventFilter）|
| pyqtgraph | 0.14.0 | PlotWidget / InfiniteLine / FillBetweenItem |
| numpy | 1.26.x | 曲线数据 buffer |

**无新依赖**。所有包已 [environment.yml](file:///d:\Aging\environment.yml) 锁定。

### 5.3 数据流依赖

```
DataSource (DemoDataSource)
    ↓ reading.emit(reading) [2s 节奏, 72 通道]
HistoryBuffer.append(reading) [全局共享, 5min × 72]
    ↓ append signal
DetailPage._on_append(reading) [订阅，只关心 _cid]
    ↓ 标记 _dirty
DetailPage._tick_chart() [5fps 兜底]
    ↓ history.snapshot(_cid)
    ↓ setData / 异常检测
PlotWidget 重绘
```

**关键不变式**：
- 详情页**不**直接订阅 DataSource（避免和 HistoryBuffer 双源）
- 详情页**不**修改 HistoryBuffer（只读 snapshot）
- CellController 状态变化通过 signal 单向广播，详情页**只读**

### 5.4 样式依赖

```
DetailPage 样式：
├── app.core.tokens.DEFAULT_TOKENS (Colors, FontSizes, Sizing, Fonts)
├── app.styles.templates          (main_window / data_cell / button 模板复用)
└── app.ui.qss_utils.refresh_qss   (dynamic property 修改后刷新)
```

**新增样式**：建议在 [app/styles/templates.py](file:///d:\Aging\app\styles\templates.py) 加 1 段 `detail_page` 模板，遵循现有按 QWidget 分块规范。

---

## 6. 风险评估

### 6.1 风险矩阵

| 风险 | 等级 | 触发条件 | 缓解措施 | 检测方法 |
|---|---|---|---|---|
| pyqtgraph 5.15 + Qt 5.15 ABI 不兼容 | 中 | detail_page.py 首次 import | 已验证环境（pyqtgraph 0.14 + PyQt5 5.15.11 长期使用）| import smoke |
| DataSource 2s 节奏下，30fps 重绘浪费 | 低 | 无新数据也重绘 | 3-OPT-3：事件驱动 + 5fps 兜底 | `_tick_chart` 日志采样看空跑比例 |
| 双击 ray-pick 不准（点空白处也触发）| 中 | best_cid 误判 | 仅当 best_cid ≠ None 时 emit | 主页面肉眼观察双击命中 |
| 多个 LED 一起开 detail | 低 | 多线程或 fast double-click | 3-OPT-1：单开语义 set_channel 覆盖 | 连续双击多个 LED 验证 |
| 详情页与电流检测页选区不一致 | 低 | 选区混乱 | 详情页只看自己 _cid，不共享 selection | 电流页选区不影响详情页 |
| chart 频繁 setData 导致闪烁 | 中 | 30fps 持续轮询 | 3-OPT-3：事件驱动 + 5fps 兜底 | 视觉验证 |
| BUTTON_LABELS 重命名影响电流页 | 中 | 引用遗漏 | A1-A2 阶段：grep 清单逐条改 | py_compile 全过 + 启动电流页 |
| _state 镜像造成双源不一致 | 中 | 主页和详情页状态不同步 | 3-OPT-4：订阅 state_changed | 主页面启动 cell → 详情页应同步 |
| HomeDashboard 旋转状态被 detail 干扰 | 中 | 进出 detail 视野跳跃 | 3-OPT-5-C3：保留 azimuth + 视角对准 | 反复进出 detail 验证 |

### 6.2 缓解优先级

| 缓解项 | 实施位置 | 优先级 |
|---|---|---|
| 3-OPT-1 eventFilter 归属 | 阶段 B4 | **必须** |
| 3-OPT-2 复用 HB 取消 ring | 阶段 B2 | **必须** |
| 3-OPT-3 事件驱动 | 阶段 B2 | **必须** |
| 3-OPT-4 订阅 state_changed | 阶段 B2 | **必须** |
| 3-OPT-5 体验 4 项 | 阶段 C | 可选（但建议）|
| 3-OPT-6 BUTTON_LABELS 消歧 | 阶段 A1 | **必须**（前置）|
| 3-OPT-7 ARCHITECTURE 同步 | 阶段 D1 | **必须**（流程要求）|
| 3-OPT-8 日志点 | 阶段 B2 | 建议（observability 一致性）|

---

## 7. 回滚机制

### 7.1 整体回滚（git revert）

**前置**：每阶段结束**必须** `git commit` 留可回滚锚点（参考 [project-restructure-4-phases.md §设计原则 7](file:///d:\Aging\.trae\documents\project-restructure-4-phases.md)）。

```bash
# 整体回滚到 Phase 3 之前
git log --oneline -20  # 找到 Phase 3 起点 commit
git revert <phase-3-start-commit>..HEAD  # 或
git reset --hard <phase-3-start-commit>  # 强回滚（破坏后续 commit）
```

### 7.2 分阶段回滚

每个阶段独立 commit，单独 revert：

| 阶段 | commit 标识 | 回滚命令 |
|---|---|---|
| 阶段 A | `phase-3-A: rename BUTTON_LABELS` | `git revert <A-commit>` |
| 阶段 B | `phase-3-B: detail_page core` | `git revert <B-commit>` |
| 阶段 C | `phase-3-C: experience polish` | `git revert <C-commit>` |
| 阶段 D | `phase-3-D: arch doc sync` | `git revert <D-commit>` |

### 7.3 单文件回滚（单优化项回滚）

| 优化项 | 单文件回滚 |
|---|---|
| 3-OPT-1 eventFilter | `git checkout HEAD~1 -- app/ui/home_page.py` + 删除新 case |
| 3-OPT-2 本地 ring | 恢复 `_ring: deque(maxlen=150)` 字段，删除 HB 注入 |
| 3-OPT-3 事件驱动 | `setInterval(200)` 改回 `setInterval(33)`，删除 `_dirty` 短路 |
| 3-OPT-4 state 订阅 | 恢复 `_state` 字段，删除 state_changed 订阅 |
| 3-OPT-5 体验 | 4 项分别独立，每项 5 min 回滚 |
| 3-OPT-6 BUTTON_LABELS | rename 反向操作（MAIN_BUTTON_LABELS → BUTTON_LABELS）+ 引用替换 |
| 3-OPT-7 文档 | `git checkout HEAD~1 -- ARCHITECTURE.md` |
| 3-OPT-8 日志 | 删除 logger 初始化 + 6 个 log 调用 |

### 7.4 紧急回滚脚本（PowerShell）

```powershell
# emergency-rollback-phase3.ps1
# 用法：.\emergency-rollback-phase3.ps1
# 作用：删除 detail_page.py + 反向修改 home_page.py + main_3d.py + labels.py

$repoRoot = "d:\Aging"

# 1. 删除 detail_page.py
if (Test-Path "$repoRoot\app\ui\pages\detail_page.py") {
    Remove-Item "$repoRoot\app\ui\pages\detail_page.py" -Force
    Write-Host "✓ 删除 detail_page.py" -ForegroundColor Yellow
}

# 2. 反向修改 home_page.py（手工操作，见 git diff）
# 提示：git checkout HEAD~1 -- app/ui/home_page.py

# 3. 反向修改 main_3d.py
# 提示：git checkout HEAD~1 -- app/ui/main_3d.py

# 4. 反向修改 labels.py
# 提示：git checkout HEAD~1 -- app/core/labels.py

# 5. 验证
& E:\MiniConda\envs\Aging\python.exe -m py_compile `
    $repoRoot\app\core\labels.py `
    $repoRoot\app\ui\home_page.py `
    $repoRoot\app\ui\main_3d.py `
    $repoRoot\app\ui\router.py

Write-Host "✓ 紧急回滚完成（请人工 review 改动）" -ForegroundColor Green
```

### 7.5 验证可回滚性

每阶段结束**强制验证**：
```bash
# 1) 备份当前
cp -r app/ui/pages/ app/ui/pages.bak/

# 2) 模拟回滚
git stash  # 暂存本阶段改动

# 3) 启动验证
& E:\MiniConda\envs\Aging\python.exe d:\Aging\Main.py
# 应正常启动（即使无 detail 功能）

# 4) 恢复
git stash pop
rm -rf app/ui/pages.bak/
```

---

## 8. 验证步骤

### 8.1 编译检查（py_compile）

```powershell
cd d:\Aging
& E:\MiniConda\envs\Aging\python.exe -m py_compile `
  d:\Aging\app\core\labels.py `
  d:\Aging\app\core\formatting.py `
  d:\Aging\app\ui\pages\detail_page.py `
  d:\Aging\app\ui\main_3d.py `
  d:\Aging\app\ui\home_page.py `
  d:\Aging\app\ui\router.py `
  d:\Aging\app\data\history_buffer.py `
  d:\Aging\app\services\cell_controller.py
```

### 8.2 import smoke

```powershell
& E:\MiniConda\envs\Aging\python.exe -c "
import Main
from app.ui.pages.detail_page import DetailPage
print('DetailPage import OK')
"
```

### 8.3 启动验证

```powershell
& E:\MiniConda\envs\Aging\python.exe d:\Aging\Main.py
```

### 8.4 交互验证清单

| 步骤 | 操作 | 期望 |
|---|---|---|
| 1 | 启动应用 | 主页 3D 渲染、5 路由就绪 |
| 2 | 双击任意 LED（如 cid=5）| 路由切到 detail、I-t 曲线开始画、归零红线可见 |
| 3 | 等待 30s | 看到 `detail tick sample` 日志 1 条 |
| 4 | 故意启动 cid=1 在主页 → 立即双击 cid=1 | 详情页状态同步显示 RUNNING（3-OPT-4 验证）|
| 5 | 在详情页点"开始"按钮 | 主页对应 LED 立即变绿（signal 双向验证）|
| 6 | 在详情页点"返回主页" | 路由回 home、3D 旋转保留进入前 azimuth |
| 7 | 在 RUNNING 状态点"返回" | 弹确认窗（3-OPT-5-C4 验证）|
| 8 | 点空白处（非 LED）| 不进入 detail（3-OPT-1 验证 best_cid=None）|
| 9 | 连续双击不同 LED | 详情页切换 channel（单开语义验证）|

### 8.5 日志验证

```powershell
# 启动后查看 logs/app.log，应包含：
Get-Content d:\Aging\logs\app.log -Tail 50 | Select-String "detail"
```

期望命中：
- `detail page initialized`
- `detail page open: cid=N`
- `detail tick sample: cid=N points=N`（30s 后出现）
- `detail: cid=N zero-anomaly segment red`（异常时）
- `detail page close: cid=N`

### 8.6 硬编码自检

```powershell
# 检查 detail_page.py 是否违反硬编码禁令
rg "#[0-9a-fA-F]{6}" d:\Aging\app\ui\pages\detail_page.py
# 期望：无命中

rg 'f"CH-\{' d:\Aging\app\ui\pages\detail_page.py
# 期望：无命中（必须走 format_cid）

rg "random\." d:\Aging\app\ui\pages\detail_page.py
# 期望：无命中（数据生成在 DataSource 实现）

rg 'setStyleSheet\(' d:\Aging\app\ui\pages\detail_page.py
# 期望：无命中（QSS 走 StylesheetBuilder）
```

---

## 9. 决策点（待用户确认）

### 9.1 优化项采纳决策

| # | 优化项 | 建议 | 决策 |
|---|---|---|---|
| 3-OPT-1 | eventFilter 放 HomeDashboard | ✅ 采纳（架构更清晰）| [ ] |
| 3-OPT-2 | 复用全局 HB 取消本地 ring | ✅ 采纳（数据一致性）| [ ] |
| 3-OPT-3 | 30fps → 事件驱动 + 5fps 兜底 | ✅ 采纳（性能）| [ ] |
| 3-OPT-4 | _state 镜像 → 订阅 state_changed | ✅ 采纳（状态一致性）| [ ] |
| 3-OPT-5 | 4 个体验细节 | ✅ 全部采纳 | [ ] |
| 3-OPT-6 | BUTTON_LABELS 消歧 | ✅ 采纳（前置必要）| [ ] |
| 3-OPT-7 | ARCHITECTURE.md 同步 | ✅ 采纳（流程要求）| [ ] |
| 3-OPT-8 | 6 个日志点 | ✅ 采纳（observability 一致性）| [ ] |

### 9.2 阶段执行决策

| 决策项 | 选项 | 建议 |
|---|---|---|
| 阶段 A 是否执行？| A: 完整执行（25 min）/ B: 仅 A1-A2（10 min）/ C: 跳过 | A: 完整执行（如果也想清 TOP 5 冗余）|
| 阶段 C 体验是否本轮做？| A: 全做 / B: 只做 C4 关闭确认 / C: 跳过 | A: 全做（40 min 性价比高）|
| 是否先 git commit 当前状态？| A: 是 / B: 否 | A: 是（无 git 现状见 ARCHITECTURE §10）|
| 是否先清 TOP 5 冗余？| A: 是 / B: 否 | A: 是（让 Phase 3 可用 format_cid / refresh_qss）|

### 9.3 风险接受决策

| 风险 | 是否接受？|
|---|---|
| pyqtgraph ABI 兼容性 | [ ] |
| 双击 ray-pick 误判 | [ ] |
| chart 闪烁（30fps）| [ ]（已被 3-OPT-3 缓解）|
| BUTTON_LABELS 重命名影响面 | [ ]（阶段 A 全工程 grep 验证）|

---

## 10. 与其他文档的关系

| 文档 | 关系 |
|---|---|
| [ARCHITECTURE.md](file:///d:\Aging\ARCHITECTURE.md) | 总体架构；本计划**不**破坏 §3 依赖方向；§11 要求同步更新 |
| [project-restructure-4-phases.md](file:///d:\Aging\.trae\documents\project-restructure-4-phases.md) | 4 阶段重构已落地；本计划是后续 Phase 3 |
| [observability-hardening-plan.md](file:///d:\Aging\.trae\documents\observability-hardening-plan.md) | 业务核心层 + 异常一致层已完成；本计划 §3-OPT-8 沿用其规范 |
| [code-redundancy-audit-2026-07-16.md](file:///d:\Aging\.trae\documents\code-redundancy-audit-2026-07-16.md) | TOP 5 冗余未清；本计划 §4 阶段 A 关联其中 C1 / C2 / M1 / M2 / M5 |
| [batch-start-pause-discussion.md](file:///d:\Aging\.trae\documents\batch-start-pause-discussion.md) | 批量控制已实现；本计划 detail 操作按钮**不**涉及批量 |
| [cell-controller-design.md](file:///d:\Aging\.trae\documents\cell-controller-design.md) | CellController 设计文档；本计划 §3-OPT-4 引用 state_changed |
| [multi-select-batch-control.md](file:///d:\Aging\.trae\documents\multi-select-batch-control.md) | 多选批量控制；本计划**不**涉及 |
| [optimization-analysis-2026-07-11.md](file:///d:\Aging\.trae\documents\optimization-analysis-2026-07-11.md) | 早期优化分析；本计划延续其方向 |

---

## 11. 版本历史

| 版本 | 日期 | 改动 |
|---|---|---|
| v1 | 2026-07-18 | 初版：3 个文件改动清单 + 280 行 DetailPage + 验证 |
| v2 | 2026-07-18 | **本次更新**：<br>1. §1 现状审计（已有资产/待改/冲突/契合）<br>2. §2 完整文件矩阵（行数 + 依赖）<br>3. §3 8 项优化详细说明<br>4. §4 4 阶段实施流程（A/B/C/D 详细步骤）<br>5. §5 依赖说明（模块/包/数据流/样式）<br>6. §6 风险矩阵（9 项风险 + 缓解）<br>7. §7 回滚机制（整体/分阶段/单文件/紧急脚本/可回滚验证）<br>8. §8 6 类验证（编译/import/启动/交互/日志/硬编码）<br>9. §9 决策点（3 类共 14 项）<br>10. §10 与其他文档关系 |

---

*待用户审阅 §9 决策点后，进入实施*
