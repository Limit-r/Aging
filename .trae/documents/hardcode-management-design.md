# 硬编码集中治理设计方案（v1 · 三件套 + 验证器）

> **用途**：本文件是「建立 config 硬编码管理系统」的**完整设计文档**，配套 `phase-3-implementation-guide.md` 风格的"做什么/为什么"
> **版本**：v1  ·  2026-07-18  ·  待审阅
> **关系**：本设计 = **WHAT + WHY**（系统边界 / 验证机制 / 4 块清理 / 风险），后续写 **HOW**（具体敲哪行代码）时另开 `hardcode-management-guide.md`
> **基线**：[project-restructure-4-phases.md](file:///d:/Aging/.trae/documents/project-restructure-4-phases.md) §阶段 2-4 + [code-redundancy-audit-2026-07-16.md](file:///d:/Aging/.trae/documents/code-redundancy-audit-2026-07-16.md) §3 + 当前 templates/nav_bar/floaters 实际硬编码扫描结果

---

## 0. 文档约定

- **PowerShell 命令**在 `E:\MiniConda\envs\Aging\python.exe` 环境运行
- **工作目录**始终是 `d:\Aging`（不切换）
- **`py_compile` 失败立即停**，不继续往下
- **每阶段结束必须 `git commit`** 留可回滚锚点
- **每阶段用户审阅通过**才能进入下一阶段（用户硬性要求）

---

## 1. 现状审计（2026-07-18 实测）

### 1.1 硬编码泄漏地图

| 类别 | 文件 | 硬编码形态 | 数量 | 严重度 |
|------|------|------------|------|--------|
| **A 类（QSS 模板内）** | [app/styles/templates.py:42,66,93,111,160,196,284,287,425,440,460-480,546,550](file:///d:/Aging/app/styles/templates.py) | `rgba(R, G, B, A)` 字面量 | 14+ 处 | 🔴 高 |
| **A 类（QSS 模板内）** | [app/styles/templates.py:441-442,693,698](file:///d:/Aging/app/styles/templates.py) | 裸 hex `#ffd0d8` / `#ff5a78` / `#ffd166` / `#ff7090` | 4 处 | 🟡 中 |
| **B 类（UI 内联）** | [app/ui/nav_bar.py:52,65,96-119](file:///d:/Aging/app/ui/nav_bar.py) | 内联 QSS + rgba | 9 处 | 🟡 中 |
| **B 类（UI 内联）** | [app/ui/floaters.py:38,90-101,312-322](file:///d:/Aging/app/ui/floaters.py) | 内联 QSS + rgba | 9 处 | 🟡 中 |
| **C 类（数字字面量）** | [app/ui/main_3d.py](file:///d:/Aging/app/ui/main_3d.py) / [app/ui/home_page.py](file:///d:/Aging/app/ui/home_page.py) / [app/ui/pages/detail_page.py](file:///d:/Aging/app/ui/pages/detail_page.py) | `setMinimumSize(56)` / `setFixedHeight(64)` 等内联数字 | ~20+ 处 | 🟢 低 |
| **D 类（文本分散）** | [home_diff.txt](file:///d:/Aging/home_diff.txt) / [show.txt](file:///d:/Aging/show.txt) / [Main.py](file:///d:/Aging/Main.py) | `"● SYSTEM ONLINE"` / `"启动"` 等 | 3+ 处 | 🟡 中 |

### 1.2 同色多 alpha 重复模式

```text
# 0,191,255（cyan）→ 4 个不同 alpha 重复
templates.py:42   rgba(0, 191, 255, 40)   # cyan@40%
templates.py:66   rgba(0, 191, 255, 50)   # cyan@50%
nav_bar.py:52     rgba(0, 191, 255, 60)   # cyan@60%
nav_bar.py:96     rgba(0, 191, 255, 25)   # cyan@25%

# 74,217,255（淡 cyan）→ 6 个不同 alpha 重复
templates.py:460-464  rgba(74, 217, 255, 0/80/80/0)
templates.py:476-480  rgba(74, 217, 255, 0/140/140/0)
templates.py:546      rgba(74, 217, 255, 60)
```

**结论**：当前 `tokens.py` 的 `Colors` 按"颜色"维度组织，但实际使用是"颜色+alpha"组合维度——色板形似而神不似。

### 1.3 现有 token 体系（保留但定位调整）

| 模块 | 现状 | 调整定位 |
|------|------|----------|
| [app/core/tokens.py](file:///d:/Aging/app/core/tokens.py) | 4 大类 frozen dataclass（Colors/Fonts/FontSizes/Sizing） | 保留为**视觉常量**的单一来源 |
| [app/core/config.py](file:///d:/Aging/app/core/config.py) | 数值/阈值常量（GRID_ROWS/REFRESH_MS/LOG_ERROR_BADGE_MAX 等） | 保留为**业务常量**的单一来源 |
| [app/core/labels.py](file:///d:/Aging/app/core/labels.py) | 字符串常量（WINDOW_TITLE/STATUS_*_TEXT/MAIN_BUTTON_LABELS 等） | 保留为**文本常量**的单一来源 |
| [app/styles/templates.py](file:///d:/Aging/app/styles/templates.py) | QSS 模板（f-string + token） | 保留为**QSS 入口** |
| **（新增）** | — | **config_registry.py**：注册表 + 启动期硬编码扫描验证器 |

---

## 2. 三件套边界（核心设计）

### 2.1 分层模型

```text
┌────────────────────────────────────────────────────────────┐
│  config_registry.py（新增 · 验证器 + 总表）                  │
│  - 启动时扫描全工程裸值，CRITICAL log 报告                    │
│  - 维护"应该出现在哪里"白名单                                │
│  - 不持有任何视觉/业务/文本常量                              │
└────────────────────────────────────────────────────────────┘
                              ↓ 验证
        ┌─────────────────────┼─────────────────────┐
        ↓                     ↓                     ↓
┌──────────────┐     ┌──────────────┐      ┌──────────────┐
│  tokens.py   │     │  config.py   │      │  labels.py   │
│  视觉常量     │     │  业务常量     │      │  文本常量     │
│  Colors      │     │  GRID_ROWS   │      │  WINDOW_TITLE│
│  Fonts       │     │  REFRESH_MS  │      │  STATUS_*    │
│  FontSizes   │     │  THRESHOLDS  │      │  BUTTON_*    │
│  Sizing      │     │  DURATIONS   │      │  CHART_*     │
└──────────────┘     └──────────────┘      └──────────────┘
        ↓                     ↓                     ↓
   注入 templates.py      注入 services/data    注入 ui/widgets
```

### 2.2 职责清单

| 文件 | 职责 | 持有 | **不**持有 |
|------|------|------|-----------|
| **tokens.py** | 视觉常量 | Colors / Fonts / FontSizes / Sizing（frozen dataclass）+ `rgba()` 工具 + `DEFAULT_TOKENS` | 任何业务数字、任何文本、任何路径 |
| **config.py** | 业务常量 | 网格规格 / 刷新间隔 / 检测时长 / 日志阈值 / 路径 / 端口 / 协议常量 | 任何颜色、任何文本（除非是协议字段名） |
| **labels.py** | 文本常量 | 窗口标题 / 状态栏 / 按钮 / 图表标签 / 详情页文案 | 任何颜色、任何业务数字、任何路径 |
| **config_registry.py**（新） | 治理 + 验证 | 硬编码白名单 / 黑名单 / 扫描正则 / 报告函数 | **不持有任何常量**（只是引用三方套件来验证） |

### 2.3 关键决策

1. **三件套零交叉**：颜色只能进 tokens，数字只能进 config，文本只能进 labels。**没有例外**。
2. **templates.py 是 QSS 唯一入口**：所有 widget 引用 `app.styles.build_stylesheet()` 或 `app.styles.get_template("xxx")`，**禁止** widget 内部 `setStyleSheet("...")`。
3. **ConfigRegistry 不持有常量，只验证**：避免变成"第四件套"造成架构漂移。
4. **inline QSS 零容忍**：[floaters.py](file:///d:/Aging/app/ui/floaters.py) / [nav_bar.py](file:///d:/Aging/app/ui/nav_bar.py) 中的 `setStyleSheet("border: 1px solid ...")` 必须迁到 templates.py。
5. **同色多 alpha 用 `rgba()` 工具**：`tokens.rgba(c.BORDER_PRIMARY, 50)` 替代 `rgba(0, 191, 255, 50)`。

### 2.4 边界争议仲裁规则

| 争议场景 | 归属 | 理由 |
|----------|------|------|
| LED 颜色 (R,G,B,A) tuple | **tokens** | 视觉常量，给 OpenGL 用 |
| 网格行数 9 / 8 | **config** | 业务规格 |
| 电流阈值 0.1A | **config** | 业务阈值 |
| 倒计时巨字 56pt | **tokens (FontSizes.COUNTDOWN_BIG)** | 视觉常量 |
| 倒计时总时长 600s | **config** | 业务时长 |
| `"开始检测"` | **labels** | 用户可见文本 |
| `"● SYSTEM ONLINE"` | **labels** | 用户可见状态文本 |
| `"app.ui.home_page"` | **config** | logger 命名空间（业务路径） |
| `"rgba(0, 191, 255, 50)"` | **tokens (BORDER_PRIMARY + rgba 工具)** | 视觉常量 |
| QSS 字符串 | **templates.py**（不允许散落 widget） | 视觉规则 |

---

## 3. 注册表验证器（核心机制）

### 3.1 目标

启动时（configure_logging 之后、QApplication 启动之前）自动扫描全工程，**发现并报告**任何违反三件套边界的硬编码。报告级别：

- 🔴 **CRITICAL** — 颜色字面量出现在非 tokens/templates 路径
- 🟡 **WARNING** — 数字字面量（除 0/1 系数）出现在 ui/widgets
- 🟢 **INFO** — 文本字面量出现在 ui/widgets（不阻断，仅提示）

### 3.2 接口设计

```python
# app/core/config_registry.py
"""硬编码集中治理 · 验证器 + 总表。

启动期调用 `scan_and_report()`：
- 扫描 app/ 全工程
- 匹配硬编码正则
- 按白名单豁免
- 按规则分级报告
- 退出码 0（不阻断启动），但 log 文件必出报告
"""

from __future__ import annotations
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable, Optional

from app.observability import get_logger

_log = get_logger("app.core.config_registry")


class Severity(Enum):
    CRITICAL = "CRITICAL"
    WARNING = "WARNING"
    INFO = "INFO"


@dataclass(frozen=True)
class HardcodeHit:
    path: str          # 相对 d:\Aging
    line: int
    severity: Severity
    category: str      # "color_hex" / "color_rgba" / "numeric" / "text_user_visible" / "inline_qss"
    snippet: str       # 该行原文（截断 80 字符）
    suggestion: str    # 建议替换为哪个 token / config / labels 项


# ---- 扫描正则 -------------------------------------------------------------
COLOR_HEX_RE = re.compile(r"#[0-9a-fA-F]{6}\b")
COLOR_RGBA_RE = re.compile(r"rgba?\s*\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*(?:,\s*[\d.]+\s*)?\)")
INLINE_QSS_RE = re.compile(r'setStyleSheet\s*\(\s*[rf]?["\']{1,3}')

# 数字字面量：>= 2 位的纯数字（避开 0/1/2 索引）
NUMERIC_RE = re.compile(r"(?<![A-Za-z_\d])\d{2,}(?![A-Za-z_\d])")

# 用户可见中文文本（粗匹配）
USER_TEXT_RE = re.compile(r'[\u4e00-\u9fff]{2,}')


# ---- 白名单（豁免） -------------------------------------------------------
# 哪些文件/行/模式应该被豁免
ALLOWED_COLOR_HEX_PATHS = {
    "app/core/tokens.py",                  # 定义本身
    "app/styles/templates.py",             # QSS 入口（应当被工具化，但允许临时直接 hex）
    # 后续迁移完后，此条会移除
}

ALLOWED_COLOR_HEX_LINE_FRAGMENTS = {
    "# noqa: hardcode",  # 行尾标记（强制豁免）
}

ALLOWED_RGBA_PATHS = {
    "app/core/tokens.py",
    "app/styles/templates.py",  # 临时豁免，本期 A 阶段后移除
}

ALLOWED_INLINE_QSS_PATHS = {
    "app/styles/templates.py",  # 模板本身
}

# 数字字面量：1 位数（0/1）+ 索引/计数器（grid index）+ 0.x 系数全部豁免
ALLOWED_NUMERIC_PATTERNS = {
    r"^0\.\d+$",                  # 0.3 / 0.5
    r"^\d+%$",                    # 50% / 100%
    r"^rgb\(\d+,\s*\d+,\s*\d+\)$",  # QSS 内部
}


def _is_exempt(path: str, line_no: int, line_text: str, regex: re.Pattern) -> bool:
    """判断该行是否豁免。"""
    rel = path.replace("\\", "/")
    # 1) 文件白名单
    if rel in ALLOWED_COLOR_HEX_PATHS and regex in (COLOR_HEX_RE, COLOR_RGBA_RE):
        return True
    if rel in ALLOWED_INLINE_QSS_PATHS and regex is INLINE_QSS_RE:
        return True
    # 2) 行尾标记
    for frag in ALLOWED_COLOR_HEX_LINE_FRAGMENTS:
        if frag in line_text:
            return True
    # 3) 数字豁免（模式匹配）
    if regex is NUMERIC_RE:
        for pat in ALLOWED_NUMERIC_PATTERNS:
            if re.match(pat, line_text.strip()):
                return True
    return False


def _make_suggestion(category: str, snippet: str) -> str:
    """基于 category 给出建议（粗略启发式）。"""
    if category == "color_hex":
        # TODO: 后续做 hash 匹配找最近 token
        return "→ tokens.Colors.xxx (新增角色色 token)"
    if category == "color_rgba":
        return "→ tokens.rgba(c.XXX, alpha) 工具"
    if category == "inline_qss":
        return "→ app.styles.templates.xxx (新增模板函数)"
    if category == "numeric":
        return "→ config.XXX 或 tokens.Sizing.XXX"
    if category == "text_user_visible":
        return "→ labels.XXX (新增用户可见文本常量)"
    return "→ 待定"


def scan_and_report(
    root: str = "app",
    *,
    raise_on_critical: bool = False,
) -> list[HardcodeHit]:
    """扫描 root 下所有 .py 文件，返回硬编码命中列表。

    Args:
        root: 扫描根目录（相对 d:\Aging）
        raise_on_critical: True 则发现 CRITICAL 抛异常（默认 False，仅报告）

    Returns:
        HardcodeHit 列表（按 severity 排序）
    """
    hits: list[HardcodeHit] = []
    root_path = Path(root)
    for py_file in root_path.rglob("*.py"):
        rel = str(py_file).replace("\\", "/")
        try:
            text = py_file.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            # 1) color hex
            for m in COLOR_HEX_RE.finditer(line):
                if _is_exempt(rel, line_no, line, COLOR_HEX_RE):
                    continue
                hits.append(HardcodeHit(
                    path=rel, line=line_no, severity=Severity.CRITICAL,
                    category="color_hex", snippet=line[:80],
                    suggestion=_make_suggestion("color_hex", line),
                ))
            # 2) color rgba
            for m in COLOR_RGBA_RE.finditer(line):
                if _is_exempt(rel, line_no, line, COLOR_RGBA_RE):
                    continue
                hits.append(HardcodeHit(
                    path=rel, line=line_no, severity=Severity.CRITICAL,
                    category="color_rgba", snippet=line[:80],
                    suggestion=_make_suggestion("color_rgba", line),
                ))
            # 3) inline qss
            for m in INLINE_QSS_RE.finditer(line):
                if _is_exempt(rel, line_no, line, INLINE_QSS_RE):
                    continue
                hits.append(HardcodeHit(
                    path=rel, line=line_no, severity=Severity.WARNING,
                    category="inline_qss", snippet=line[:80],
                    suggestion=_make_suggestion("inline_qss", line),
                ))
            # 4) numeric (ui/widgets 路径下 WARNING)
            if "/ui/" in rel or "/widgets/" in rel:
                for m in NUMERIC_RE.finditer(line):
                    if _is_exempt(rel, line_no, line, NUMERIC_RE):
                        continue
                    hits.append(HardcodeHit(
                        path=rel, line=line_no, severity=Severity.WARNING,
                        category="numeric", snippet=line[:80],
                        suggestion=_make_suggestion("numeric", line),
                    ))
            # 5) user-visible text (ui/widgets 路径下 INFO)
            if "/ui/" in rel or "/widgets/" in rel:
                for m in USER_TEXT_RE.finditer(line):
                    snippet = m.group(0)
                    if len(snippet) < 4:  # 过滤短词（如"启动"）
                        continue
                    hits.append(HardcodeHit(
                        path=rel, line=line_no, severity=Severity.INFO,
                        category="text_user_visible", snippet=line[:80],
                        suggestion=_make_suggestion("text_user_visible", line),
                    ))

    # 排序：CRITICAL > WARNING > INFO；同 severity 按路径+行号
    hits.sort(key=lambda h: (h.severity.value, h.path, h.line))

    # 报告
    if not hits:
        _log.info("config_registry: no hardcode leak detected ✓")
        return hits

    by_sev: dict[str, list[HardcodeHit]] = {"CRITICAL": [], "WARNING": [], "INFO": []}
    for h in hits:
        by_sev[h.severity.value].append(h)

    _log.warning(
        "config_registry: %d hardcode hits (CRITICAL=%d WARNING=%d INFO=%d)",
        len(hits), len(by_sev["CRITICAL"]), len(by_sev["WARNING"]), len(by_sev["INFO"]),
    )
    for sev_name in ("CRITICAL", "WARNING", "INFO"):
        if not by_sev[sev_name]:
            continue
        _log.warning("--- %s (%d) ---", sev_name, len(by_sev[sev_name]))
        for h in by_sev[sev_name][:20]:  # 每级最多展示 20 条
            _log.warning("  %s:%d  [%s]  %s", h.path, h.line, h.category, h.snippet)
            _log.warning("    %s", h.suggestion)
        if len(by_sev[sev_name]) > 20:
            _log.warning("  ... (%d more)", len(by_sev[sev_name]) - 20)

    if by_sev["CRITICAL"] and raise_on_critical:
        raise RuntimeError(
            f"config_registry: {len(by_sev['CRITICAL'])} CRITICAL hardcode leaks, "
            f"see logs/app.log for details"
        )

    return hits


if __name__ == "__main__":
    # 独立跑：python -m app.core.config_registry
    import sys
    sys.path.insert(0, r"d:\Aging")
    hits = scan_and_report(raise_on_critical=False)
    print(f"\n[summary] {len(hits)} hits")
    sys.exit(0)
```

### 3.3 启动期集成

[Main.py:35](file:///d:/Aging/Main.py#L35) 改为：

```python
def main() -> int:
    configure_logging()
    _log = get_logger("app.system")
    _log.info("aging system v3.0 starting...")

    # 硬编码治理：启动期扫描（不阻断启动）
    from app.core.config_registry import scan_and_report
    scan_and_report()

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    install_exception_hooks(app)

    try:
        app.setStyleSheet(build_stylesheet(DEFAULT_TOKENS))
        _log.info("qss applied (%d bytes)", len(app.styleSheet()))
    except Exception as e:
        _log.critical("qss load failed: %r\n  app will run with default style", e, exc_info=True)

    win = HomePage()
    win.show()

    _log.info("ui ready, entering event loop")
    return app.exec_()
```

### 3.4 验证器与三件套的关系

| 时刻 | 验证器动作 | 期望 |
|------|-----------|------|
| **启动期** | 扫描 app/ 全工程 | CRITICAL=0, WARNING<=10（迁移中），INFO 自由 |
| **A 阶段完成** | 扫一次 | templates.py 的 14+4 处全部消失 → CRITICAL=0 |
| **B 阶段完成** | 扫一次 | nav_bar/floaters 的 18+ 处内联 QSS 全部消失 → WARNING 显著下降 |
| **C 阶段完成** | 扫一次 | 数字字面量（除 0/1）全部走 config/tokens → WARNING 趋近 0 |
| **D 阶段完成** | 扫一次 | 状态栏/footer/启动文案全部走 labels → INFO 趋近 0 |
| **E 阶段完成** | 扫一次 | 移除 templates.py 的 hex 临时豁免，强制走 `rgba(c.xxx, alpha)` → 全绿 |

---

## 4. 4 块清理工作的实施步骤

按依赖顺序：A → B → C → D → E。每阶段独立可回滚。

### 阶段 A：模板内硬编码收口（templates.py 14+4 处）

**目标**：把 [templates.py](file:///d:/Aging/app/styles/templates.py) 中的 14+4 处 `rgba()` / 裸 hex 全部 token 化。

**新增**（[tokens.py](file:///d:/Aging/app/core/tokens.py)）：

```python
# 在 Sizing 之前新增：

def rgba(color: str, alpha: int) -> str:
    """token 化 rgba 工具：把 #RRGGBB 转 rgba(R, G, B, alpha)。

    Args:
        color: 形如 "#00bfff" 的 hex 字符串
        alpha: 0-255 的整数

    Returns:
        形如 "rgba(0, 191, 255, 50)" 的字符串
    """
    if not color.startswith("#") or len(color) != 7:
        raise ValueError(f"rgba() expects #RRGGBB, got {color!r}")
    r = int(color[1:3], 16)
    g = int(color[3:5], 16)
    b = int(color[5:7], 16)
    return f"rgba({r}, {g}, {b}, {alpha})"
```

**修改**（[templates.py](file:///d:/Aging/app/styles/templates.py)）：

| 位置 | 改前 | 改后 |
|------|------|------|
| L42 | `border-top: 1px solid rgba(0, 191, 255, 40);` | `border-top: 1px solid {rgba(c.BORDER_PRIMARY, 40)};` |
| L66 | `background-color: rgba(0, 191, 255, 50);` | `background-color: {rgba(c.BORDER_PRIMARY, 50)};` |
| L93 | `border-bottom: 1px dashed rgba(0, 191, 255, 50);` | `border-bottom: 1px dashed {rgba(c.BORDER_PRIMARY, 50)};` |
| L111 | `border-top: 1px dashed rgba(0, 191, 255, 30);` | `border-top: 1px dashed {rgba(c.BORDER_PRIMARY, 30)};` |
| L160 | `background-color: rgba(0, 191, 255, 30);` | `background-color: {rgba(c.BORDER_PRIMARY, 30)};` |
| L441 | `color: #ffd0d8;` | `color: {c.TEXT_DANGER_LIGHT};`（需新增 token） |
| L442 | `border: 2px solid #ff5a78;` | `border: 2px solid {c.BORDER_DANGER_LIGHT};`（需新增 token） |
| L693 | `stop:1 #ffd166);` | `stop:1 {c.PROGRESS_CHUNK_WARNING_LIGHT});`（需新增） |
| L698 | `stop:1 #ff7090);` | `stop:1 {c.PROGRESS_CHUNK_EXPIRED_LIGHT});`（需新增） |

**新增 token**（必须配套，否则方案不闭环）：

```python
# Colors 类追加
TEXT_DANGER_LIGHT: str = "#ffd0d8"           # 危险态浅色（用在深色背景下）
BORDER_DANGER_LIGHT: str = "#ff5a78"         # 危险态浅边框
PROGRESS_CHUNK_WARNING_LIGHT: str = "#ffd166" # 警告渐变末端
PROGRESS_CHUNK_EXPIRED_LIGHT: str = "#ff7090" # 归零渐变末端

# 4 处未归类色（rgba(16, 255, 161, 90) 等运行/告警渐变）：
GRADIENT_RUNNING_START: str = "rgba(16, 255, 161, 90)"   # 运行态渐变起
GRADIENT_RUNNING_END: str = "rgba(16, 200, 130, 70)"     # 运行态渐变末
GRADIENT_RUNNING_BORDER: str = "rgba(16, 255, 161, 110)" # 运行态边框
GRADIENT_ALERT_BG_START: str = "rgba(80, 18, 36, 200)"   # 告警背景起
GRADIENT_ALERT_BG_END: str = "rgba(40, 8, 18, 200)"      # 告警背景末
GRADIENT_ALERT_BG_HOVER_START: str = "rgba(120, 30, 50, 220)"
GRADIENT_ALERT_BG_HOVER_END: str = "rgba(60, 12, 24, 220)"

# 74,217,255 反复出现的"光晕蓝"
GLOW_LIGHT_CYAN_LOW: str = "rgba(74, 217, 255, 0)"       # 渐变两端透明
GLOW_LIGHT_CYAN_MID: str = "rgba(74, 217, 255, 80)"      # 渐变中段
GLOW_LIGHT_CYAN_HIGH: str = "rgba(74, 217, 255, 140)"    # hover 中段
GLOW_LIGHT_CYAN_BORDER: str = "rgba(74, 217, 255, 60)"   # 边框
GLOW_LIGHT_CYAN_ALERT: str = "rgba(255, 59, 92, 100)"    # 告警叠加
```

**预期产出**：
- templates.py 内部 0 处裸 hex / 0 处裸 rgba
- `Grep "#[0-9a-fA-F]{6}\b" app/styles/templates.py` 无命中
- `Grep "rgba\(" app/styles/templates.py` 仅命中 `tokens.rgba()` 调用

**验证命令**：
```powershell
& E:\MiniConda\envs\Aging\python.exe -m py_compile d:\Aging\app\core\tokens.py d:\Aging\app\styles\templates.py
& E:\MiniConda\envs\Aging\python.exe d:\Aging\Main.py
# 目视：3D 主页视觉与改前像素级一致
& E:\MiniConda\envs\Aging\python.exe -c "from app.core import config_registry; config_registry.scan_and_report()"
# 期望：CRITICAL=0 (templates.py 路径已豁免移除)
```

**回滚**：`git checkout HEAD -- app/core/tokens.py app/styles/templates.py`

---

### 阶段 B：UI 内联 QSS 迁出（nav_bar / floaters）

**目标**：把 [nav_bar.py](file:///d:/Aging/app/ui/nav_bar.py) / [floaters.py](file:///d:/Aging/app/ui/floaters.py) 中的 18+ 处内联 QSS 全部迁到 [templates.py](file:///d:/Aging/app/styles/templates.py)。

**新增模板**（[templates.py](file:///d:/Aging/app/styles/templates.py)）：

```python
# 在文件末尾追加：

def nav_bar(t: DesignTokens) -> str:
    """导航条样式：左/右/中三栏布局 + 选中态高亮。"""
    c = t.colors
    return f"""
QFrame#navBar {{
    background-color: {c.BG_DEEP};
    border-top: 1px solid {rgba(c.BORDER_PRIMARY, 60)};
    border-bottom: 1px solid {rgba(c.BORDER_PRIMARY, 30)};
}}
QFrame#navLeft, QFrame#navRight {{
    background: transparent;
}}
QPushButton#navBtn {{
    background: transparent;
    color: {c.TEXT_PRIMARY};
    border: none;
    padding: 8px 16px;
    font-family: {t.fonts.FAMILY_TITLE};
    font-size: {t.font_sizes.MD}pt;
}}
QPushButton#navBtn:hover {{
    background-color: {rgba(c.BORDER_PRIMARY, 25)};
    border-bottom: 2px solid {rgba(c.TEXT_NEON_CYAN, 120)};
}}
QPushButton#navBtn:checked {{
    background-color: {rgba(c.BORDER_PRIMARY, 60)};
    border-bottom: 2px solid {c.TEXT_NEON_CYAN};
}}
"""

def floater_panel(t: DesignTokens) -> str:
    """悬浮面板（信息提示/告警浮窗）：半透明深色背景 + 状态色边框。"""
    c = t.colors
    return f"""
QFrame#floater {{
    background-color: {rgba(c.BG_BASE, 200)};
    border-radius: {t.sizing.RADIUS_MD}px;
    border: 1px solid {rgba(c.BORDER_OFFLINE, 140)};
}}
QFrame#floater[running="true"] {{
    border: 1px solid {rgba(c.LED_RUNNING[0], c.LED_RUNNING[1], c.LED_RUNNING[2], 160)};
}}
QFrame#floater[alert="true"] {{
    border: 1px solid {rgba(c.LED_ALERT[0], c.LED_ALERT[1], c.LED_ALERT[2], 180)};
}}
QFrame#floater[warning="true"] {{
    border: 1px solid {rgba(c.LED_WARNING[0], c.LED_WARNING[1], c.LED_WARNING[2], 180)};
}}
QLabel#floaterTitle {{
    color: {c.TEXT_NEON_CYAN};
    font-family: {t.fonts.FAMILY_TITLE};
    font-size: {t.font_sizes.SM}pt;
}}
"""
```

**修改**：

| 文件 | 改动 |
|------|------|
| [nav_bar.py](file:///d:/Aging/app/ui/nav_bar.py) | 删 9 处 `setStyleSheet("...")`；改用 `setObjectName("navBar/navBtn/...")` + 集中 QSS |
| [floaters.py](file:///d:/Aging/app/ui/floaters.py) | 删 9 处 `setStyleSheet("...")` + `border = "rgba(...)"`；改用 `setObjectName` + property |

**预期产出**：
- nav_bar.py / floaters.py 内部 0 处 `setStyleSheet` 调用
- 所有样式集中在 [templates.py](file:///d:/Aging/app/styles/templates.py)

**回滚**：`git checkout HEAD -- app/ui/nav_bar.py app/ui/floaters.py app/styles/templates.py`

---

### 阶段 C：数字字面量收口（main_3d / home_page / detail_page）

**目标**：把 widget 内的 `setMinimumSize(56)` / `setFixedHeight(64)` 等内联数字替换为 `tokens.Sizing.XXX` 或 `config.XXX`。

**新增**（[Sizing](file:///d:/Aging/app/core/tokens.py) 类追加）：

```python
# 3D 视图
GL_PANEL_W: int = 800
GL_PANEL_H: int = 600
GL_MIN_W: int = 400
GL_MIN_H: int = 300

# 详情页（已有，再补）
DETAIL_HEADER_H: int = 56
DETAIL_ACTIONS_H: int = 96
DETAIL_PADDING: int = 16
```

**新增**（[config.py](file:///d:/Aging/app/core/config.py) 追加）：

```python
# 3D 相机参数
CAMERA_DIST: float = 26.0
CAMERA_AZIM: float = 90.0
CAMERA_CENTER: tuple = (0, 0, -1.0)

# LED 参数
LED_SIZE: float = 0.675
LED_SPACING: float = 1.5
PANEL_THICKNESS: float = 0.9
PICK_THRESHOLD_PX: int = 80

# 拖拽检测
CLICK_DRAG_THRESHOLD_PX: float = 15.0
```

**修改**（[main_3d.py](file:///d:/Aging/app/ui/main_3d.py)）：

| 位置 | 改前 | 改后 |
|------|------|------|
| GL widget 尺寸 | `setMinimumSize(400, 300)` | `setMinimumSize(tokens.DEFAULT_TOKENS.sizing.GL_MIN_W, ...)` |
| 相机参数 | `dist=30.0, azim=90` | `dist=config.CAMERA_DIST, azim=config.CAMERA_AZIM` |
| pick 阈值 | `THRESHOLD_PX = 80` | `THRESHOLD_PX = config.PICK_THRESHOLD_PX` |
| LED 尺寸 | `size=0.675` | `size=config.LED_SIZE` |

**预期产出**：
- main_3d.py / home_page.py / detail_page.py 内部无 2+ 位数字字面量（除 0/1/索引）
- `Grep -E 'setMinimumSize|setFixedHeight|setFixedWidth' app/ui` 全部用 token/config

**回滚**：`git checkout HEAD -- app/ui/main_3d.py app/ui/home_page.py app/ui/pages/detail_page.py app/core/tokens.py app/core/config.py`

---

### 阶段 D：用户可见文本集中（状态栏 / footer / 启动文案）

**目标**：把 [Main.py](file:///d:/Aging/Main.py) / [home_page.py](file:///d:/Aging/app/ui/home_page.py) / [nav_bar.py](file:///d:/Aging/app/ui/nav_bar.py) / [floaters.py](file:///d:/Aging/app/ui/floaters.py) 中的用户可见中文文本（除 logger 文本外）全部走 [labels.py](file:///d:/Aging/app/core/labels.py)。

**新增**（[labels.py](file:///d:/Aging/app/core/labels.py) 追加）：

```python
# ---- 系统状态文本（v3.0 治理）-----------------------------------------
WINDOW_TITLE = "Aging 老化检测系统 v3.0"

STATUS_ONLINE = "● SYSTEM ONLINE"
STATUS_ALERT = "● SYSTEM ALERT"
STATUS_OFFLINE = "● OFFLINE"

FOOTER_TEMPLATE = "{channels} channels · {running} running · {paused} paused · {stopped} stopped"

# ---- 导航条（与 templates.py 对齐）------------------------------------
NAV_HOME = "主页"
NAV_CURRENT = "电流"
NAV_DATA = "数据"
NAV_VIDEO = "视频"
NAV_SETTINGS = "设置"

# ---- 悬浮面板 -------------------------------------------------------
FLOATER_TITLE_RUNNING = "运行中"
FLOATER_TITLE_ALERT = "告警"
FLOATER_TITLE_WARNING = "即将结束"
FLOATER_TITLE_OFFLINE = "未连接"
```

**修改**：所有 `"● SYSTEM ONLINE"` / `"启动"` / `"主页"` 等用户可见字符串替换为 `labels.XXX`。

**预期产出**：
- `Grep -E '"● SYSTEM|"● ON|"● ALERT|"\[ OK \]' app/` 仅命中 [labels.py](file:///d:/Aging/app/core/labels.py)

**回滚**：`git checkout HEAD -- app/core/labels.py app/Main.py app/ui/`

---

### 阶段 E：移除验证器豁免 + 启用 raise_on_critical

**目标**：移除 [templates.py](file:///d:/Aging/app/styles/templates.py) 的临时豁免，强制 `config_registry.scan_and_report(raise_on_critical=True)` 在 CI/启动时阻断。

**修改**（[config_registry.py](file:///d:/Aging/app/core/config_registry.py)）：

```python
# A 阶段完成后移除：
ALLOWED_COLOR_HEX_PATHS = {
    "app/core/tokens.py",
    # "app/styles/templates.py",  # ← 删除此条
}
ALLOWED_RGBA_PATHS = {
    "app/core/tokens.py",
    # "app/styles/templates.py",  # ← 删除此条
}
```

**修改**（[Main.py](file:///d:/Aging/Main.py)）：

```python
# 启动期扫描改为 raise_on_critical=False（生产环境）
# 但提供 CLI 模式：python -m app.core.config_registry --strict
```

**新增**（CLI 入口）：

```python
# app/core/config_registry.py 末尾
if __name__ == "__main__":
    import sys
    sys.path.insert(0, r"d:\Aging")
    strict = "--strict" in sys.argv
    hits = scan_and_report(raise_on_critical=strict)
    print(f"\n[summary] {len(hits)} hits")
    if strict and any(h.severity == Severity.CRITICAL for h in hits):
        sys.exit(1)
    sys.exit(0)
```

**预期产出**：
- 任意时刻 `python -m app.core.config_registry` 输出报告
- CI 集成时 `--strict` 模式阻断

**回滚**：`git checkout HEAD -- app/core/config_registry.py Main.py`

---

## 5. 风险与回滚

### 5.1 风险

| 风险 | 等级 | 缓解 |
|------|------|------|
| templates.py 改完视觉漂移 | 中 | 改前截图 vs 改后截图（2560x1440）人工对比 |
| nav_bar/floaters 迁移后 objectName 漏改 | 中 | 启动后逐个点击导航 + 浮窗，目视无错位 |
| 数字字面量收口过度（误把 0/1 收掉） | 低 | `NUMERIC_RE` 限定为 2+ 位数 |
| 文本收口遗漏（漏改 1 处） | 低 | 阶段 D 开始前 `Grep` 全量建清单 |
| ConfigRegistry 启动扫描耗时（> 500ms） | 低 | 限制为 `rglob("*.py")` 一次性扫，5ms 量级 |
| 验证器误报（如 logger 里的中文） | 中 | `USER_TEXT_RE` 只匹配 ui/widgets 路径，logger 路径豁免 |

### 5.2 回滚粒度

| 粒度 | 命令 |
|------|------|
| 单文件 | `git checkout HEAD -- <file>` |
| 单阶段 | `git revert <stage-commit>` |
| 整体 | `git revert A..E` |
| 紧急回滚 | `git reset --hard <baseline-commit>` |

### 5.3 不做（明确边界）

- **不**引入新依赖（pydantic、pyyaml、jsonschema）
- **不**做 i18n / gettext
- **不**做暗亮主题切换（虽然 ConfigRegistry 留有扩展点）
- **不**重写 QSS 模板函数体（只迁移硬编码）
- **不**动数据生成逻辑（mock_source / protocol）
- **不**改 widget 几何（不改 layout 结构，只改数字来源）

---

## 6. 实施节奏

| 阶段 | 时间 | 性质 | 风险等级 | 失败回退 |
|------|------|------|----------|----------|
| **A** 模板内 token 化 | 0.5 h | 加 rgba 工具 + 新增 12 token + 改 14+4 处 | 🟡 中 | `git revert A` |
| **B** nav_bar/floaters 迁出 | 1.0 h | 新增 2 模板 + 改 18 处 setStyleSheet | 🟡 中 | `git revert B` |
| **C** 数字字面量收口 | 0.5 h | 新增 8 sizing/config + 改 20+ 处 | 🟢 低 | `git revert C` |
| **D** 文本集中 | 0.3 h | 新增 10 labels + 改 5+ 处 | 🟢 低 | `git revert D` |
| **E** 移除豁免 + CLI | 0.2 h | 删 2 行 + 加 CLI 入口 | 🟢 低 | `git revert E` |

**总预估：2.5 h**（5 个 commit，每个独立可回滚）

**前置条件**：
```powershell
cd d:\Aging
git status                    # 确认 working tree 干净
git add -A
git commit -m "chore: hardcode-management baseline (pre config_registry)"
```

---

## 7. 验证方法汇总

| 验证项 | 命令 / 操作 | 期望 |
|--------|-------------|------|
| 编译通过 | `py_compile app/core/{config,config_registry,labels,tokens}.py app/styles/{stylesheet,templates}.py` | 0 错误 |
| 启动正常 | `python d:\Aging\Main.py` | 主页 3D 视觉、导航、悬浮面板、详情页**像素级一致** |
| A 阶段验证 | `python -m app.core.config_registry` | CRITICAL=0, templates 路径下 hex/rgba 全部消失 |
| B 阶段验证 | `Grep "setStyleSheet" app/ui/nav_bar.py app/ui/floaters.py` | 0 命中 |
| C 阶段验证 | `Grep -E "setMinimumSize\(\d{2,}" app/ui/` | 0 命中 |
| D 阶段验证 | `Grep -E '"● SYSTEM|"\[ OK \]' app/` | 仅 labels.py |
| E 阶段验证 | `python -m app.core.config_registry --strict` | 退出码 0（无 CRITICAL） |
| 视觉回归 | 截图对比（2560x1440） | 与 baseline 像素级一致 |

---

## 8. 决策点（待你拍板）

- [ ] **三件套边界**是否符合预期？（config / tokens / labels 各管什么）
- [ ] **ConfigRegistry 验证器**的扫描粒度是否过细？是否需要豁免更多路径？
- [ ] **A 阶段新增 12 个 token**（`TEXT_DANGER_LIGHT` / `BORDER_DANGER_LIGHT` 等）命名是否合理？
- [ ] **B 阶段是否要做**？（nav_bar / floaters 迁移工作量大）
- [ ] **C 阶段数字字面量收口**是否过度？（main_3d 内部还有 GL 数值如 `azim=90`）
- [ ] **5 个阶段顺序**是否合理？是否要合并 A+B？
- [ ] **CRITICAL log 是否阻断启动**？（默认不阻断，可选 CLI 严格模式）
- [ ] **是否纳入 unit test**？（pytest 单元测试冻结 ConfigRegistry 行为）

---

## 9. 后续（不在本轮范围）

- 暗亮主题切换（已有 ConfigRegistry 扩展点，加 LightTokens / DarkTokens 即可）
- pytest 单元测试（ConfigRegistry / tokens / labels）
- i18n（如果未来需要多语言）
- QSS 性能分析（哪些规则代价高）
- IDE 插件（VSCode 标记硬编码行）

---

## 10. 文件依赖速查表

### 10.1 新增/修改文件清单

| 阶段 | 新增 | 修改 |
|------|------|------|
| A | （无） | [tokens.py](file:///d:/Aging/app/core/tokens.py) + [templates.py](file:///d:/Aging/app/styles/templates.py) |
| B | （无） | [templates.py](file:///d:/Aging/app/styles/templates.py) + [nav_bar.py](file:///d:/Aging/app/ui/nav_bar.py) + [floaters.py](file:///d:/Aging/app/ui/floaters.py) |
| C | （无） | [tokens.py](file:///d:/Aging/app/core/tokens.py) + [config.py](file:///d:/Aging/app/core/config.py) + [main_3d.py](file:///d:/Aging/app/ui/main_3d.py) + [home_page.py](file:///d:/Aging/app/ui/home_page.py) + [detail_page.py](file:///d:/Aging/app/ui/pages/detail_page.py) |
| D | （无） | [labels.py](file:///d:/Aging/app/core/labels.py) + [Main.py](file:///d:/Aging/Main.py) + [nav_bar.py](file:///d:/Aging/app/ui/nav_bar.py) + [floaters.py](file:///d:/Aging/app/ui/floaters.py) |
| 0（前置） | [config_registry.py](file:///d:/Aging/app/core/config_registry.py)（新增） | [Main.py](file:///d:/Aging/Main.py) |
| E | CLI 入口（[config_registry.py](file:///d:/Aging/app/core/config_registry.py)） | [config_registry.py](file:///d:/Aging/app/core/config_registry.py) + [Main.py](file:///d:/Aging/Main.py) |

### 10.2 间接依赖

| 文件 | 提供的 API |
|------|-----------|
| [app/observability/logger.py](file:///d:/Aging/app/observability/logger.py) | `get_logger()` |
| [app/observability/__init__.py](file:///d:/Aging/app/observability/__init__.py) | `get_logger` 暴露 |
| [app/core/tokens.py](file:///d:/Aging/app/core/tokens.py) | `DesignTokens` / `DEFAULT_TOKENS` / `rgba()` |
| [app/core/config.py](file:///d:/Aging/app/core/config.py) | 业务常量 |
| [app/core/labels.py](file:///d:/Aging/app/core/labels.py) | 文本常量 |
| [app/styles/templates.py](file:///d:/Aging/app/styles/templates.py) | 模板函数 |
| [app/styles/stylesheet.py](file:///d:/Aging/app/styles/stylesheet.py) | `build_stylesheet()` 合并入口 |

### 10.3 完整依赖方向图

```text
                 tokens.py ──────┐
                 config.py ──────┤
                 labels.py ──────┤
                                 ↓
                          config_registry.py (新增 · 验证器)
                                 ↓
                              Main.py
                                 ↓
                ┌────────────────┼────────────────┐
                ↓                ↓                ↓
          styles/         observability/    ui/
        templates.py       logger.py       home_page.py
        stylesheet.py                     main_3d.py
                                          pages/*.py
                                          nav_bar.py
                                          floaters.py
                                              ↓
                                          widgets/
                                        data_cell.py
                                        cell_grid.py
```

---

## 11. 审阅检查清单

你审阅本文档时建议关注：

1. **§2 三件套边界**：config / tokens / labels 各自的职责清单是否合理？
2. **§3 验证器接口**：`scan_and_report()` 的 5 类规则（color_hex/color_rgba/inline_qss/numeric/text）是否过细/过粗？
3. **§4 阶段 A 新增 token**（12 个）命名是否清晰？
4. **§4 阶段 B 迁移成本**：nav_bar/floaters 改造工作量大，是否拆成 B1/B2？
5. **§4 阶段 C 数字字面量范围**：`main_3d` 的 `azim=90` 等是否要收？
6. **§6 实施节奏**：5 阶段 vs 合并 A+B？
7. **§8 决策点**：8 个待决项逐条回复

---

**审阅完成后**，确认进入 A 阶段时回复"执行 A"或其他具体阶段名。
