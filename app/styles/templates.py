"""QSS 模板（按 widget 分块）。

每个模板函数接收一个 `DesignTokens` 实例，返回一段 QSS 字符串。
模板**不**包含任何裸 hex / 字号 / 字体名——所有视觉量从 `tokens` 读取。
"""

from app.core.tokens import DesignTokens, rgba


# ---- 主窗口背景 -------------------------------------------------------------
def main_window(t: DesignTokens) -> str:
    c = t.colors
    return f"""
QMainWindow {{
    background-color: {c.BG_DEEP};
    background-image:
        qradialgradient(cx:0.15, cy:0.20, radius:0.50, fx:0.15, fy:0.20,
                        stop:0 {c.GLOW_CYAN}, stop:1 {c.GLOW_CYAN}),
        qradialgradient(cx:0.85, cy:0.85, radius:0.55, fx:0.85, fy:0.85,
                        stop:0 {c.GLOW_PURPLE}, stop:1 {c.GLOW_PURPLE}),
        qradialgradient(cx:0.50, cy:0.50, radius:1.20, fx:0.50, fy:0.50,
                        stop:0 {c.BG_DEEP_GRAD_INNER}, stop:0.55 {c.BG_MID}, stop:1 {c.BG_DEEP_GRAD_OUTER});
}}
"""


# ---- 电流检测页工具条 + 详情面板（Phase A.1） ----------------------------
def current_page(t: DesignTokens) -> str:
    """电流检测页：工具条 + CellGrid 滚动区 + 详情面板。"""
    c, fs = t.colors, t.font_sizes
    f, s = t.fonts, t.sizing
    return f"""
QWidget#currentPage {{
    background-color: {c.BG_DEEP};
}}

QFrame#currentToolbar {{
    background-color: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 {c.BG_TITLE_BAR}, stop:1 {c.BG_DEEP});
    border-bottom: 1px solid {c.BORDER_PRIMARY};
    border-top: 1px solid {rgba(c.BORDER_PRIMARY, 40)};
}}

QLabel#currentTitle {{
    color: {c.TEXT_NEON_CYAN};
    font-family: {f.FAMILY_TITLE};
    font-size: 14pt;
    font-weight: bold;
    letter-spacing: 2px;
    background: transparent;
}}

QLabel#currentInfo {{
    color: {c.TEXT_DIM};
    font-family: {f.FAMILY_MONO};
    font-size: 10pt;
    background: transparent;
}}

QSplitter#currentSplitter {{
    background-color: {c.BG_DEEP};
}}

QSplitter#currentSplitter::handle {{
    background-color: {rgba(c.BORDER_PRIMARY, 50)};
}}

QScrollArea#cellGridScroll {{
    background-color: {c.BG_DEEP};
    border: none;
}}

QScrollArea#cellGridScroll > QWidget > QWidget {{
    background-color: {c.BG_DEEP};
}}

QFrame#currentDetailPanel {{
    background-color: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 {c.BG_RIGHT_PANEL}, stop:1 {c.BG_DEEP});
    border-left: 1px solid {c.BORDER_PRIMARY};
}}

QLabel#detailTitle {{
    color: {c.TEXT_NEON_CYAN};
    font-family: {f.FAMILY_TITLE};
    font-size: 14pt;
    font-weight: bold;
    letter-spacing: 2px;
    background: transparent;
    padding-bottom: 8px;
    border-bottom: 1px dashed {rgba(c.BORDER_PRIMARY, 50)};
}}

QLabel#detailPlaceholder {{
    color: {c.TEXT_DIM};
    font-family: {f.FAMILY_MONO};
    font-size: 11pt;
    font-style: italic;
    background: transparent;
    padding: 20px;
}}

QLabel#detailInfo {{
    color: {c.TEXT_SECONDARY};
    font-family: {f.FAMILY_MONO};
    font-size: 10pt;
    background: transparent;
    padding: 8px;
    border-top: 1px dashed {rgba(c.BORDER_PRIMARY, 30)};
}}

QFrame#detailValueBox {{
    background-color: {c.BG_BTN_BOTTOM};
    border: 1px solid {c.BORDER_PRIMARY};
    border-radius: 4px;
    padding: 4px 2px;
}}

QLabel#detailChannelName {{
    color: {c.TEXT_DIM};
    font-family: {f.FAMILY_MONO};
    font-size: 8pt;
    font-weight: bold;
    background: transparent;
}}

QLabel#detailChannelValue {{
    color: {c.TEXT_NEON_CYAN};
    font-family: {f.FAMILY_DATA};
    font-size: 13pt;
    font-weight: bold;
    background: transparent;
}}

/* ---- 工具条（Phase A.8） ------------------------------------------------- */
QLabel#currentTitle {{
    color: {c.BORDER_PRIMARY};
    font-family: {f.FAMILY_MONO};
    font-size: 12pt;
    font-weight: bold;
    letter-spacing: 1px;
    background: transparent;
}}
QLabel#currentInfo {{
    color: {c.TEXT_SECONDARY};
    font-family: {f.FAMILY_MONO};
    font-size: 9pt;
    background: transparent;
}}
QLabel#selectionCount {{
    color: {c.TEXT_NEON_CYAN};
    font-family: {f.FAMILY_DATA};
    font-size: 11pt;
    font-weight: bold;
    padding: 2px 8px;
    border: 1px solid {c.BORDER_PRIMARY};
    border-radius: 4px;
    background-color: {rgba(c.BORDER_PRIMARY, 30)};
}}

/* 批量按钮（Phase A.8） */
QPushButton#btnBatch {{
    background-color: {c.BG_BTN_BOTTOM};
    color: {c.TEXT_PRIMARY};
    border: 1px solid {c.BORDER_PRIMARY};
    border-radius: 4px;
    padding: 4px 12px;
    font-family: {f.FAMILY_BUTTON};
    font-size: 10pt;
    font-weight: bold;
    min-width: 64px;
}}
QPushButton#btnBatch:hover {{
    background-color: {c.BG_BTN_HOVER_TOP};
    border: 1px solid {c.BORDER_HOVER};
    color: {c.BORDER_HOVER};
}}
QPushButton#btnBatch:pressed {{
    background-color: {c.BORDER_PRIMARY};
    color: {c.BG_DEEP};
}}
QPushButton#btnBatch:disabled {{
    color: {c.TEXT_DIM};
    border: 1px solid {c.BORDER_BTN_DISABLED};
    background-color: {c.BG_BTN_BOTTOM};
}}

/* ---- 3D LED hover tooltip（Phase A.8.3） --------------------------------- */
QLabel#hoverTooltip {{
    color: {c.TEXT_NEON_CYAN};
    font-family: {f.FAMILY_DATA};
    font-size: 10pt;
    font-weight: bold;
    background-color: {rgba(c.BG_BASE, 220)};
    border: 1px solid {c.BORDER_PRIMARY};
    border-radius: 4px;
    padding: 4px 8px;
}}
"""


