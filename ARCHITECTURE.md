# 老化检测系统控制台 — 架构与二次开发指南（v3.0）

> 本文件是**唯一权威**的项目结构与开发规范文档。任何对目录结构、依赖、命名、流程的改动都需先更新本文，再改代码。

---

## 1. 项目概述

PyQt5 桌面应用，模拟/接收 72 通道（4 电流 + 4 温度）的实时数据并以**3D 机柜全屏 + 4 浮窗 + 5 路由页面**呈现。目标平台 Windows 10/11 + Python 3.10（Conda 环境 `Aging`）。

**核心特性**：
- **3D 主页**：72 LED 机柜全屏渲染，5 色状态可视化（offline/running/paused/alert/warning）
- **空闲 5s 自动旋转 + eventFilter 鼠标交互暂停**
- **4 浮窗**：右告警 / 左 LED 矩阵 / 右下 HUD 系统状态 / 复位按钮
- **5 路由页面**：主页 / 电流检测 / 视频检测 / 数据中心 / 系统设置
- **72 cell 业务状态机**（CellController）+ UI 状态映射（CellUIManager）
- **5min × 72 channels 历史缓冲**（HistoryBuffer），30s 周期聚合摘要
- **observability 层**：loguru + Qt signal bus + 通俗事件描述 + safe_call 装饰器 + 全局异常钩子
- **顶部 60px 工业风 nav bar**（active 发光条）

**启动**：
```powershell
& E:\MiniConda\envs\Aging\python.exe d:\Aging\Main.py
```

---

## 2. 目录结构

```
d:\Aging\
├── Main.py                          # 应用入口（仅 ~30 行，构造 HomePage）
├── environment.yml                  # Conda 依赖锁文件
├── ARCHITECTURE.md                  # 本文件
├── logs/                            # 运行时日志（loguru rotating）
│   └── app.log
├── .trae/                           # Trae IDE 工作区
│   └── documents/                   # 设计文档 / 路线图 / 审计
└── app/
    ├── core/                        # ──── Layer 0：基础常量（不依赖任何业务）
    │   ├── config.py                # 数值型常量：窗口/网格/阈值/相机
    │   ├── tokens.py                # DesignTokens：颜色/字体/尺寸 dataclass
    │   ├── labels.py                # 用户可见字符串唯一来源（含模板）
    │   └── formatting.py            # format_cid / format_hms / divmod3600
    │
    ├── data/                        # ──── Layer 1：数据契约与数据源
    │   ├── protocol.py              # DataSource Protocol + ChannelReading
    │   ├── demo_source.py           # DemoDataSource（v3 唯一数据源）
    │   └── history_buffer.py        # 5min 滑动窗口，按 cell 索引
    │
    ├── services/                    # ──── Layer 1.5：领域服务（无 UI 依赖）
    │   ├── cell_controller.py       # 72 cell 状态机（STOPPED/RUNNING/PAUSED）
    │   ├── cell_ui_manager.py       # 状态→5 色 LED 映射
    │   └── countdown.py             # 检测倒计时
    │
    ├── observability/               # ──── Layer 1.5：横切关注
    │   ├── logger.py                # loguru 配置 + Qt signal 桥接
    │   ├── log_signals.py           # log_message signal 单一总线
    │   ├── narrative.py             # 通俗事件描述 + format_cids
    │   ├── safe_call.py             # 异常隔离装饰器
    │   └── exception_hook.py        # 全局未捕获异常 → 状态栏
    │
    ├── styles/                      # ──── Layer 2：QSS 模板与拼接
    │   ├── templates.py             # 9 段 QSS f-string 模板
    │   └── stylesheet.py            # StylesheetBuilder.render()
    │
    ├── widgets/                     # ──── Layer 3：基础控件
    │   ├── data_cell.py             # 9×8 grid cell
    │   └── cell_grid.py             # 72 cell 网格 + hover/选择/批量工具
    │
    └── ui/                          # ──── Layer 4：页面与编排
        ├── home_page.py             # HomePage（3D 主页编排）
        ├── main_3d.py               # Rack3DView + 72 LED + 5 色辉光呼吸
        ├── nav_bar.py               # TopNavBar（60px 工业风）
        ├── floaters.py              # 4 浮窗：alerts/LED-strip/HUD/reset
        ├── router.py                # PageRouter（QStackedWidget 薄包装）
        ├── qss_utils.py             # refresh_qss（dynamic property 重渲染）
        ├── dialogs.py               # 通用确认对话框
        └── pages/
            ├── current_page.py      # 电流检测（9×8 + 选区 + 批量工具）✅
            ├── video_page.py        # 视频检测（占位）⏳
            ├── data_page.py         # 数据中心（占位）⏳
            ├── settings_page.py     # 系统设置（占位）⏳
            └── detail_page.py       # 单 channel 详情（双击 3D LED 进入）✅  v3.0 Phase 3
```

