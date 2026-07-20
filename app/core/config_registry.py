"""硬编码集中治理 · 启动期扫描验证器（Phase 4-D）。

设计目标：
- 启动时（configure_logging 之后、QApplication 启动之前）扫描全工程
- 发现并报告任何违反"三件套边界"的硬编码
- **不阻断启动**（仅记录到 logs/app.log）
- 退出码始终 0

三件套边界（与 hardcode-management-design.md §2.4 一致）：
- 颜色 / 字号 / 尺寸 / 边距 / 圆角 → app.core.tokens
- 网格规格 / 刷新间隔 / 阈值 / 时长 / 路径 → app.core.config
- 用户可见字符串 → app.core.labels
- QSS 字符串 → app.styles.templates
- 其它路径出现以上内容 → 报告

报告级别：
- CRITICAL — 颜色字面量（hex / rgba）出现在非 tokens/templates 路径
- WARNING — 数字字面量（>= 2 位）出现在 ui/widgets 路径
- INFO    — 用户可见中文文本（>= 2 字符）出现在 ui/widgets 路径
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import List, Pattern

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


# ---- 扫描正则 ---------------------------------------------------------------
# 颜色 hex（7 字符 #RRGGBB，word boundary）
COLOR_HEX_RE = re.compile(r"#[0-9a-fA-F]{6}\b")
# 颜色 rgba/rgb 字面量
COLOR_RGBA_RE = re.compile(
    r"rgba?\s*\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*(?:,\s*[\d.]+\s*)?\)"
)
# 内联 QSS（widget 内 setStyleSheet 字符串）
INLINE_QSS_RE = re.compile(r'setStyleSheet\s*\(\s*[rf]?["\']{1,3}')
# 数字字面量：>= 2 位的纯数字（避开单字符 0/1）
NUMERIC_RE = re.compile(r"(?<![A-Za-z_\d])\d{2,}(?![A-Za-z_\d])")
# 用户可见中文文本（>= 2 个连续汉字）
USER_TEXT_RE = re.compile(r"[\u4e00-\u9fff]{2,}")


# ---- 白名单（豁免） ----------------------------------------------------------
# 哪些文件是"三件套"定义本身 → 不应被扫到
DEFINITION_FILES = {
    "app/core/tokens.py",
    "app/core/config.py",
    "app/core/labels.py",
    "app/core/config_registry.py",   # 自身（验证器中含字面量是预期）
}

# QSS 模板与样式入口（允许集中色字面量）
STYLE_FILES = {
    "app/styles/templates.py",
    "app/styles/stylesheet.py",
}

# 启动期豁免（observability / 入口）
BOOTSTRAP_FILES = {
    "Main.py",
    "app/__init__.py",
}

# 行尾豁免标记
LINE_EXEMPT_MARKER = "# noqa: hardcode"

# 数字豁免：0.x 系数、百分比、rgb 字面量
NUMERIC_EXEMPT_PATTERNS = (
    r"^\s*0\.\d+\s*$",                              # 0.5 / 0.95
    r".*=\s*\d+%\s*$",                              # 50% / 100%
    r"^\s*rgba?\(\d+,\s*\d+,\s*\d+.*\)\s*$",        # rgb(...) 整行
    r"^\s*#[0-9a-fA-F]{6}\s*$",                      # hex 整行
    r"^\s*\d+:\d+\s*$",                             # 9:0 / 16:9 比例
)

# 行内数字豁免（这些是"算法常数"而非 UI 尺寸，应豁免）
#   时间单位：1000 (ms↔s)、60 (s↔m)、24 (h↔d)、360/360.0 (圆周)
#   帧率：30 (pxMode 缩放)、50/20 (fps ms)
#   浮点系数：0.05 / 0.10 / 0.15 / 0.20 / 0.30 / 0.50 / 0.70 / 0.85 / 0.90 / 0.95 / 0.99
INLINE_NUMERIC_EXEMPT = (
    r"\*\s*1000(?:\.0)?",     # * 1000 / * 1000.0
    r"\*\s*1000\.0",          # * 1000.0
    r"/\s*1000(?:\.0)?",      # / 1000 / / 1000.0
    r"//\s*1000",             # // 1000
    r"\*\s*30\b",             # * 30  (pxMode 缩放系数)
    r"%\s*360(?:\.0)?",       # % 360 / % 360.0  圆周取模
    r"\b0\.\d+\b",            # 0.05 / 0.90 等浮点系数（行内）
    r"\b1\.0\b",              # 1.0 浮点单位
    r"\b0\.5\b",              # 0.5 半值系数
)

# 命名常量豁免正则（下划线开头/全大写 + 数字后缀 + 赋值）
NAMED_CONST_RE = re.compile(
    r"^\s*_?[A-Z][A-Z0-9_]*\s*[:=]\s*"   # 例如：_FLOAT_PADDING =  / ROTATE_SPEED_DEG_PER_S:
)


def _is_in_ui_widgets(rel: str) -> bool:
    """判断文件是否在 ui/ 或 widgets/ 路径下。"""
    rel = rel.replace("\\", "/")
    return ("/ui/" in rel or rel.startswith("ui/") or
            "/widgets/" in rel or rel.startswith("widgets/"))


def _is_dynamic_qss_injection(line_text: str) -> bool:
    """识别"动态属性 QSS 注入"模式：setStyleSheet 字符串中只含 f-string + 变量引用，
    没有硬编码颜色/像素/字体。

    示例（豁免）：
        setStyleSheet(f"color: {color};")
        setStyleSheet(f"color: {config.COLOR_TEXT_OK};")
        setStyleSheet(f"background: {bg_color};")

    反例（不豁免，仍报 CRITICAL）：
        setStyleSheet("color: #ff0000;")        # 含 hex
        setStyleSheet("border: 1px solid red;")  # 颜色名
        setStyleSheet("font-size: 12px;")        # 像素字面量
    """
    # 必须是 f-string
    if not re.search(r'setStyleSheet\s*\(\s*f["\']', line_text):
        return False
    # 取出 f-string 内部内容
    m = re.search(r'setStyleSheet\s*\(\s*f["\'](.+?)["\']\s*\)', line_text)
    if not m:
        return False
    body = m.group(1)
    # 移除所有 {...} 占位符（动态变量）
    body = re.sub(r"\{[^}]*\}", "", body)
    # 移除空白/标点
    body = re.sub(r"[\s:;,\(\)]", "", body)
    # 残留：颜色 hex / 颜色名 / 像素值 / 字体名 → 视为含硬编码
    if re.search(r"#[0-9a-fA-F]{3,8}\b", body):
        return False
    if re.search(r"\b\d+px\b", body, re.IGNORECASE):
        return False
    if re.search(r"\b\d+pt\b", body, re.IGNORECASE):
        return False
    # 颜色名（红/绿/青等）通过常见 CSS 颜色名识别
    color_names = {
        "red", "green", "blue", "yellow", "orange", "cyan", "magenta",
        "white", "black", "gray", "grey", "transparent", "none",
    }
    for name in color_names:
        if re.search(rf"\b{name}\b", body, re.IGNORECASE):
            return False
    # 剩余为空或仅含 px/pt 等结构词 → 纯动态注入
    return True


def _is_in_docstring_block(line_text: str, prev_in_doc: bool) -> bool:
    """判断当前行是否在三引号 docstring 块内。

    用 3 引号计数法追踪块状态。
    """
    stripped = line_text.strip()
    # 简化：检查该行是否含未闭合/闭合的三引号
    triple = '"""' in stripped or "'''" in stripped
    return prev_in_doc or triple


