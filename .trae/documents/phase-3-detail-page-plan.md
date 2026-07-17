# Phase 3 实施计划：详情页（v3.0 LED 双击 → 电流+倒计时 实时页）

> 目标：闭合 v3.0 主页交互闭环 —— 双击 3D 机柜 LED → 进入单 channel 详情页 → 看实时 I-t 曲线 + 倒计时 → 返回主页。
> 设计决策（用户确认）：**内嵌 / 单开 / pyqtgraph / 电流+倒计时 / 归零异常线**

---

## 1. 设计要点

| 维度 | 决策 | 备注 |
|---|---|---|
| 形态 | 内嵌页（PageRouter key=`detail`） | 暂不进 nav bar，纯瞬时页 |
| 模式 | 单开（点其他 LED → set_channel 切换） | 不支持同时多开 |
| 图表库 | pyqtgraph 0.14.0 `PlotWidget` | 已用，性能 30fps+ |
| 数据维度 | 电流 I-t（4 路）+ 倒计时面板 | **不**含温度 |
| 异常参考线 | y=0A 横线（红色虚线） | 归零 = 运行中电流跌至 0 |
| 异常填充 | current < 0.1A 且 state=RUNNING → 曲线段标红 | 复用 [DetectionState](file:///d:/Aging/app/services/cell_controller.py) |
| 时间窗 | 5min 滚动（180 帧 @ 2s/帧 × 4 路 × 1 主电流）| 复用 [HistoryBuffer](file:///d:/Aging/app/data/history_buffer.py) |
| 渲染节奏 | 30fps throttle（33ms tick）| 避免 60fps 抢 CPU |

---

## 2. 文件改动清单

| # | 文件 | 类型 | 估时 | 内容 |
|---|---|---|---|---|
| 3.1 | [app/core/labels.py](file:///d:/Aging/app/core/labels.py) | 改 | 15min | +8 个 DETAIL_PAGE_* 常量（title/back/zero-anomaly/badge）|
| 3.2 | [app/ui/pages/detail_page.py](file:///d:/Aging/app/ui/pages/detail_page.py) | **新建** | 1.5h | `DetailPage(QWidget)` ~280 行（详见 §3）|
| 3.3 | [app/ui/main_3d.py](file:///d:/Aging/app/ui/main_3d.py) | 改 | 30min | + `led_double_clicked = pyqtSignal(int)` + eventFilter 双击检测（复用已有 hover ray-pick）|
| 3.4 | [app/ui/home_page.py](file:///d:/Aging/app/ui/home_page.py) | 改 | 30min | 实例化 `DetailPage`、注册到 router、接双击→打开 / 返回→home |
| 3.5 | detail_page.py 内置 | （含在 3.2）| 30min | 30fps tick timer + decimate 策略 + 5min ring |
| 3.6 | （验证）| 改 | 15min | py_compile + import smoke + 启动 Main.py |
| **合计** | 4 个文件 | | **~3h** | |

**完全不动**：[CellController](file:///d:/Aging/app/services/cell_controller.py)、[CountdownService](file:///d:/Aging/app/services/countdown.py)、[HistoryBuffer](file:///d:/Aging/app/data/history_buffer.py)、[DataSource](file:///d:/Aging/app/data/protocol.py) 协议

---

## 3. DetailPage 类骨架（280 行）

```python
class DetailPage(QWidget):
    """单 channel 详情：I-t 实时曲线 + 倒计时 + 控制按钮。"""

    # 信号
    requested_back = pyqtSignal()         # 用户点"返回主页"
    action_requested = pyqtSignal(str, int)  # (action, cid) → CellController

    def __init__(self, data_source, history, cell_controller, parent=None):
        # 4 个组件：header(56) + chart(*) + countdown(180) + actions(64)
        # 1 个定时器：30fps chart tick
        # 0 个 worker：直接 subscribe data_source

    def set_channel(self, cid: int) -> None:
        """切换到指定 channel（单开语义：覆盖当前显示）。"""

    def _on_reading(self, reading: ChannelReading) -> None:
        """DataSource 推数据 → 追加到本地 5min ring → 标记 dirty。"""

    def _tick_chart(self) -> None:
        """30fps：读取 dirty 标志 → 重绘曲线 + 异常段标红。"""

    def _on_back(self): self.requested_back.emit()
    def _on_action(self, action: str): self.action_requested.emit(action, self._cid)
```

### 3.1 关键内部状态

| 字段 | 类型 | 用途 |
|---|---|---|
| `_cid` | `int` | 当前显示的 channel |
| `_ring` | `deque(maxlen=150)` | 5min × 2s = 150 帧（**不进 HomePage HB 共享，避免抢资源**）|
| `_dirty` | `bool` | 新数据待绘 |
| `_chart` | `pg.PlotWidget` | pyqtgraph 曲线 |
| `_curve` | `pg.PlotDataItem` | 主电流曲线 |
| `_zero_line` | `pg.InfiniteLine(pos=0, angle=0)` | 归零参考线（红虚线）|
| `_fill` | `pg.FillBetweenItem` | 异常段填充（红色半透明）|
| `_state` | `DetectionState` | 镜像 CellController 状态，决定是否启用异常检测 |
| `_closing` | `bool` | closeEvent gate（防 RuntimeError）|

### 3.2 30fps throttle + decimate

```python
self._tick_timer = QTimer(self)
self._tick_timer.setInterval(33)  # 30fps
self._tick_timer.timeout.connect(self._tick_chart)
# 60s 后 ring > 600 点 → decimate to 200（保留首尾点）
```

---

## 4. labels.py 新增 8 个常量

```python
# 详情页（v3.0）
DETAIL_TITLE_TEMPLATE = "详情  //  {cid}  ·  {state}"  # 复用 format_cid + state 文本
DETAIL_BACK_TEXT = "← 返回主页"
DETAIL_NO_CHANNEL_TEXT = "（请从主页双击 LED 打开详情）"

DETAIL_CHART_TITLE = "电流时序  //  CURRENT I-t"
DETAIL_CHART_X_LABEL = "时间 (s)"
DETAIL_CHART_Y_LABEL = "电流 (A)"

DETAIL_ZERO_LINE_LABEL = "归零阈值 0A"
DETAIL_ZERO_ANOMALY_TEMPLATE = "⚠ {cid} 电流归零异常"  # 复用 format_cid

DETAIL_ACTIONS_TITLE = "操作  //  ACTIONS"
DETAIL_ACTION_START = "▶ 开始"
DETAIL_ACTION_PAUSE = "⏸ 暂停"
DETAIL_ACTION_RESUME = "↻ 继续"
DETAIL_ACTION_STOP  = "■ 停止"
DETAIL_ACTION_LABELS = ("DETAIL_ACTION_START", "DETAIL_ACTION_PAUSE",
                        "DETAIL_ACTION_RESUME", "DETAIL_ACTION_STOP")
```

> 注：复用 `BUTTON_LABELS`（已有 start/pause/resume/stop）有命名冲突，需要重命名避免歧义。

---

## 5. main_3d.py 改动（最小侵入）

```python
class Rack3DView(QWidget):
    # 已有：_hover_label / _hover_timer / _tick_hover
    # 新增：
    led_double_clicked = pyqtSignal(int)  # 参数：cid

    def __init__(...):
        # 已有 eventFilter 监听 MouseButtonPress（pause 旋转）
        # 新增：MouseButtonDblClick → 计算 best_cid → emit
        ...
```

**复用** 已有 ray-pick 逻辑（_pick_led_cid）—— 已经能算 best_cid。
**新增** 在 eventFilter 加 1 个 case：`QEvent.MouseButtonDblClick`。

---

## 6. home_page.py 改动（最小侵入）

```python
class HomePage(QMainWindow):
    def __init__(...):
        ...
        # 已有：self._router.register("home", home_widget) × 4
        # 新增：
        self._detail = DetailPage(
            data_source=self._data_source,
            history=self._history,
            cell_controller=self._controller,
            parent=self,
        )
        self._router.register("detail", self._detail)
        # 已有：self._rack.hover_changed
        # 新增：
        self._rack.led_double_clicked.connect(self._open_detail)

    def _open_detail(self, cid: int):
        self._detail.set_channel(cid)
        self._router.navigate("detail")
        # 暂停 3D 旋转（避免后台空转）
        self._rack.set_auto_rotate(False)

    def _on_detail_back(self):
        self._router.navigate("home")
        self._rack.set_auto_rotate(True)  # 恢复
```

---

## 7. 风险与缓解

| 风险 | 等级 | 缓解 |
|---|---|---|
| pyqtgraph 5.15 + Qt 5.15 ABI 不兼容 | 中 | 已验证环境（pyqtgraph 0.14 + PyQt5 5.15.11 长期使用）|
| DataSource 2s 节奏下，30fps 重绘浪费 | 低 | dirty 标志：无新数据跳过重绘 |
| 双击 ray-pick 不准（点空白处也触发）| 中 | 仅当 best_cid ≠ None 时 emit |
| 多个 LED 一起开 detail | 低 | Q2 决定单开：`set_channel` 覆盖 |
| 详情页与电流检测页选区不一致 | 低 | 不共享 selection，详情页只看自己 _cid |
| chart 频繁 setData 导致闪烁 | 中 | 30fps throttle + decimate + FillBetweenItem 而非 LinearRegionItem |

---

## 8. 验证步骤（3.6）

```powershell
# 1) py_compile 4 个文件
& E:\MiniConda\envs\Aging\python.exe -m py_compile `
  d:\Aging\app\core\labels.py `
  d:\Aging\app\ui\pages\detail_page.py `
  d:\Aging\app\ui\main_3d.py `
  d:\Aging\app\ui\home_page.py

# 2) import smoke
& E:\MiniConda\envs\Aging\python.exe -c "
import Main
from app.ui.pages.detail_page import DetailPage
print('DetailPage import OK')
"

# 3) 启动应用
& E:\MiniConda\envs\Aging\python.exe d:\Aging\Main.py
#   - 等 5s
#   - 双击 3D 任意 LED
#   - 验证：路由切到 detail、曲线开始画、归零红线可见
#   - 点"返回主页" → 回到 home
```

---

## 9. 实施顺序

```
3.1 labels.py（+8 字符串）    ← 低风险，纯文本
        ↓
3.2 detail_page.py（新建 280 行）   ← 核心，需最长
        ↓
3.3 main_3d.py（+led_double_clicked signal + 双击 case）   ← 复用已有 ray-pick
        ↓
3.4 home_page.py（注册 + 接 signal）   ← 编排层
        ↓
3.5 性能（已含在 3.2）   ← throttle + decimate
        ↓
3.6 验证  ← py_compile + import + 启动
```

每完成一步立即 `py_compile` 兜底，避免一次性写 280 行调试。

---

*最后更新：2026-07-18 — Phase 3 实施计划 v1*