# ---- 标题栏 -----------------------------------------------------------------
def title_bar(t: DesignTokens) -> str:
    c, fs = t.colors, t.font_sizes
    f = t.fonts
    s = t.sizing
    return f"""
QWidget#titleBar {{
    background-color: {c.BG_TITLE_BAR};
    border-bottom: {s.BORDER_THICK}px solid {c.BORDER_PRIMARY};
}}
QLabel#titleText {{
    color: {c.BORDER_PRIMARY};
    font-family: {f.FAMILY_TITLE};
    font-size: {fs.TITLE}pt;
    font-weight: bold;
    letter-spacing: 3px;
    background: transparent;
    padding: 8px 16px;
}}
QLabel#titleAccent {{
    color: {c.TEXT_NEON_GREEN};
    font-family: {f.FAMILY_MONO};
    font-size: {fs.ACCENT}pt;
    background: transparent;
    padding: 8px 16px;
}}
"""


# ---- 数据单元容器（最外层） -------------------------------------------------
def data_cell(t: DesignTokens) -> str:
    c = t.colors
    s = t.sizing
    return f"""
QWidget#dataCell {{
    background-color: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 {c.BG_CELL_TOP}, stop:1 {c.BG_CELL_BOTTOM});
    border: {s.BORDER_THICK}px solid {c.BORDER_PRIMARY};
    border-radius: {s.RADIUS_CELL}px;
}}
QWidget#dataCell[status="online"] {{
    border: {s.BORDER_THICK}px solid {c.BORDER_PRIMARY};
}}
QWidget#dataCell[status="anomaly"] {{
    border: {s.BORDER_THICK}px solid {c.BORDER_DANGER};
    background-color: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 {c.BG_CELL_ALERT_TOP}, stop:1 {c.BG_CELL_ALERT_BOTTOM});
}}
QWidget#dataCell[status="offline"] {{
    border: {s.BORDER_THICK}px solid {c.BORDER_OFFLINE};
    background-color: {c.BG_TITLE_BAR};
}}
QWidget#dataCell[status="no_data"] {{
    border: {s.BORDER_THICK}px solid {c.BORDER_NO_DATA};
    background-color: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 {c.BG_CELL_NO_DATA_TOP}, stop:1 {c.BG_CELL_NO_DATA_BOTTOM});
}}
QWidget#dataCell[hovered="true"] {{
    border: {s.BORDER_THICK}px solid {c.BORDER_HOVER};
}}
QWidget#dataCell[hovered="true"][status="no_data"] {{
    border: {s.BORDER_THICK}px solid {c.BORDER_NO_DATA};
}}
QWidget#dataCell[selected="true"] {{
    border: 4px solid {c.BORDER_SELECTED};
}}
QWidget#dataCell[selected="true"][status="no_data"] {{
    border: 4px solid {c.BORDER_SELECTED_NODATA};
}}
QWidget#dataCell[selected="true"][status="anomaly"] {{
    border: 4px solid {c.BORDER_SELECTED_ANOMALY};
}}
/* ---- 倒计时归零·闪烁高亮绿色（on/off 切换，500ms 间隔） ---------------- */
QWidget#dataCell[expired_pending="on"] {{
    border: 3px solid {c.TEXT_NEON_GREEN};
    background-color: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 {c.GRADIENT_RUNNING_START}, stop:1 {c.GRADIENT_RUNNING_END});
}}
QWidget#dataCell[expired_pending="off"] {{
    border: 2px solid {c.GRADIENT_RUNNING_BORDER};
}}
QWidget#dataCell[expired_pending="on"][selected="true"] {{
    border: 3px solid {c.TEXT_NEON_GREEN};
}}
"""


# ---- 头部信息行 -------------------------------------------------------------
def header_bar(t: DesignTokens) -> str:
    c, fs = t.colors, t.font_sizes
    f = t.fonts
    s = t.sizing
    return f"""
QWidget#headerBar {{
    background-color: transparent;
    border: none;
    border-bottom: {s.BORDER_THIN}px solid {c.BORDER_PRIMARY};
    border-radius: 0px;
}}
QLabel#cellId {{
    color: {c.BORDER_PRIMARY};
    font-family: {f.FAMILY_MONO};
    font-size: {fs.CELL_ID}pt;
    font-weight: bold;
    background: transparent;
}}
QWidget#dataCell[status="no_data"] QLabel#cellId {{
    color: {c.TEXT_NO_DATA};
}}
QLabel#cellStatus {{
    font-family: {f.FAMILY_MONO};
    font-size: {fs.CELL_STATUS}pt;
    font-weight: bold;
    background: transparent;
}}
"""


# ---- 2x4 数据网格容器 -------------------------------------------------------
def data_grid(t: DesignTokens) -> str:
    c = t.colors
    s = t.sizing
    return f"""
QWidget#dataGrid {{
    background-color: {c.BG_DATAGRID};
    border: {s.BORDER_THICK}px solid {c.BORDER_DARK_BLUE};
    border-radius: {s.RADIUS_LG}px;
}}
QWidget#dataCell[status="no_data"] QWidget#dataGrid {{
    background-color: {c.BG_DATAGRID_NO_DATA};
    border: {s.BORDER_THICK}px solid {c.BORDER_NO_DATA};
}}
"""


# ---- 单个数据点方格 ---------------------------------------------------------
def data_point(t: DesignTokens) -> str:
    c, fs = t.colors, t.font_sizes
    f = t.fonts
    s = t.sizing
    return f"""
QWidget#dataPoint {{
    background-color: {c.BG_DATAPOINT};
    border: {s.BORDER_THICK}px solid {c.BORDER_DARK_BLUE};
    border-radius: {s.RADIUS_SM}px;
}}
QWidget#dataPoint[alert="true"] {{
    background-color: {c.BG_DATAPOINT_ALERT};
    border: {s.BORDER_THICK}px solid {c.BORDER_DANGER};
}}
QLabel#dataPointLabel {{
    color: {c.TEXT_LABEL};
    font-family: {f.FAMILY_DATA};
    font-size: {fs.DATA_POINT_LABEL}pt;
    font-weight: bold;
    background: transparent;
}}
QLabel#dataPointValue {{
    color: {c.TEXT_VALUE};
    font-family: {f.FAMILY_DATA};
    font-size: {fs.DATA_POINT_VALUE}pt;
    font-weight: bold;
    background: transparent;
}}
QLabel#dataPointValue[alert="true"] {{
    color: {c.TEXT_DANGER};
}}
QLabel#dataPointUnit {{
    color: {c.TEXT_LABEL};
    font-family: {f.FAMILY_DATA};
    font-size: {fs.DATA_POINT_UNIT}pt;
    background: transparent;
}}
"""


