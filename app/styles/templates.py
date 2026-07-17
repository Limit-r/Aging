"""QSS 模板（按 widget 分块）。

每个模板函数接收一个 `DesignTokens` 实例，返回一段 QSS 字符串。
模板**不**包含任何裸 hex / 字号 / 字体名——所有视觉量从 `tokens` 读取。
"""

from app.core.tokens import DesignTokens


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
    border-top: 1px solid rgba(0, 191, 255, 40);
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
    background-color: rgba(0, 191, 255, 50);
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
    border-bottom: 1px dashed rgba(0, 191, 255, 50);
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
    border-top: 1px dashed rgba(0, 191, 255, 30);
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
    background-color: rgba(0, 191, 255, 30);
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
    background-color: rgba(10, 15, 28, 220);
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
        stop:0 rgba(16, 255, 161, 90), stop:1 rgba(16, 200, 130, 70));
}}
QWidget#dataCell[expired_pending="off"] {{
    border: 2px solid rgba(16, 255, 161, 110);
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
        stop:0 rgba(80, 18, 36, 200), stop:1 rgba(40, 8, 18, 200));
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
        stop:0 rgba(120, 30, 50, 220), stop:1 rgba(60, 12, 24, 220));
    color: #ffd0d8;
    border: 2px solid #ff5a78;
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
        stop:0   rgba(74, 217, 255, 0),
        stop:0.4 rgba(74, 217, 255, 80),
        stop:0.5 {c.BORDER_HOVER},
        stop:0.6 rgba(74, 217, 255, 80),
        stop:1   rgba(74, 217, 255, 0)
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
        stop:0   rgba(74, 217, 255, 0),
        stop:0.4 rgba(74, 217, 255, 140),
        stop:0.5 {c.BORDER_HOVER},
        stop:0.6 rgba(74, 217, 255, 140),
        stop:1   rgba(74, 217, 255, 0)
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
    border-top: 1px dashed rgba(74, 217, 255, 60);
}}
QLabel#batchSectionTitle[danger="true"] {{
    color: {c.TEXT_DANGER};
    border-top-color: rgba(255, 59, 92, 100);
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
        stop:0 {c.PROGRESS_CHUNK_WARNING}, stop:1 #ffd166);
}}
QProgressBar#countdownProgress[state="expired"]::chunk {{
    background-color: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 {c.PROGRESS_CHUNK_EXPIRED}, stop:1 #ff7090);
}}
"""