def _is_exempt(
    rel: str,
    line_text: str,
    line_no: int,
    category: str,
    in_docstring: bool = False,
) -> bool:
    """判断该行是否豁免。"""
    # 1) 文件白名单
    if rel in DEFINITION_FILES or rel in STYLE_FILES or rel in BOOTSTRAP_FILES:
        return True
    # 2) 行尾标记
    if LINE_EXEMPT_MARKER in line_text:
        return True
    stripped = line_text.strip()
    # 3) 注释/文档字符串豁免（仅对 numeric 和 user_text）
    if category in ("numeric", "text_user_visible"):
        if stripped.startswith("#"):
            return True
        # 行内 # 注释（数字/中文出现在 # 后 → 一定是注释）
        if "#" in line_text:
            comment_idx = line_text.find("#")
            code_part = line_text[:comment_idx]
            text_part = line_text[comment_idx:]
            if category == "numeric":
                if not re.search(NUMERIC_RE, code_part) and re.search(NUMERIC_RE, text_part):
                    return True
            if category == "text_user_visible":
                if not re.search(USER_TEXT_RE, code_part) and re.search(USER_TEXT_RE, text_part):
                    return True
        # 文档字符串内任何内容都豁免
        if in_docstring:
            return True
        # 单行三引号 docstring
        if (stripped.startswith('"""') or stripped.startswith("'''") or
                stripped.startswith('r"""') or stripped.startswith("r'''")):
            return True
    # ---- 数字专用豁免（仅 numeric） ------------------------------------------
    if category == "numeric":
        # 3a) 整行匹配：百分比、rgb、纯 0.x 等
        for pat in NUMERIC_EXEMPT_PATTERNS:
            if re.match(pat, line_text):
                return True
        # 3b) 行内豁免：算法常数（时间单位、浮点系数等）
        for pat in INLINE_NUMERIC_EXEMPT:
            if re.search(pat, line_text):
                return True
        # 3c) tuple/list 索引豁免：xxx[数字]
        if re.search(r"\[[\d,\s]+\]", line_text):
            return True
        # 3d) 命名常量赋值豁免：_FLOAT_PADDING = 24 / _WINDOW_S: int = 180
        if NAMED_CONST_RE.match(stripped):
            return True
        # 3e) 函数/方法形参默认值豁免：def foo(x: int = 200)
        if re.search(r"def\s+\w+\([^)]*=\s*\d", line_text):
            return True
        # 3f) QTimer.setInterval(数字) 豁免（毫秒间隔）
        if "setInterval(" in line_text or "setSingleShot(" in line_text:
            return True
        # 3g) QWidget.move(x, y) / setPos(x, y) 浮点位置
        if re.search(r"\.(?:move|setPos)\(\s*int\(", line_text):
            return True
        # 3h) OpenGL 几何函数：setSize/setSpacing 整型参数
        if re.search(r"\.(?:setSize|setSpacing|setLineWidth)\(\s*[\d.,\s]+\)", line_text):
            return True
    # ---- 文本专用豁免（仅 text_user_visible） -------------------------------
    if category == "text_user_visible":
        # 4a) 字典值映射：KEY: "中文" 形式（state→label 映射，运行时常量）
        if re.match(r"^\s*[A-Za-z_][A-Za-z0-9_.\s]*:\s*[\"']", stripped):
            return True
        # 4b) 字典方法调用：.get(state, "中文")
        if re.search(r"\.get\([^,]+,\s*[\"'][^\"']*[\"']\)", line_text):
            return True
        # 4c) 函数调用关键字参数豁免：note="..." / desc="..." / name="..."
        #     （narrative.event / _log.xxx / .format() / placeholder 构造的元数据）
        #     也匹配 f-string 形式：note=f"..." / desc=f"..."
        if re.search(r"\b(?:note|desc|name|reason|action)\s*=\s*f?[\"']", line_text):
            return True
        # 4d) 状态栏消息：str setStatus / set_status 调用内的 f"..." 中文
        if re.search(r"setStatus\([^,]+,\s*[\"'].*[\u4e00-\u9fff]", line_text):
            return True
        # 4e) f"● ..."  状态栏 dot 前缀消息（典型 status bar 写法）
        if re.search(r"[\"']●\s*[\u4e00-\u9fff]", line_text):
            return True
    return False