# ---- 右侧科幻按钮 -----------------------------------------------------------
def button(t: DesignTokens) -> str:
    c, fs = t.colors, t.font_sizes
    f = t.fonts
    return f"""
QPushButton {{
    background-color: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 {c.BG_BTN_TOP}, stop:1 {c.BG_BTN_BOTTOM});
    color: {c.TEXT_PRIMARY};
    border: 2px solid {c.BORDER_PRIMARY};
    border-radius: 6px;
    padding: 12px 16px;
    font-family: {f.FAMILY_BUTTON};
    font-size: {fs.BUTTON}pt;
    font-weight: bold;
    letter-spacing: 1px;
    text-align: left;
    padding-left: 16px;
}}
QPushButton:hover {{
    background-color: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 {c.BG_BTN_HOVER_TOP}, stop:1 {c.BG_BTN_HOVER_BOTTOM});
    color: {c.BORDER_PRIMARY};
    border: 2px solid {c.BORDER_HOVER};
}}
QPushButton:pressed {{
    background-color: {c.BORDER_PRIMARY};
    color: {c.BG_DEEP};
    border: 2px solid {c.BORDER_HOVER};
    padding-left: 20px;
}}
QPushButton:disabled {{
    color: {c.TEXT_DIM};
    border: 2px solid {c.BORDER_BTN_DISABLED};
    background-color: {c.BG_BTN_BOTTOM};
}}
QPushButton[role="danger"] {{
    background-color: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 {c.GRADIENT_ALERT_BG_START}, stop:1 {c.GRADIENT_ALERT_BG_END});
    color: {c.TEXT_DANGER};
    border: 2px solid {c.BORDER_DANGER};
    border-radius: 6px;
    padding: 12px 16px;
    font-family: {f.FAMILY_BUTTON};
    font-size: {fs.BUTTON}pt;
    font-weight: bold;
    letter-spacing: 1px;
    text-align: left;
    padding-left: 16px;
}}
QPushButton[role="danger"]:hover {{
    background-color: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 {c.GRADIENT_ALERT_BG_HOVER_START}, stop:1 {c.GRADIENT_ALERT_BG_HOVER_END});
    color: {c.TEXT_DANGER_LIGHT};
    border: 2px solid {c.BORDER_DANGER_LIGHT};
}}
QPushButton[role="danger"]:pressed {{
    background-color: {c.BORDER_DANGER};
    color: {c.BG_DEEP};
    padding-left: 20px;
}}
"""


# ---- 垂直分组分割线（发光光柱） -------------------------------------------
def vline(t: DesignTokens) -> str:
    c = t.colors
    s = t.sizing
    return f"""
QFrame#vline {{
    background-color: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0   {c.GLOW_LIGHT_CYAN_LOW},
        stop:0.4 {c.GLOW_LIGHT_CYAN_MID},
        stop:0.5 {c.BORDER_HOVER},
        stop:0.6 {c.GLOW_LIGHT_CYAN_MID},
        stop:1   {c.GLOW_LIGHT_CYAN_LOW}
    );
    min-width: {s.VLINE_TOTAL_W}px;
    max-width: {s.VLINE_TOTAL_W}px;
    border: none;
    border-radius: 0px;
    margin-top: {s.VLINE_MARGIN}px;
    margin-bottom: {s.VLINE_MARGIN}px;
}}
QFrame#vline:hover {{
    background-color: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0   {c.GLOW_LIGHT_CYAN_LOW},
        stop:0.4 {c.GLOW_LIGHT_CYAN_HIGH},
        stop:0.5 {c.BORDER_HOVER},
        stop:0.6 {c.GLOW_LIGHT_CYAN_HIGH},
        stop:1   {c.GLOW_LIGHT_CYAN_LOW}
    );
}}
"""


# ---- 状态栏 -----------------------------------------------------------------
def status_bar(t: DesignTokens) -> str:
    c, fs = t.colors, t.font_sizes
    f = t.fonts
    return f"""
QStatusBar {{
    background-color: {c.BG_BASE};
    color: {c.TEXT_SECONDARY};
    border-top: 2px solid {c.BORDER_PRIMARY};
    font-family: {f.FAMILY_DATA};
    font-size: {fs.STATUSBAR}pt;
}}
QStatusBar::item {{
    border: none;
}}
QLabel#dcAlertLabel {{
    color: {c.TEXT_SECONDARY};
    padding-left: 10px;
}}
QLabel#dcAlertLabel[alert="warn"] {{
    color: {c.PROGRESS_CHUNK_WARNING};
}}
QLabel#dcAlertLabel[alert="error"] {{
    color: {c.TEXT_DANGER_LIGHT};
}}
QLabel#dcAlertLabel[alert="critical"] {{
    color: {c.TEXT_DANGER_LIGHT};
    font-weight: bold;
}}
"""


# ---- 右侧面板 ---------------------------------------------------------------
def right_panel(t: DesignTokens) -> str:
    c, fs = t.colors, t.font_sizes
    f = t.fonts
    return f"""
QWidget#rightPanel {{
    background-color: {c.BG_RIGHT_PANEL};
    border-left: 2px solid {c.BORDER_PRIMARY};
}}
QLabel#panelTitle {{
    color: {c.BORDER_PRIMARY};
    font-family: {f.FAMILY_MONO};
    font-size: {fs.PANEL_TITLE}pt;
    font-weight: bold;
    letter-spacing: 2px;
    background: transparent;
    padding: 6px 4px 10px 4px;
}}
QLabel#panelFooter {{
    color: {c.TEXT_DIM};
    font-family: {f.FAMILY_MONO};
    font-size: {fs.PANEL_FOOTER}pt;
    background: transparent;
    padding: 6px;
}}
"""


# ---- 批量控制段标题 ---------------------------------------------------------
def batch_section(t: DesignTokens) -> str:
    """段标题（"── 批量 ──"）和选中标签（双行：primary + secondary）。"""
    c, fs = t.colors, t.font_sizes
    f = t.fonts
    return f"""
QLabel#batchSectionTitle {{
    color: {c.TEXT_DIM};
    font-family: {f.FAMILY_MONO};
    font-size: 9pt;
    font-weight: bold;
    letter-spacing: 1px;
    background: transparent;
    padding: 8px 0 2px 0;
    border-top: 1px dashed {c.GLOW_LIGHT_CYAN_BORDER};
}}
QLabel#batchSectionTitle[danger="true"] {{
    color: {c.TEXT_DANGER};
    border-top-color: {c.GLOW_LIGHT_CYAN_ALERT};
}}
QLabel#panelSelection {{
    color: {c.BORDER_PRIMARY};
    font-family: {f.FAMILY_MONO};
    font-size: 11pt;
    font-weight: bold;
    background: transparent;
    padding: 2px 4px 6px 4px;
}}
QLabel#panelSelection[empty="true"] {{
    color: {c.TEXT_DIM};
    font-weight: normal;
    font-style: italic;
}}
QLabel#panelSelectionSecondary {{
    color: {c.TEXT_DIM};
    font-family: {f.FAMILY_MONO};
    font-size: 9pt;
    background: transparent;
    padding: 0 4px 4px 4px;
}}
QLabel#batchHelpText {{
    color: {c.TEXT_DIM};
    font-family: {f.FAMILY_MONO};
    font-size: 8pt;
    font-style: italic;
    background: transparent;
    padding: 2px 4px 4px 4px;
}}
"""