---

## 3. 依赖方向（强约束）

```
core  ←  data
       ←  services
       ←  observability
       ←  styles
       ←  widgets
       ←  ui
```

- `core` 不依赖任何其他包（**唯一**可被所有层引用的最底层）
- `data` / `services` / `observability` 仅依赖 `core`（可被 UI 引用，但反之不行）
- `styles` 仅依赖 `core`（含 tokens，不依赖 widgets/ui）
- `widgets` 依赖 `core` + `data`（不含 services：保持解耦）
- `ui` 依赖所有下层（允许组合 `services` + `widgets` + `floaters`）
- 任何**反向**依赖 = bug，必须立即修复

---

## 4. 各文件职责

| 文件 | 职责 | 关键导出 |
|---|---|---|
| [Main.py](file:///d:/Aging/Main.py) | 应用入口：QApplication + QSS + HomePage | — |
| [app/core/config.py](file:///d:/Aging/app/core/config.py) | 数值型配置（窗口/网格/阈值/相机/刷新） | `WINDOW_SIZE`, `GRID_ROWS`, `ANOMALY_CURRENT_THRESHOLD`, `CAMERA_*` |
| [app/core/tokens.py](file:///d:/Aging/app/core/tokens.py) | DesignTokens（4 个 frozen dataclass） | `Colors`, `Fonts`, `FontSizes`, `Sizing`, `DEFAULT_TOKENS` |
| [app/core/labels.py](file:///d:/Aging/app/core/labels.py) | 用户可见字符串（12+ 模板常量） | `WINDOW_TITLE`, `NAV_ITEMS`, `STATUS_*_TEXT` |
| [app/core/formatting.py](file:///d:/Aging/app/core/formatting.py) | 格式化集中点 | `format_cid`（全工程统一入口）, `format_hms`, `divmod3600` |
| [app/data/protocol.py](file:///d:/Aging/app/data/protocol.py) | 数据契约 | `ChannelReading`, `DataSource` (Protocol), `Subscriber` |
| [app/data/demo_source.py](file:///d:/Aging/app/data/demo_source.py) | 72 通道 mock + 偶发异常 | `DemoDataSource`（v3 唯一数据源） |
| [app/data/history_buffer.py](file:///d:/Aging/app/data/history_buffer.py) | 5min 滑动窗口 | `HistoryBuffer.snapshot(cid, n)` |
| [app/services/cell_controller.py](file:///d:/Aging/app/services/cell_controller.py) | 72 cell FSM 真理源 | `DetectionState`, `CellController.start/pause/resume/stop()` |
| [app/services/cell_ui_manager.py](file:///d:/Aging/app/services/cell_ui_manager.py) | FSM 状态 → 5 色 LED 映射 | `CellUIManager` |
| [app/services/countdown.py](file:///d:/Aging/app/services/countdown.py) | 检测倒计时（按 cell） | `CountdownService.start(cid, dur_s)` |
| [app/observability/logger.py](file:///d:/Aging/app/observability/logger.py) | loguru + Qt signal | `get_logger`, `DEFAULT_LOG_FMT` |
| [app/observability/log_signals.py](file:///d:/Aging/app/observability/log_signals.py) | 单一 log bus | `LogSignals.log_message` |
| [app/observability/narrative.py](file:///d:/Aging/app/observability/narrative.py) | 通俗事件 + format_cids | `narrative.event()`, `format_cid`, `format_cids` |
| [app/observability/safe_call.py](file:///d:/Aging/app/observability/safe_call.py) | 异常隔离装饰器 | `@safe_call(context="...")` |
| [app/observability/exception_hook.py](file:///d:/Aging/app/observability/exception_hook.py) | 全局未捕获 → 状态栏 | `install_exception_hook()` |
| [app/styles/templates.py](file:///d:/Aging/app/styles/templates.py) | 9 段 QSS f-string | `main_window`, `title_bar`, `data_cell`, `header_bar`, `data_grid`, `data_point`, `button`, `status_bar`, `right_panel` |
| [app/styles/stylesheet.py](file:///d:/Aging/app/styles/stylesheet.py) | 模板拼接器 | `build_stylesheet(tokens)` |
| [app/widgets/data_cell.py](file:///d:/Aging/app/widgets/data_cell.py) | 9×8 单元格 | `DataCell` |
| [app/widgets/cell_grid.py](file:///d:/Aging/app/widgets/cell_grid.py) | 72 cell 网格 | `CellGrid` |
| [app/ui/home_page.py](file:///d:/Aging/app/ui/home_page.py) | 3D 主页编排 | `HomePage` |
| [app/ui/main_3d.py](file:///d:/Aging/app/ui/main_3d.py) | 3D 机柜 + LED | `Rack3DView`, `LEDState`, `CAMERA_*` |
| [app/ui/nav_bar.py](file:///d:/Aging/app/ui/nav_bar.py) | 顶部导航 | `TopNavBar` |
| [app/ui/floaters.py](file:///d:/Aging/app/ui/floaters.py) | 4 浮窗 | `RightAlertsFloater`, `RightLEDStripFloater`, `BottomRightHUDFloater`, `ResetViewButton` |
| [app/ui/router.py](file:///d:/Aging/app/ui/router.py) | 页面路由 | `PageRouter.register/navigate/current_key` |
| [app/ui/qss_utils.py](file:///d:/Aging/app/ui/qss_utils.py) | QSS 工具 | `refresh_qss(widget)` |
| [app/ui/dialogs.py](file:///d:/Aging/app/ui/dialogs.py) | 通用对话框 | `confirm_stop_running()` |
| [app/ui/pages/current_page.py](file:///d:/Aging/app/ui/pages/current_page.py) | 电流检测 | `CurrentDetectionPage` |
| [app/ui/pages/detail_page.py](file:///d:/Aging/app/ui/pages/detail_page.py) | 单 channel 详情（双击 3D LED 进入）| `DetailPage` |
| [app/ui/pages/video_page.py](file:///d:/Aging/app/ui/pages/video_page.py) | 视频检测（占位） | `VideoDetectionPage` |
| [app/ui/pages/data_page.py](file:///d:/Aging/app/ui/pages/data_page.py) | 数据中心（占位） | `DataCenterPage` |
| [app/ui/pages/settings_page.py](file:///d:/Aging/app/ui/pages/settings_page.py) | 系统设置（占位） | `SettingsPage` |

---

## 5. 硬编码禁令

下列内容**严禁**出现在 `app/ui/` 与 `app/widgets/`（除文档/注释/log）：

| 类型 | 必须从哪取 |
|---|---|
| 颜色 hex（`#xxxxxx`） | `DEFAULT_TOKENS.colors.*` |
| 字号（`\d+pt`） | `DEFAULT_TOKENS.font_sizes.*` |
| 字体族字符串 | `DEFAULT_TOKENS.fonts.*` |
| 尺寸数字（`setMinimumSize` / `setFixedHeight`） | `DEFAULT_TOKENS.sizing.*` |
| 间距数字（`setSpacing` / `setContentsMargins`，>1） | `DEFAULT_TOKENS.sizing.*` |
| 圆角数字（`border-radius`） | `DEFAULT_TOKENS.sizing.*` |
| 边框宽度（`border: Npx`） | `DEFAULT_TOKENS.sizing.*` |
| 用户可见中英文字符串 | `app.core.labels.*` |
| 状态文字（"● ON" / "● ALERT" / "○ OFF"） | `labels.STATUS_*_TEXT` |
| `CH-NN` 通道号 | `app.core.formatting.format_cid(N)` |
| 数据生成（`random.uniform` 等） | `app.data.protocol.DataSource` 实现 |

**唯一例外**：
- `setSpacing(0)` / `setContentsMargins(0,0,0,0)`（0 是结构系数）
- docstring 与 ASCII 框图
- log 输出（loguru 自由文本）

---

## 6. 二次开发指南

### 6.1 新增可见文本

1. 打开 [app/core/labels.py](file:///d:/Aging/app/core/labels.py)
2. 添加常量（模板用 `.format(**)` 注入参数）：
   ```python
   NEW_LABEL = "新增文本"
   NEW_TEMPLATE = "操作 {action} 完成于 {time}"
   ```
3. 在 `app/ui/` / `app/widgets/` 中 `from app.core import labels`，然后 `labels.NEW_LABEL`
4. **不要**在 widget 中写中英文字符串字面量

### 6.2 新增通道号格式

1. 打开 [app/core/formatting.py](file:///d:/Aging/app/core/formatting.py)
2. 修改 `format_cid()` 单一函数，全工程同步生效

### 6.3 调整颜色 / 字号 / 尺寸

1. 打开 [app/core/tokens.py](file:///d:/Aging/app/core/tokens.py)
2. 修改对应 `Colors` / `FontSizes` / `Sizing` 字段默认值
3. 全应用同步生效（QSS 模板 f-string 自动重渲染）

### 6.4 切换主题（如增加 Light 主题）

1. 在 `tokens.py` 增加 `LightColors(frozen=True)`，填浅色系值
2. 构造 `LightTokens = DesignTokens(colors=LightColors(), ...)`
3. `app.setStyleSheet(build_stylesheet(LightTokens))`
4. 所有 widget 无需任何改动

### 6.5 切换数据源（如增加文件回放 / 串口）

1. 在 [app/data/](file:///d:/Aging/app/data/) 新建 `file_source.py` / `serial_source.py`
2. 实现 [DataSource Protocol](file:///d:/Aging/app/data/protocol.py)：`start()` / `stop()` / `subscribe(callback)`
3. 在 [app/ui/home_page.py](file:///d:/Aging/app/ui/home_page.py) 实例化时替换 `DemoDataSource`
4. widget / services 无需任何改动

### 6.6 新增页面（左侧新增 Tabs）

1. 在 [app/ui/pages/](file:///d:/Aging/app/ui/pages/) 新建 `<name>_page.py`
2. 继承 `QWidget`，实现 `__init__(parent, ...)`，暴露 `name: str`（与 `labels.NAV_ITEMS` 对应）
3. 在 [app/ui/home_page.py](file:///d:/Aging/app/ui/home_page.py) 中 `self.router.register("name", widget_instance)`
4. 在 [app/core/labels.py](file:///d:/Aging/app/core/labels.py) `NAV_ITEMS` 添加新条目
5. nav bar 自动出现新按钮，点击自动路由

### 6.7 新增浮窗

1. 在 [app/ui/floaters.py](file:///d:/Aging/app/ui/floaters.py) 追加新类，继承 `QWidget`
2. 在 [app/ui/home_page.py](file:///d:/Aging/app/ui/home_page.py) `__init__` 实例化 + `self._float_layer.addWidget(...)`
3. 坐标与大小从 `DEFAULT_TOKENS.sizing.*` 取

### 6.8 新增 cell 业务动作

1. 在 [app/services/cell_controller.py](file:///d:/Aging/app/services/cell_controller.py) `_STATE_TRANSITIONS` 加新 action
2. 在 `CellController` 加新 `def action_<name>(cid)` 方法
3. 在 [app/services/cell_ui_manager.py](file:///d:/Aging/app/services/cell_ui_manager.py) 加新视觉映射
4. UI 层只需调 `controller.action_<name>(cid)`，状态变化通过 signal 自动广播

---

## 7. 关键设计原则（不可破坏）

1. **`DesignTokens` 必须 `frozen=True`** — 运行时不可变
2. **`format_cid` 是通道号格式唯一入口** — 禁止 `f"CH-{n:02d}"`
3. **`DataSource` 必须用 `typing.Protocol`** — duck-type 即可，不强制继承
4. **QSS 模板统一在 `StylesheetBuilder` 合并** — widget **不**在 `__init__` 调用 `setStyleSheet('''...''')`
5. **dynamic property 修改后必须 `refresh_qss(widget)`** — QSS selector 才生效
6. **所有 UI 可见文本走 `app/core/labels.py`** — 模板用 `.format(**)` 注入参数
7. **业务状态与 UI 状态解耦** — `CellController` 不知道 `LEDState`，靠 `CellUIManager` 映射
8. **包级 `__init__.py` 保持空**（除 `app.styles` 暴露 `build_stylesheet`）
9. **每阶段结束必须 `python Main.py` 可启动** — 不留 broken commit
10. **依赖方向严格单向** — 见第 3 节

---

## 8. 依赖管理

- Python 环境：`E:\MiniConda\envs\Aging`（Miniconda, Python 3.10.20）
- 锁文件：[environment.yml](file:///d:/Aging/environment.yml)
- 镜像源：清华 TUNA（conda + pip）
- 关键依赖：
  - PyQt5 5.15.11
  - pyqtgraph 0.14.0
  - opencv-python 4.10.0.84（**不**升级到 4.11+，避免 ffmpeg DLL 冲突）
  - pillow 11.0.0（**不**升级到 12.x，torchvision 0.23 兼容）
  - openvino 2024.6.0（**不**使用 2026.2.1，runtime 报错）
  - torch 2.7+ / cu128（支持 RTX 5060 Ti sm_120 / Blackwell）

**复现命令**：
```powershell
conda env create -f d:\Aging\environment.yml
conda activate Aging
```

---

## 9. 启动 & 验证

```powershell
# 启动
& E:\MiniConda\envs\Aging\python.exe d:\Aging\Main.py

# 编译检查（全部 v3 模块）
cd d:\Aging
& E:\MiniConda\envs\Aging\python.exe -m py_compile Main.py `
  app/core/*.py app/data/*.py app/services/*.py app/observability/*.py `
  app/styles/*.py app/widgets/*.py app/ui/*.py app/ui/pages/*.py

# Import smoke test
& E:\MiniConda\envs\Aging\python.exe -c "import Main; print('OK')"

# 硬编码自检（见第 5 节）
rg "#[0-9a-fA-F]{6}" d:\Aging\app\widgets d:\Aging\app\ui
rg "CH-\{.*02d\}" d:\Aging\app\ui d:\Aging\app\widgets d:\Aging\app\observability
rg "random\." d:\Aging\app\widgets
```

---

## 10. 备份

- 旧版备份：`d:\Aging_backup_20260707\`（v1 单层结构）
- 暂无 git 仓库（**强烈建议引入**，参考 [github.com/.../aging](https://github.com/...)）

---

## 11. 变更流程

任何对架构的改动需遵循：

1. **先改本文档**（更新目录树 + 文件职责 + 二次开发步骤）
2. 再改代码
3. 跑第 9 节的启动 + 编译 + 硬编码自检
4. 提交（若启用 VCS）：commit message 引用本文件对应章节

---

*最后更新：2026-07-18 — v3.0 主页 + 4 浮窗 + 5 路由页架构落地；归档 v2 死代码 9 个文件*