def _suggest(category: str) -> str:
    """基于 category 给出建议。"""
    return {
        "color_hex": "→ tokens.Colors.xxx (新增/复用角色色 token)",
        "color_rgba": "→ tokens.rgba(c.XXX, alpha) 工具或新增 rgba 字面量 token",
        "inline_qss": "→ app.styles.templates.xxx (新增模板函数)",
        "numeric": "→ config.XXX 或 tokens.Sizing.XXX",
        "text_user_visible": "→ labels.XXX (新增用户可见文本常量)",
    }.get(category, "→ 待定")


def _scan_line(
    rel: str,
    line_no: int,
    line_text: str,
    hits: List[HardcodeHit],
    in_docstring: bool = False,
) -> None:
    """对单行应用所有规则，命中则追加到 hits。

    in_docstring: 调用方维护的三引号块状态
    """
    is_ui = _is_in_ui_widgets(rel)

    # 1) 颜色 hex — CRITICAL（任何文件都查）
    for _m in COLOR_HEX_RE.finditer(line_text):
        if _is_exempt(rel, line_text, line_no, "color_hex", in_docstring):
            continue
        hits.append(HardcodeHit(
            path=rel, line=line_no, severity=Severity.CRITICAL,
            category="color_hex", snippet=line_text[:80].rstrip(),
            suggestion=_suggest("color_hex"),
        ))

    # 2) 颜色 rgba — CRITICAL
    for _m in COLOR_RGBA_RE.finditer(line_text):
        if _is_exempt(rel, line_text, line_no, "color_rgba", in_docstring):
            continue
        hits.append(HardcodeHit(
            path=rel, line=line_no, severity=Severity.CRITICAL,
            category="color_rgba", snippet=line_text[:80].rstrip(),
            suggestion=_suggest("color_rgba"),
        ))

    # 3) 内联 QSS — CRITICAL（widget 中 setStyleSheet 是硬编码）
    #    豁免：f-string + 纯变量注入（动态属性）
    for _m in INLINE_QSS_RE.finditer(line_text):
        if _is_exempt(rel, line_text, line_no, "inline_qss", in_docstring):
            continue
        if _is_dynamic_qss_injection(line_text):
            continue
        hits.append(HardcodeHit(
            path=rel, line=line_no, severity=Severity.CRITICAL,
            category="inline_qss", snippet=line_text[:80].rstrip(),
            suggestion=_suggest("inline_qss"),
        ))

    # 4) 数字字面量 — WARNING（仅 ui/widgets 路径）
    if is_ui:
        for m in NUMERIC_RE.finditer(line_text):
            if _is_exempt(rel, line_text, line_no, "numeric", in_docstring):
                continue
            hits.append(HardcodeHit(
                path=rel, line=line_no, severity=Severity.WARNING,
                category="numeric", snippet=line_text[:80].rstrip(),
                suggestion=_suggest("numeric"),
            ))

    # 5) 用户可见中文文本 — INFO（仅 ui/widgets 路径，>= 2 字符）
    if is_ui:
        for m in USER_TEXT_RE.finditer(line_text):
            if _is_exempt(rel, line_text, line_no, "text_user_visible", in_docstring):
                continue
            hits.append(HardcodeHit(
                path=rel, line=line_no, severity=Severity.INFO,
                category="text_user_visible", snippet=line_text[:80].rstrip(),
                suggestion=_suggest("text_user_visible"),
            ))