# ---- 详情页倒计时 -----------------------------------------------------------
def countdown(t: DesignTokens) -> str:
    c, fs = t.colors, t.font_sizes
    f, s = t.fonts, t.sizing
    return f"""
QFrame#countdownBox {{
    background-color: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 {c.BG_BTN_TOP}, stop:1 {c.BG_BTN_BOTTOM});
    border: 2px solid {c.BORDER_PRIMARY};
    border-radius: 10px;
}}
QLabel#countdownTitle {{
    color: {c.BORDER_PRIMARY};
    font-family: {f.FAMILY_TITLE};
    font-size: {fs.PANEL_TITLE}pt;
    font-weight: bold;
    letter-spacing: 2px;
    background: transparent;
    padding: 0 0 4px 0;
}}
QLabel#countdownBigTime {{
    color: {c.TEXT_COUNTDOWN_IDLE};
    font-family: {f.FAMILY_DATA};
    font-size: {fs.COUNTDOWN_BIG}pt;
    font-weight: bold;
    letter-spacing: 4px;
    background: transparent;
    padding: 0;
    qproperty-alignment: AlignCenter;
}}
QLabel#countdownBigTime[state="running"] {{
    color: {c.TEXT_COUNTDOWN_RUNNING};
}}
QLabel#countdownBigTime[state="warning"] {{
    color: {c.TEXT_COUNTDOWN_WARNING};
}}
QLabel#countdownBigTime[state="expired"] {{
    color: {c.TEXT_COUNTDOWN_EXPIRED};
}}
QLabel#countdownStatusText {{
    color: {c.TEXT_DIM};
    font-family: {f.FAMILY_MONO};
    font-size: {fs.COUNTDOWN_STATUS}pt;
    font-weight: bold;
    letter-spacing: 1px;
    background: transparent;
    padding: 0;
}}
QLabel#countdownStatusText[state="running"] {{
    color: {c.TEXT_COUNTDOWN_RUNNING};
}}
QLabel#countdownStatusText[state="warning"] {{
    color: {c.TEXT_COUNTDOWN_WARNING};
}}
QLabel#countdownStatusText[state="expired"] {{
    color: {c.TEXT_COUNTDOWN_EXPIRED};
}}
QLabel#countdownLabel {{
    color: {c.TEXT_SECONDARY};
    font-family: {f.FAMILY_MONO};
    font-size: {fs.COUNTDOWN_STATUS}pt;
    background: transparent;
}}
QSpinBox#countdownSpin {{
    background-color: {c.BG_DEEP};
    color: {c.TEXT_NEON_CYAN};
    border: 2px solid {c.BORDER_PRIMARY};
    border-radius: 6px;
    padding: 4px 12px;
    font-family: {f.FAMILY_DATA};
    font-size: 18pt;
    font-weight: bold;
    letter-spacing: 2px;
    selection-background-color: {c.BORDER_PRIMARY};
    selection-color: {c.BG_DEEP};
}}
QSpinBox#countdownSpin:hover {{
    border: 2px solid {c.BORDER_HOVER};
}}
QSpinBox#countdownSpin:focus {{
    border: 2px solid {c.BORDER_HOVER};
    background-color: {c.BG_TITLE_BAR};
}}
QSpinBox#countdownSpin:disabled {{
    color: {c.TEXT_DIM};
    border: 2px solid {c.BORDER_BTN_DISABLED};
    background-color: {c.BG_BTN_BOTTOM};
}}
QProgressBar#countdownProgress {{
    background-color: {c.PROGRESS_TRACK};
    border: 1px solid {c.BORDER_PRIMARY};
    border-radius: 4px;
    text-align: center;
    color: {c.TEXT_PRIMARY};
    min-height: {s.COUNTDOWN_PROGRESS_H}px;
    max-height: {s.COUNTDOWN_PROGRESS_H}px;
}}
QProgressBar#countdownProgress::chunk {{
    background-color: {c.PROGRESS_CHUNK_IDLE};
    border-radius: 3px;
}}
QProgressBar#countdownProgress[state="running"]::chunk {{
    background-color: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 {c.PROGRESS_CHUNK_RUNNING}, stop:1 {c.BORDER_HOVER});
}}
QProgressBar#countdownProgress[state="warning"]::chunk {{
    background-color: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 {c.PROGRESS_CHUNK_WARNING}, stop:1 {c.PROGRESS_CHUNK_WARNING_LIGHT});
}}
QProgressBar#countdownProgress[state="expired"]::chunk {{
    background-color: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 {c.PROGRESS_CHUNK_EXPIRED}, stop:1 {c.PROGRESS_CHUNK_EXPIRED_LIGHT});
}}
"""


# ============================================================================
# 顶部导航栏（TopNavBar / NavButton / navBrand / navVersion）
# ============================================================================
def nav_bar(t: DesignTokens) -> str:
    """顶部导航栏完整 QSS。

    视觉：60px 高，顶部 1px 高光 / 底部 1px 描边。
    品牌区 1px 右侧分隔线，nav 按钮 4 状态（default / hover / active / pressed）。
    """
    c = t.colors
    f = t.fonts
    return f"""
/* ---- 整体 nav 容器：上下细高光 + 暗色背景 ----------------------------- */
QWidget#topNavBar {{
    background-color: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 {c.BG_TITLE_BAR},
        stop:0.5 {c.BG_BASE},
        stop:1 {c.BG_DEEP});
    border-top: 1px solid {rgba(c.BORDER_PRIMARY, 60)};
    border-bottom: 1px solid {c.BORDER_PRIMARY};
}}

/* ---- 品牌区：左侧大写 + 1px 右侧分隔线 --------------------------------- */
QLabel#navBrand {{
    color: {c.TEXT_NEON_CYAN};
    font-family: {f.FAMILY_TITLE};
    font-size: 14pt;
    font-weight: bold;
    letter-spacing: 3px;
    background: transparent;
    padding: 0 24px 0 8px;
    border-right: 1px solid {rgba(c.BORDER_PRIMARY, 50)};
}}

QLabel#navVersion {{
    color: {c.TEXT_DIM};
    font-family: {f.FAMILY_MONO};
    font-size: 10pt;
    font-weight: bold;
    letter-spacing: 2px;
    background: transparent;
    padding: 0 16px;
}}

/* ---- Nav 按钮：默认态（透明 + 暗色文字）------------------------------- */
QPushButton#navButton {{
    background-color: transparent;
    color: {c.TEXT_SECONDARY};
    border: none;
    border-bottom: 2px solid transparent;
    border-radius: 0px;
    padding: 0 20px;
    min-height: 50px;
    font-family: {f.FAMILY_MONO};
    font-size: 12pt;
    font-weight: bold;
    letter-spacing: 1px;
    text-align: center;
}}

/* ---- Nav 按钮：hover 态（暗亮蓝背景 + 文字变亮）---------------------- */
QPushButton#navButton:hover {{
    background-color: {rgba(c.BORDER_PRIMARY, 25)};
    color: {c.TEXT_PRIMARY};
    border-bottom: 2px solid {rgba(c.TEXT_NEON_CYAN, 120)};
}}

/* ---- Nav 按钮：active 选中态（顶部到底色加深 + 底部亮青发光条）-------- */
QPushButton#navButton[active="true"] {{
    background-color: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 {rgba(c.BORDER_PRIMARY, 35)},
        stop:1 {rgba(c.BORDER_PRIMARY, 8)});
    color: {c.TEXT_NEON_CYAN};
    border-bottom: 2px solid {c.TEXT_NEON_CYAN};
}}

QPushButton#navButton[active="true"]:hover {{
    background-color: {rgba(c.BORDER_PRIMARY, 60)};
    color: {c.TEXT_NEON_CYAN};
    border-bottom: 2px solid {c.TEXT_NEON_CYAN};
}}

/* ---- Nav 按钮：pressed 态（短按下反馈）------------------------------- */
QPushButton#navButton:pressed {{
    background-color: {rgba(c.BORDER_PRIMARY, 80)};
    color: {c.BG_DEEP};
}}
"""


