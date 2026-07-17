# Aging PyQt5 项目治理重构方案

## Context

UI 设计已收敛为可运行状态，但代码组织是"快速试错"留下的临时形态：

- 6 个 .py 平铺根目录，零包结构
- [sci_fi_style.py](file:///d:/Aging/sci_fi_style.py) 230 行 QSS 中**所有颜色/字号/字体都是裸 hex/数字字符串**（`#00bfff` 重复 10+ 次）
- [config.py](file:///d:/Aging/config.py) 定义了 `COLOR_NEON_CYAN` / `FONT_SIZE_MD` / `FONT_MONO` 等常量，但**没有任何样式代码引用它们**——两套值在两处独立维护，已形成事实分歧
- [data_cell.py](file:///d:/Aging/data_cell.py) 直接 `random.uniform` 模拟数据 + 异常判定，**UI 与数据耦合**
- 状态栏 / footer / accent 文字、widget 尺寸/边距数字散落 6 个文件

**目标**：建一个可扩展、token 化、UI/数据解耦的经典分层架构，4 阶段执行，每阶段用户确认后再进下一阶段。

**用户决策（已确认）**：
1. 目录结构：**经典分层**（core / data / ui / widgets / styles / resources）
2. 样式管理：**Token 字典 + 模板渲染**（dataclass 存 token，f-string 渲染 QSS）
3. 数据层：**DataSource 协议 + Mock 实现**（typing.Protocol，widget 只订阅）
4. 执行节奏：**分 4 阶段，每阶段用户确认后进入下一阶段**

**约束**：
- 不引入新依赖（pydantic、pyyaml 等）
- 每阶段结束应用必须可运行（`python Main.py`）
- 备份已存在 `d:\Aging_backup_20260707\`，本轮不需再次备份

## 目标目录结构（终态）

```
d:\Aging\
├── Main.py                          # 入口（仅 import app.ui.main_window）
├── environment.yml
├── README.md
└── app/
    ├── __init__.py
    ├── core/
    │   ├── __init__.py
    │   ├── config.py                # 窗口尺寸/刷新间隔/网格规格（迁自原 config.py）
    │   ├── tokens.py                # DesignTokens frozen dataclass + DEFAULT_TOKENS
    │   └── labels.py                # status/footer/accent 等所有 UI 文本常量
    ├── data/
    │   ├── __init__.py
    │   ├── protocol.py              # DataSource Protocol（typing.Protocol）
    │   └── mock_source.py           # MockDataSource（保留 random.uniform 行为）
    ├── ui/
    │   ├── __init__.py
    │   └── main_window.py           # 主窗口（9x8 网格 + 状态栏 + footer）
    ├── widgets/
    │   ├── __init__.py
    │   ├── data_cell.py             # 数据单元（订阅 DataSource，不再自己造数据）
    │   └── control_button.py        # 按钮
    ├── styles/
    │   ├── __init__.py              # 暴露 build_stylesheet()
    │   ├── templates.py             # QSS f-string 模板（按 widget 分块）
    │   └── stylesheet.py            # StylesheetLoader：合并 token 与模板，输出 QSS
    └── resources/
        └── __init__.py              # 资产占位
```

## 4 阶段执行

### 阶段 1：骨架迁移（零逻辑改动）

| 项 | 说明 |
|---|---|
| 目标 | 建分层目录，6 文件平移，import 改完即可启动 |
| 前置 | 无 |
| 新建 | 7 个空 `__init__.py`（app/ + 6 个子包） |
| 修改 | [Main.py](file:///d:/Aging/Main.py) 改 `from app.ui.main_window import MainWindow`；[main_window.py](file:///d:/Aging/main_window.py) / [data_cell.py](file:///d:/Aging/data_cell.py) / [control_button.py](file:///d:/Aging/control_button.py) / [sci_fi_style.py](file:///d:/Aging/sci_fi_style.py) / [config.py](file:///d:/Aging/config.py) 改 import 指向 `app.*` |
| 验收 | `python d:\Aging\Main.py` 启动，9x8 网格、状态栏、刷新与现版本**像素级一致** |
| 风险 | import 链遗漏导致启动失败。**缓解**：阶段 1 改完跑一次完整启动流程 |
| 不做 | 不动样式、不动数据生成、不重构函数体 |

### 阶段 2：Token 与样式解耦

| 项 | 说明 |
|---|---|
| 目标 | 消除 [sci_fi_style.py](file:///d:/Aging/sci_fi_style.py) 中所有裸 hex / 裸数字字号 / 裸字体名，统一由 `DesignTokens` 注入 |
| 前置 | 阶段 1 的 `app.core` / `app.styles` 空包 |
| 新建 | [d:\Aging\app\core\tokens.py](file:///d:/Aging/app/core/tokens.py)（frozen dataclass，colors / fonts / sizes / spacing / radius / borders + DEFAULT_TOKENS）；[d:\Aging\app\styles\templates.py](file:///d:/Aging/app/styles/templates.py)（按 QWidget / QPushButton / QStatusBar 分块的 f-string 模板）；[d:\Aging\app\styles\stylesheet.py](file:///d:/Aging/app/styles/stylesheet.py)（`StylesheetLoader.render(tokens)` 合并输出） |
| 修改 | [Main.py](file:///d:/Aging/Main.py) `app.setStyleSheet(build_stylesheet(DEFAULT_TOKENS))`；[d:\Aging\app\widgets\data_cell.py](file:///d:/Aging/app/widgets/data_cell.py) / [control_button.py](file:///d:/Aging/app/widgets/control_button.py) 中 `setMinimumSize` / `setMinimumHeight` 内联值全替换为 `tokens.sizes.xxx`；[sci_fi_style.py](file:///d:/Aging/sci_fi_style.py) **删除**（已被 templates 替代） |
| 验收 | `grep -r "#[0-9a-fA-F]\{6\}" d:\Aging\app\styles\ d:\Aging\app\widgets\` 命中数在 widgets 中为 0；启动视觉与之前完全一致（截图对比） |
| 风险 | 某处漏改的硬编码导致回退。**缓解**：阶段 2 开始前 `Grep "#00bfff"` 建立硬编码清单逐条消项 |
| 不做 | 不改数据生成、不改布局结构、不动状态栏文案（留到阶段 4） |

### 阶段 3：DataSource 解耦

| 项 | 说明 |
|---|---|
| 目标 | `data_cell.py` 不再调用 `random.uniform`；通过 `DataSource` 协议取数，Mock 复现原行为 |
| 前置 | 阶段 1-2 |
| 新建 | [d:\Aging\app\data\protocol.py](file:///d:/Aging/app/data/protocol.py)（`DataSource(Protocol)` 定义 `start/stop/subscribe` + `ChannelReading` NamedTuple）；[d:\Aging\app\data\mock_source.py](file:///d:/Aging/app/data/mock_source.py)（**逐字复刻**原 `data_cell.py` 的 random 范围与异常判定，5% 概率异常） |
| 修改 | [d:\Aging\app\widgets\data_cell.py](file:///d:/Aging/app/widgets/data_cell.py) 构造函数接受 `DataSource` + `channel_id`；删除 `import random`；`update_data(reading)` 仅渲染数据 + 判定 alert；[d:\Aging\app\ui\main_window.py](file:///d:/Aging/app/ui/main_window.py) 实例化 `MockDataSource()`，订阅事件并派发到 72 个 cell |
| 验收 | `grep -nE 'random\.' d:\Aging\app\widgets\` 无命中；72 通道数字持续刷新、异常态仍按原概率闪现、刷新间隔 2000ms 不变 |
| 风险 | Mock 数值分布漂移。**缓解**：把原 `random.uniform` 的 seed 范围/异常阈值**逐行复制**到 Mock，保留 `random` 调用顺序与频次 |
| 不做 | 不写 FileDataSource / SerialDataSource；不引入多线程；不改变 UI 布局 |

### 阶段 4：文本集中与收尾

| 项 | 说明 |
|---|---|
| 目标 | 状态栏 `● SYSTEM ONLINE ...`、footer、`[ OK ]` 等所有可见字符串统一走 `core/labels.py` |
| 前置 | 阶段 2 已建立 `core/labels.py` 占位，阶段 4 填实 |
| 新建 | （仅扩充 [d:\Aging\app\core\labels.py](file:///d:/Aging/app/core/labels.py)）：`WINDOW_TITLE`、`STATUS_BAR_TEMPLATE`、`FOOTER_TEMPLATE`、`ACCENT_OK_BADGE`、`STATUS_ONLINE_TEXT/ALERT/OFFLINE`、`BUTTON_GLYPHS/BUTTON_LABELS` |
| 修改 | [d:\Aging\app\ui\main_window.py](file:///d:/Aging/app/ui/main_window.py) 状态栏 / footer f-string 改 `labels.STATUS_TEMPLATE.format(refresh_ms=...)`；[d:\Aging\app\widgets\data_cell.py](file:///d:/Aging/app/widgets/data_cell.py) 状态文字改 `labels.STATUS_*_TEXT` |
| 验收 | `grep -nE '"● SYSTEM ONLINE"|"\[ OK \]"|"● ON"|"● ALERT"' d:\Aging\app\ui\ d:\Aging\app\widgets\` 全部无命中（这些字符串只能存在于 `app/core/labels.py`） |
| 风险 | 遗漏某条字符串。**缓解**：阶段 4 开始前全量 Grep 可见文本建清单 |
| 不做 | 不引入 i18n / gettext；不切换语言；不重构布局参数 |

## 设计原则

1. **`DesignTokens` 必须 `frozen=True`**，运行时不可变；所有 widget 通过参数注入，禁止 mutate
2. **数字字面量禁出现于 `app/ui` 与 `app/widgets`**，除 `0` / `1` 系数外；尺寸/margin/spacing 必须命名 token 或常量
3. **`DataSource` 用 `typing.Protocol`**，不强制继承；`MockDataSource` 与未来 `FileDataSource` 平级
4. **QSS 模板统一在 `StylesheetLoader` 中合并**，各 widget 不再 `setStyleSheet('''...''')`，仅在 `__init__` 调用对象名
5. **所有 UI 可见文本走 `app/core/labels.py`**，常量集中
6. **包级 `__init__.py` 保持空**（除 `app.styles` 暴露 `build_stylesheet`），避免隐式副作用
7. **每阶段结束必须 `python Main.py` 可启动**；阶段间用 `git commit` 留可回滚锚点（若启用 VCS）

## 关键复用点（参考现有代码）

- `_restyle(widget)` 工具函数（[data_cell.py:29-33](file:///d:/Aging/data_cell.py#L29-L33)）→ 阶段 4 迁到 `app/core/utils.py`
- `setAttribute(Qt.WA_StyledBackground, True)` 模式（[data_cell.py:42](file:///d:/Aging/data_cell.py#L42)）→ 阶段 3 提取为 helper
- `setProperty("alert", True) + _restyle()` 状态切换模式 → 阶段 3 保留并文档化
- 现有 [sci_fi_style.py:11-217](file:///d:/Aging/sci_fi_style.py#L11-L217) 中每个 QSS 块 → 阶段 2 直接转 f-string 模板

## 整体验证

每阶段结束后执行：
```powershell
cd d:\Aging
& E:\MiniConda\envs\Aging\python.exe -m py_compile Main.py main_window.py data_cell.py control_button.py config.py sci_fi_style.py
& E:\MiniConda\envs\Aging\python.exe d:\Aging\Main.py
```
目视检查：9x8 网格仍正常显示，4 电流 + 4 温度按 2 秒节奏刷新，按钮点击正常，状态栏正常。

阶段 2 结束时额外加一次截图回归：渲染 2560x1440 截图，与阶段 0 截图人工对比（应当像素级一致）。