def scan(root: str = "app") -> List[HardcodeHit]:
    """扫描 root 目录下所有 .py 文件，返回硬编码命中列表（不报告）。

    Args:
        root: 扫描根目录（相对 d:\Aging）

    Returns:
        HardcodeHit 列表（按 severity 排序）
    """
    hits: List[HardcodeHit] = []
    root_path = Path(root)
    if not root_path.exists():
        return hits
    for py_file in root_path.rglob("*.py"):
        rel = str(py_file).replace("\\", "/")
        try:
            text = py_file.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        # 追踪三引号 docstring 块状态（未闭合则后续行都豁免）
        in_doc = False
        for line_no, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            # 计算本行三引号个数（"""和'''分开计算）
            n_dq = line.count('"""')
            n_sq = line.count("'''")
            # 奇数次 = 翻转一次；偶数次 = 状态不变
            triple_flip = (n_dq % 2 == 1) or (n_sq % 2 == 1)
            if not stripped:
                # 空行：不命中，但仍更新三引号状态
                if triple_flip:
                    in_doc = not in_doc
                continue
            # 该行是否豁免 / 命中
            _scan_line(rel, line_no, line, hits, in_docstring=in_doc)
            # 翻转 docstring 状态（奇数三引号才翻转）
            if triple_flip:
                in_doc = not in_doc

    # 排序：CRITICAL > WARNING > INFO；同 severity 按路径+行号
    hits.sort(key=lambda h: (h.severity.value, h.path, h.line))
    return hits


def scan_and_report(root: str = "app") -> List[HardcodeHit]:
    """扫描并报告（启动期入口）。

    Returns:
        HardcodeHit 列表
    """
    hits = scan(root)
    by_sev: dict = {"CRITICAL": [], "WARNING": [], "INFO": []}
    for h in hits:
        by_sev[h.severity.value].append(h)

    n_crit, n_warn, n_info = (
        len(by_sev["CRITICAL"]), len(by_sev["WARNING"]), len(by_sev["INFO"]),
    )
    total = len(hits)

    if total == 0:
        _log.info("config_registry: no hardcode leak detected (clean)")
        return hits

    # 主摘要行（warning 级别确保写入 app.log）
    _log.warning(
        "config_registry: %d hardcode hits (CRITICAL=%d WARNING=%d INFO=%d)",
        total, n_crit, n_warn, n_info,
    )
    # 每级最多展示 10 条（避免启动期日志爆量）
    for sev_name in ("CRITICAL", "WARNING", "INFO"):
        items = by_sev[sev_name]
        if not items:
            continue
        _log.warning("--- %s (%d) ---", sev_name, len(items))
        for h in items[:10]:
            _log.warning("  %s:%d  [%s]  %s", h.path, h.line, h.category, h.snippet)
            _log.warning("    %s", h.suggestion)
        if len(items) > 10:
            _log.warning("  ... (%d more omitted)", len(items) - 10)
    return hits


__all__ = [
    "Severity",
    "HardcodeHit",
    "scan",
    "scan_and_report",
]