# ============================================================================
# 浮窗（floaterPanel + 4 种 side 边框色）
# ============================================================================
def floater(t: DesignTokens) -> str:
    """浮窗基础 + 4 种 side 边框色 QSS。

    通过 `QFrame#floaterPanel[side="xxx"]` 动态属性区分边框色。
    """
    c = t.colors
    f = t.fonts
    return f"""
/* ---- 浮窗基础：半透明深色 + 圆角 ----------------------------------- */
QFrame#floaterPanel {{
    background-color: {c.FLOATER_BG};
    border-radius: 8px;
}}

/* ---- 4 种 side 边框色（通过 dynamic property 切换）----------------- */
QFrame#floaterPanel[side="right"] {{
    border: 1px solid {c.FLOATER_BORDER_WARNING};
}}
QFrame#floaterPanel[side="bottomright"] {{
    border: 1px solid {c.FLOATER_BORDER_CYAN};
}}
QFrame#floaterPanel[side="ledstrip"] {{
    border: 1px solid {c.FLOATER_BORDER_RUNNING};
}}
QFrame#floaterPanel[side="neutral"] {{
    border: 1px solid {c.FLOATER_BORDER_NEUTRAL};
}}

/* ---- 浮窗标题（标题色随 side 变化）---------------------------------- */
QLabel#floaterTitle {{
    font-family: {f.FAMILY_MONO};
    font-size: 11pt;
    font-weight: bold;
    letter-spacing: 2px;
    background: transparent;
    padding: 0 0 4px 0;
}}
QFrame#floaterPanel[side="right"] QLabel#floaterTitle {{
    color: {c.FLOATER_BORDER_WARNING};
}}
QFrame#floaterPanel[side="bottomright"] QLabel#floaterTitle {{
    color: {c.FLOATER_BORDER_CYAN};
}}
QFrame#floaterPanel[side="ledstrip"] QLabel#floaterTitle {{
    color: {c.FLOATER_BORDER_RUNNING};
}}

/* ---- 浮窗主体（统一色）-------------------------------------------- */
QLabel#floaterBody {{
    color: {c.TEXT_PRIMARY};
    font-family: {f.FAMILY_MONO};
    font-size: 10pt;
    background: transparent;
    padding: 2px 0;
}}

/* ---- 浮窗强调文字（色随 side 变化）---------------------------------- */
QLabel#floaterAccent {{
    font-family: {f.FAMILY_DATA};
    font-size: 14pt;
    font-weight: bold;
    background: transparent;
    padding: 0;
}}
QFrame#floaterPanel[side="right"] QLabel#floaterAccent {{
    color: {c.TEXT_COUNTDOWN_WARNING};
}}
QFrame#floaterPanel[side="bottomright"] QLabel#floaterAccent {{
    color: {c.TEXT_NEON_CYAN};
}}
QFrame#floaterPanel[side="ledstrip"] QLabel#floaterAccent {{
    color: {c.TEXT_NEON_GREEN};
}}

/* ---- 浮窗提示（暗色斜体）---------------------------------------- */
QLabel#floaterHint {{
    color: {c.TEXT_DIM};
    font-family: {f.FAMILY_MONO};
    font-size: 8pt;
    font-style: italic;
    background: transparent;
    padding: 4px 0 0 0;
}}
"""


# ============================================================================
# 复位按钮（resetViewButton）
# ============================================================================
def reset_view_button(t: DesignTokens) -> str:
    """右上角"立即复位"按钮 QSS。"""
    c = t.colors
    f = t.fonts
    return f"""
QPushButton#resetViewButton {{
    background-color: {c.RESET_BTN_BG};
    color: {c.TEXT_DIM};
    border: 1px solid {c.RESET_BTN_BORDER};
    border-radius: 4px;
    font-family: {f.FAMILY_MONO};
    font-size: 9pt;
    font-weight: normal;
    padding: 0;
}}
QPushButton#resetViewButton:hover {{
    background-color: {c.RESET_BTN_BG_HOVER};
    color: {c.TEXT_NEON_CYAN};
    border: 1px solid {c.BORDER_PRIMARY};
}}
QPushButton#resetViewButton:pressed {{
    background-color: {c.BORDER_PRIMARY};
    color: {c.BG_DEEP};
}}
"""


# ---- 浮窗 LED 状态点（RightLEDStripFloater 内 72 个 dot，状态色动态切换） ----
# Phase 5 收口：把原本在 floaters.py 内的 3 处动态 setStyleSheet 迁到 QSS 属性选择器
#   - setObjectName("ledDot") + setProperty("ledState", "running")
#   - 此处根据 ledState 属性匹配不同颜色（无字面量）
def led_dot(t: DesignTokens) -> str:
    """浮窗 LED 状态点（按 ledState 属性动态着色）。"""
    from app.core.tokens import rgba_from_tuple
    c = t.colors
    return f"""
QLabel#ledDot {{
    color: {rgba_from_tuple(c.LED_OFFLINE, 0.6)};
    background: transparent;
}}
QLabel#ledDot[ledState="offline"] {{
    color: {rgba_from_tuple(c.LED_OFFLINE, 0.6)};
}}
QLabel#ledDot[ledState="running"] {{
    color: {rgba_from_tuple(c.LED_RUNNING, 0.95)};
}}
QLabel#ledDot[ledState="paused"] {{
    color: {rgba_from_tuple(c.LED_PAUSED, 0.95)};
}}
QLabel#ledDot[ledState="alert"] {{
    color: {rgba_from_tuple(c.LED_ALERT, 0.95)};
}}
QLabel#ledDot[ledState="warning"] {{
    color: {rgba_from_tuple(c.LED_WARNING, 0.95)};
}}
"""


# ---- 数据中心（Phase 6）-----------------------------------------------------
def data_center(t: DesignTokens) -> str:
    """数据中心页：页头横幅 + 自绘页签 + 标注工作区 + 工具条/页脚。"""
    c, fs = t.colors, t.font_sizes
    f, s = t.fonts, t.sizing
    return f"""
QWidget#dataCenterPage {{
    background-color: {c.BG_DEEP};
}}

/* ---- 顶栏：图标徽章 + 标题 + 副标题 + 状态指示 ------------------------ */
QFrame#dataHeader {{
    background-color: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 {rgba(c.BORDER_PRIMARY, 35)}, stop:0.6 {rgba(c.BORDER_PRIMARY, 8)}, stop:1 transparent);
    border-top: 1px solid {rgba(c.BORDER_PRIMARY, 60)};
    border-bottom: 1px solid {c.BORDER_PRIMARY};
    padding-left: 8px;
    padding-right: 12px;
}}
QLabel#dataHeaderBadge {{
    color: {c.BG_DEEP};
    background-color: {c.BORDER_PRIMARY};
    border: 1px solid {c.BORDER_PRIMARY};
    border-radius: 4px;
    font-family: {f.FAMILY_TITLE};
    font-size: 11pt;
    font-weight: bold;
    padding: 2px 10px;
    min-width: 28px;
    max-width: 36px;
}}
QLabel#dataHeaderTitle {{
    color: {c.TEXT_NEON_CYAN};
    font-family: {f.FAMILY_TITLE};
    font-size: 16pt;
    font-weight: bold;
    letter-spacing: 4px;
    background: transparent;
}}
QLabel#dataHeaderSubtitle {{
    color: {c.TEXT_SECONDARY};
    font-family: {f.FAMILY_MONO};
    font-size: 9pt;
    letter-spacing: 1px;
    background: transparent;
}}
QLabel#dataHeaderStatus {{
    color: {c.BORDER_PRIMARY};
    font-family: {f.FAMILY_MONO};
    font-size: 9pt;
    font-weight: bold;
    letter-spacing: 1px;
    padding: 3px 10px;
    border: 1px solid {c.BORDER_PRIMARY};
    border-radius: 3px;
    background-color: {rgba(c.BORDER_PRIMARY, 12)};
}}
QWidget#dataHeaderTitleWrap {{
    background: transparent;
}}

/* ---- 自绘页签（QPushButton + property） ------------------------------ */
QFrame#dataTabsBar {{
    background-color: {c.BG_DEEP};
    border-bottom: 1px solid {c.BORDER_PRIMARY};
    padding-left: 8px;
    padding-right: 8px;
}}
QPushButton#dataTab {{
    background-color: transparent;
    color: {c.TEXT_SECONDARY};
    border: none;
    border-bottom: 2px solid transparent;
    padding: 8px 18px;
    font-family: {f.FAMILY_MONO};
    font-size: 10pt;
    font-weight: bold;
    letter-spacing: 2px;
    min-width: 120px;
}}
QPushButton#dataTab:hover {{
    color: {c.TEXT_PRIMARY};
    background-color: {rgba(c.BORDER_PRIMARY, 12)};
}}
QPushButton#dataTab:checked {{
    color: {c.TEXT_NEON_CYAN};
    border-bottom: 2px solid {c.TEXT_NEON_CYAN};
    background-color: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 {rgba(c.BORDER_PRIMARY, 30)}, stop:1 transparent);
}}
QStackedWidget#dataStack {{
    background-color: {c.BG_DEEP};
    border: none;
}}
QWidget#dcCanvasOuter {{
    background: transparent;
}}
QWidget#dcCanvasCenter {{
    background: transparent;
}}
QLabel#dcFooterTitle {{
    color: {c.TEXT_NEON_CYAN};
    font-family: {f.FAMILY_TITLE};
    font-size: 11pt;
    font-weight: bold;
    letter-spacing: 2px;
    background: transparent;
    padding: 0;
}}

/* ---- 标注页 · 类别工具条 -------------------------------------------- */
QFrame#dcCategoryBar {{
    background-color: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 {c.BG_BTN_BOTTOM}, stop:1 {c.BG_DEEP});
    border: 1px solid {c.BORDER_PRIMARY};
    border-radius: 4px;
    padding: 6px 10px;
}}
QLabel#dcBarLabel {{
    color: {c.BORDER_PRIMARY};
    font-family: {f.FAMILY_MONO};
    font-size: 9pt;
    font-weight: bold;
    letter-spacing: 2px;
    background: transparent;
}}
QLabel#dcChip {{
    background-color: {rgba(c.BORDER_PRIMARY, 18)};
    color: {c.TEXT_NEON_CYAN};
    border: 1px solid {c.BORDER_PRIMARY};
    border-radius: 12px;
    padding: 3px 12px;
    font-family: {f.FAMILY_MONO};
    font-size: 9pt;
    font-weight: bold;
    letter-spacing: 1px;
}}
QLabel#dcChipAdd {{
    background-color: transparent;
    color: {c.TEXT_SECONDARY};
    border: 1px dashed {c.BORDER_PRIMARY};
    border-radius: 12px;
    padding: 3px 12px;
    font-family: {f.FAMILY_MONO};
    font-size: 9pt;
    font-weight: bold;
    letter-spacing: 1px;
}}
QPushButton#dcChipAdd {{
    background-color: transparent;
    color: {c.TEXT_SECONDARY};
    border: 1px dashed {c.BORDER_PRIMARY};
    border-radius: 12px;
    padding: 3px 12px;
    font-family: {f.FAMILY_MONO};
    font-size: 9pt;
    font-weight: bold;
    letter-spacing: 1px;
}}
QPushButton#dcChipAdd:hover {{
    background-color: {rgba(c.BORDER_PRIMARY, 25)};
    color: {c.TEXT_NEON_CYAN};
    border: 1px solid {c.BORDER_HOVER};
}}
QPushButton#dcChipAdd:pressed {{
    background-color: {rgba(c.BORDER_PRIMARY, 40)};
}}
QPushButton#dcChipBtn {{
    background-color: {rgba(c.BORDER_PRIMARY, 18)};
    color: {c.TEXT_NEON_CYAN};
    border: 1px solid {rgba(c.BORDER_PRIMARY, 60)};
    border-radius: 12px;
    padding: 3px 12px;
    font-family: {f.FAMILY_MONO};
    font-size: 9pt;
    font-weight: bold;
    letter-spacing: 1px;
}}
QPushButton#dcChipBtn:hover {{
    background-color: {rgba(c.BORDER_PRIMARY, 35)};
    border: 1px solid {c.BORDER_HOVER};
}}
QPushButton#dcChipBtn:checked {{
    background-color: {c.BORDER_PRIMARY};
    color: {c.BG_DEEP};
    border: 1px solid {c.BORDER_HOVER};
}}
QPushButton#dcGhostBtn {{
    background-color: {c.BG_BTN_BOTTOM};
    color: {c.TEXT_PRIMARY};
    border: 1px solid {c.BORDER_PRIMARY};
    border-radius: 4px;
    padding: 4px 12px;
    font-family: {f.FAMILY_BUTTON};
    font-size: 9pt;
    font-weight: bold;
    min-width: 72px;
}}
QPushButton#dcGhostBtn:hover {{
    background-color: {c.BG_BTN_HOVER_TOP};
    color: {c.BORDER_HOVER};
    border: 1px solid {c.BORDER_HOVER};
}}
QPushButton#dcGhostBtn:pressed {{
    background-color: {c.BORDER_PRIMARY};
    color: {c.BG_DEEP};
}}

/* ---- 标注页 · 工作区分隔 --------------------------------------------- */
QSplitter#dataSplitter {{
    background-color: {c.BG_DEEP};
}}
QSplitter#dataSplitter::handle {{
    background-color: {rgba(c.BORDER_PRIMARY, 50)};
}}
QSplitter#dataSplitter::handle:horizontal {{
    width: 2px;
}}

/* ---- 侧栏：图片列表 + 导航 ------------------------------------------ */
QFrame#dcSidePanel {{
    background-color: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 {c.BG_RIGHT_PANEL}, stop:1 {c.BG_DEEP});
    border: 1px solid {c.BORDER_PRIMARY};
    border-radius: 4px;
}}
QLabel#dcPanelTitle {{
    color: {c.TEXT_NEON_CYAN};
    font-family: {f.FAMILY_TITLE};
    font-size: 12pt;
    font-weight: bold;
    letter-spacing: 2px;
    background: transparent;
    padding: 4px 2px 8px 2px;
    border-bottom: 1px dashed {rgba(c.BORDER_PRIMARY, 50)};
}}
QListWidget#dcList {{
    background-color: transparent;
    color: {c.TEXT_PRIMARY};
    border: none;
    font-family: {f.FAMILY_MONO};
    font-size: 10pt;
    padding: 4px 2px;
    outline: none;
}}
QListWidget#dcList::item {{
    padding: 6px 10px;
    border-radius: 3px;
    border-left: 2px solid transparent;
}}
QListWidget#dcList::item:hover {{
    background-color: {rgba(c.BORDER_PRIMARY, 18)};
    color: {c.TEXT_PRIMARY};
}}
QListWidget#dcList::item:selected {{
    background-color: {rgba(c.BORDER_PRIMARY, 35)};
    color: {c.TEXT_NEON_CYAN};
    border-left: 2px solid {c.TEXT_NEON_CYAN};
}}

/* ---- 标注画布 ----------------------------------------------------- */
QFrame#dcCanvas {{
    background-color: {c.BG_BASE};
    border: 1px solid {c.BORDER_PRIMARY};
    border-radius: 4px;
}}
QLabel#dcCanvasCorner {{
    color: {c.BORDER_PRIMARY};
    font-family: {f.FAMILY_MONO};
    font-size: 8pt;
    font-weight: bold;
    letter-spacing: 1px;
    background: transparent;
}}
QLabel#dcCanvasHint {{
    color: {c.TEXT_DIM};
    font-family: {f.FAMILY_MONO};
    font-size: 12pt;
    font-style: italic;
    background: transparent;
}}
QLabel#dcCanvasHintAccent {{
    color: {c.BORDER_PRIMARY};
    font-family: {f.FAMILY_MONO};
    font-size: 10pt;
    font-weight: bold;
    letter-spacing: 2px;
    background: transparent;
}}

/* ---- 缩放控制条按钮 / 百分比 -------------------------------------- */
QPushButton#dcZoomBtn {{
    background-color: {c.BG_BTN_BOTTOM};
    color: {c.TEXT_PRIMARY};
    border: 1px solid {rgba(c.BORDER_PRIMARY, 60)};
    border-radius: 3px;
    padding: 0;
    min-width: {s.ANNOT_ZOOM_BTN_W}px;
    max-width: {s.ANNOT_ZOOM_BTN_W}px;
    min-height: {s.ANNOT_ZOOM_BTN_H}px;
    max-height: {s.ANNOT_ZOOM_BTN_H}px;
    font-family: {f.FAMILY_MONO};
    font-size: 9pt;
    font-weight: bold;
}}
QPushButton#dcZoomBtn:hover {{
    background-color: {c.BG_BTN_HOVER_TOP};
    color: {c.BORDER_HOVER};
    border: 1px solid {c.BORDER_HOVER};
}}
QPushButton#dcZoomBtn:pressed {{
    background-color: {c.BORDER_PRIMARY};
    color: {c.BG_DEEP};
}}
QLabel#dcZoomPct {{
    color: {c.TEXT_NEON_CYAN};
    font-family: {f.FAMILY_DATA};
    font-size: 9pt;
    font-weight: bold;
    background: transparent;
    min-width: {s.ANNOT_ZOOM_PCT_W}px;
    text-align: center;
}}

/* ---- 底部 · 对象列表 + 操作栏 ------------------------------------ */
QFrame#dcFooter {{
    background-color: {c.BG_BTN_BOTTOM};
    border: 1px solid {c.BORDER_PRIMARY};
    border-radius: 4px;
    padding: 8px 10px;
}}
QListWidget#dcObjectList {{
    background-color: transparent;
    color: {c.TEXT_SECONDARY};
    border: none;
    font-family: {f.FAMILY_MONO};
    font-size: 9pt;
    padding: 0;
    outline: none;
}}
QPushButton#dcPrimaryBtn {{
    background-color: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 {c.BG_BTN_TOP}, stop:1 {c.BG_BTN_BOTTOM});
    color: {c.TEXT_NEON_CYAN};
    border: 1px solid {c.BORDER_PRIMARY};
    border-radius: 4px;
    padding: 6px 18px;
    font-family: {f.FAMILY_BUTTON};
    font-size: 10pt;
    font-weight: bold;
    letter-spacing: 1px;
    min-width: 96px;
}}
QPushButton#dcPrimaryBtn:hover {{
    background-color: {c.BG_BTN_HOVER_TOP};
    border: 1px solid {c.BORDER_HOVER};
}}
QPushButton#dcPrimaryBtn:pressed {{
    background-color: {c.BORDER_PRIMARY};
    color: {c.BG_DEEP};
}}

/* ---- 训练页 · 高级下拉按钮（视觉与 ghost 一致，避免"白板"）--------- */
QToolButton#dcGhostBtn {{
    background-color: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 {c.BG_BTN_TOP}, stop:1 {c.BG_BTN_BOTTOM});
    color: {c.TEXT_NEON_CYAN};
    border: 1px solid {c.BORDER_PRIMARY};
    border-radius: 4px;
    padding: 6px 14px;
    font-family: {f.FAMILY_BUTTON};
    font-size: 9pt;
    font-weight: bold;
    letter-spacing: 1px;
}}
QToolButton#dcGhostBtn:hover {{
    background-color: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 {c.BG_BTN_HOVER_TOP}, stop:1 {c.BG_BTN_HOVER_BOTTOM});
    border: 1px solid {c.BORDER_HOVER};
    color: {c.BORDER_HOVER};
}}
QToolButton#dcGhostBtn:pressed {{
    background-color: {c.BG_TITLE_BAR};
    color: {c.BORDER_PRIMARY};
}}
QMenu {{
    background-color: {c.BG_DEEP};
    color: {c.TEXT_NEON_CYAN};
    border: 1px solid {c.BORDER_PRIMARY};
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 24px;
    border-radius: 2px;
}}
QMenu::item:selected {{
    background-color: {c.BG_TITLE_BAR};
    color: {c.BORDER_HOVER};
}}
QMenu::separator {{
    height: 1px;
    background: {c.BORDER_PRIMARY};
    margin: 4px 8px;
}}

/* ---- 历史 / 训练 页占位 ------------------------------------------ */
QLabel#dcTabPlaceholder {{
    color: {c.TEXT_DIM};
    font-family: {f.FAMILY_MONO};
    font-size: 12pt;
    font-style: italic;
    background: transparent;
}}
QLabel#dcTabPlaceholderAccent {{
    color: {c.BORDER_PRIMARY};
    font-family: {f.FAMILY_MONO};
    font-size: 10pt;
    font-weight: bold;
    letter-spacing: 2px;
    background: transparent;
}}

/* ---- 训练页 · 概览横幅 -------------------------------------------- */
QLabel#dcTrainOverview {{
    color: {c.TEXT_SECONDARY};
    font-family: {f.FAMILY_MONO};
    font-size: 9pt;
    background: transparent;
    padding: 2px 4px;
}}

/* ---- 训练页 · 分段卡片 ------------------------------------------- */
QFrame#dcTrainSection {{
    background-color: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 {c.BG_RIGHT_PANEL}, stop:1 {c.BG_DEEP});
    border: 1px solid {c.BORDER_PRIMARY};
    border-radius: 4px;
}}
QLabel#dcTrainSectionTitle {{
    color: {c.TEXT_NEON_CYAN};
    font-family: {f.FAMILY_TITLE};
    font-size: 11pt;
    font-weight: bold;
    letter-spacing: 2px;
    background: transparent;
    padding: 2px 2px 6px 2px;
    border-bottom: 1px dashed {rgba(c.BORDER_PRIMARY, 50)};
}}
QLabel#dcTrainParamLabel {{
    color: {c.TEXT_SECONDARY};
    font-family: {f.FAMILY_MONO};
    font-size: 8pt;
    background: transparent;
}}

/* ---- 训练页 · 日志区 -------------------------------------------- */
QPlainTextEdit#dcTrainLog {{
    background-color: {c.BG_BASE};
    color: {c.TEXT_PRIMARY};
    border: 1px solid {c.BORDER_PRIMARY};
    border-radius: 4px;
    font-family: {f.FAMILY_MONO};
    font-size: 9pt;
    padding: 6px;
    selection-background-color: {rgba(c.BORDER_PRIMARY, 40)};
}}
QPlainTextEdit#dcTrainLog:disabled {{
    color: {c.TEXT_DIM};
}}

/* ---- 训练页 · 状态行 --------------------------------------------- */
QLabel#dcTrainHint {{
    color: {c.TEXT_DIM};
    font-family: {f.FAMILY_MONO};
    font-size: 8pt;
    font-style: italic;
    background: transparent;
}}
QLabel#dcTrainHint[running="true"] {{
    color: {c.TEXT_NEON_GREEN};
    font-style: normal;
    font-weight: bold;
}}
QLabel#dcTrainHint[state="fail"] {{
    color: {c.TEXT_DANGER};
    font-style: normal;
    font-weight: bold;
}}

/* ---- 训练页 · 状态区（深度优化） ------------------------------------- */
QFrame#dcTrainStatusSection {{
    background-color: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 {c.BG_RIGHT_PANEL}, stop:1 {c.BG_DEEP});
    border: 1px solid {c.BORDER_PRIMARY};
    border-radius: 4px;
}}
QLabel#dcTrainStatusLabel {{
    color: {c.TEXT_SECONDARY};
    font-family: {f.FAMILY_MONO};
    font-size: 8pt;
    background: transparent;
}}
QLabel#dcTrainStageLabel {{
    color: {c.TEXT_NEON_CYAN};
    font-family: {f.FAMILY_MONO};
    font-size: 9pt;
    font-weight: bold;
    background: transparent;
}}
QLabel#dcTrainMetricsLabel {{
    color: {c.TEXT_NEON_GREEN};
    font-family: {f.FAMILY_MONO};
    font-size: 9pt;
    background: transparent;
}}
QProgressBar#dcTrainProgress {{
    background-color: {c.PROGRESS_TRACK};
    border: 1px solid {c.BORDER_PRIMARY};
    border-radius: 3px;
    text-align: center;
    color: {c.TEXT_PRIMARY};
    font-family: {f.FAMILY_MONO};
    font-size: 8pt;
}}
QProgressBar#dcTrainProgress::chunk {{
    background-color: {c.PROGRESS_CHUNK_RUNNING};
    border-radius: 2px;
}}
"""


# ---- 视频检测页（总览 + 单通道视频流） ------------------------------------
def video_page(t: DesignTokens) -> str:
    """视频总览（位点标记） + 视频流检测页。"""
    c, fs, f, s = t.colors, t.font_sizes, t.fonts, t.sizing
    return f"""
/* ---- 视频总览：位点标记 ---- */
QWidget#videoPage {{
    background-color: {c.BG_DEEP};
}}

QFrame#videoToolbar {{
    background-color: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 {c.BG_TITLE_BAR}, stop:1 {c.BG_DEEP});
    border-bottom: 1px solid {c.BORDER_PRIMARY};
    border-top: 1px solid {rgba(c.BORDER_PRIMARY, 40)};
}}

QLabel#videoTitle {{
    color: {c.TEXT_NEON_CYAN};
    font-family: {f.FAMILY_TITLE};
    font-size: 14pt;
    font-weight: bold;
    letter-spacing: 2px;
    background: transparent;
}}

QLabel#videoInfo {{
    color: {c.TEXT_DIM};
    font-family: {f.FAMILY_MONO};
    font-size: 10pt;
    background: transparent;
}}

QFrame#videoCell {{
    background-color: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 {c.BG_CELL_TOP}, stop:1 {c.BG_CELL_BOTTOM});
    border: 1px solid {c.BORDER_OFFLINE};
    border-radius: {s.RADIUS_CELL}px;
}}
QFrame#videoCell:hover {{
    border-color: {c.BORDER_HOVER};
}}
QFrame#videoCell:selected {{
    border-color: {c.BORDER_SELECTED};
}}

QLabel#videoCellHeader {{
    color: {c.TEXT_NEON_CYAN};
    font-family: {f.FAMILY_MONO};
    font-size: {fs.CELL_ID}pt;
    font-weight: bold;
    background: transparent;
}}

QLabel#videoCellMark {{
    color: {c.TEXT_SECONDARY};
    font-family: {f.FAMILY_MONO};
    font-size: {fs.MD}pt;
    background: transparent;
}}

QLabel#videoCellHint {{
    color: {c.TEXT_DIM};
    font-family: {f.FAMILY_MONO};
    font-size: {fs.XS}pt;
    background: transparent;
}}

/* ---- 视频流检测页：单通道 ---- */
QWidget#videoStreamPage {{
    background-color: {c.BG_DEEP};
}}

QFrame#vsToolbar {{
    background-color: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 {c.BG_TITLE_BAR}, stop:1 {c.BG_DEEP});
    border-bottom: 1px solid {c.BORDER_PRIMARY};
    border-top: 1px solid {rgba(c.BORDER_PRIMARY, 40)};
}}

QPushButton#vsBack {{
    color: {c.TEXT_SECONDARY};
    border: 1px solid {c.BORDER_DARK_BLUE};
    border-radius: {s.RADIUS_MD}px;
    padding: 5px 14px;
    font-family: {f.FAMILY_MONO};
    font-size: {fs.MD}pt;
    background-color: transparent;
}}
QPushButton#vsBack:hover {{
    color: {c.TEXT_NEON_CYAN};
    border-color: {c.BORDER_PRIMARY};
}}

QLabel#vsTitle {{
    color: {c.TEXT_NEON_GREEN};
    font-family: {f.FAMILY_TITLE};
    font-size: 14pt;
    font-weight: bold;
    background: transparent;
}}

QFrame#vsLive, QFrame#vsStatsPanel {{
    background-color: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 {c.BG_CELL_TOP}, stop:1 {c.BG_CELL_BOTTOM});
    border: 1px solid {c.BORDER_DARK_BLUE};
    border-radius: {s.RADIUS_LG}px;
}}

QLabel#vsPanelTitle {{
    color: {c.TEXT_SECONDARY};
    font-family: {f.FAMILY_MONO};
    font-size: {fs.MD}pt;
    font-weight: bold;
    background: transparent;
}}

QLabel#vsVideo {{
    color: {c.TEXT_DIM};
    background-color: {c.BG_DEEP};
    border: 1px solid {c.BORDER_OFFLINE};
    border-radius: {s.VIDEO_THUMB_CORN_RADIUS}px;
    font-family: {f.FAMILY_MONO};
    font-size: {fs.XS}pt;
}}

QLabel#vsStats {{
    color: {c.TEXT_SECONDARY};
    font-family: {f.FAMILY_MONO};
    font-size: {fs.XS}pt;
    background: transparent;
}}

/* 检测结果面板：VPL / CPL / PWR 三条闪烁折线图 */
QWidget#vsResult {{
    background: transparent;
}}

QLabel#vsEmpty {{
    color: {c.TEXT_DIM};
    font-family: {f.FAMILY_MONO};
    font-size: {fs.XS}pt;
    background: transparent;
}}

QLabel#vsSectionTitle {{
    color: {c.TEXT_SECONDARY};
    font-family: {f.FAMILY_MONO};
    font-size: {fs.XS}pt;
    font-weight: bold;
    letter-spacing: 1px;
    background: transparent;
}}
"""
