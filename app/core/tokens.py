"""设计 token：所有 UI 视觉常量的单一来源。

四类：
- Colors：色板（背景/边框/文本/告警/状态）
- Fonts：字体族
- FontSizes：字号（pt）
- Sizing：圆角、边框宽度、最小尺寸

所有 dataclass `frozen=True`，运行时不可变。QSS 模板通过 f-string 引用。
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Colors:
    # ---- 背景：深色系（主窗口/单元/面板） --------------------------------
    BG_DEEP: str = "#04060d"
    BG_BASE: str = "#0a0f1c"
    BG_MID: str = "#060a18"
    BG_DEEP_GRAD_INNER: str = "#0a1530"
    BG_DEEP_GRAD_OUTER: str = "#02040a"
    BG_RIGHT_PANEL: str = "#050810"
    BG_CELL_TOP: str = "#142850"
    BG_CELL_BOTTOM: str = "#0a1530"
    BG_CELL_ALERT_TOP: str = "#2a0a18"
    BG_CELL_ALERT_BOTTOM: str = "#1a0810"
    BG_CELL_NO_DATA_TOP: str = "#1a1a1a"     # 灰黑：上下渐变
    BG_CELL_NO_DATA_BOTTOM: str = "#0a0a0a"
    BG_BTN_TOP: str = "#131c33"
    BG_BTN_BOTTOM: str = "#0a0f1c"
    BG_BTN_HOVER_TOP: str = "#1a2542"
    BG_BTN_HOVER_BOTTOM: str = "#0f1729"
    BG_TITLE_BAR: str = "#0a0f1c"

    # ---- 背景：浅色系（数据网格/数据点，参考图二） -------------------------
    BG_DATAGRID: str = "#cfe2f3"          # 浅蓝
    BG_DATAGRID_NO_DATA: str = "#161616"   # 无数据态深灰
    BG_DATAPOINT: str = "#ffffff"          # 白
    BG_DATAPOINT_ALERT: str = "#ffe0e6"    # 浅红

    # ---- 霓虹强调色（径向渐变光晕） ----------------------------------------
    GLOW_CYAN: str = "rgba(0, 191, 255, 30)"
    GLOW_PURPLE: str = "rgba(120, 80, 200, 30)"

    # ---- 边框 -------------------------------------------------------------
    BORDER_PRIMARY: str = "#00bfff"        # 亮蓝青
    BORDER_HOVER: str = "#00ffff"          # 亮青
    BORDER_DANGER: str = "#ff3b5c"         # 红
    BORDER_OFFLINE: str = "#3d4a66"
    BORDER_DARK_BLUE: str = "#1a4d8c"      # 深蓝（数据点）
    BORDER_NO_DATA: str = "#3a3a3a"
    BORDER_BTN_DISABLED: str = "#1a2542"
    # ---- 选中专用（高对比度，让用户一眼看出当前选区） ---------------------
    BORDER_SELECTED: str = "#00ffff"        # 选中（亮青，比 PRIMARY 更亮）
    BORDER_SELECTED_NODATA: str = "#cccccc"  # 选中 + NO_DATA（亮灰，区别于 BORDER_NO_DATA #3a3a3a）
    BORDER_SELECTED_ANOMALY: str = "#ff3b5c" # 选中 + 异常（亮红）

    # ---- 文本 -------------------------------------------------------------
    TEXT_PRIMARY: str = "#e2e8f0"
    TEXT_SECONDARY: str = "#7a8ba8"
    TEXT_DIM: str = "#3d4a66"
    TEXT_VALUE: str = "#0a1f3d"            # 深蓝（白底数字）
    TEXT_LABEL: str = "#1a4d8c"            # 深蓝（标签/单位）
    TEXT_DANGER: str = "#c01838"
    TEXT_NEON_CYAN: str = "#00e5ff"
    TEXT_NEON_GREEN: str = "#10ffa1"
    TEXT_NO_DATA: str = "#666666"           # NO_DATA 状态文字灰色
    TEXT_NO_DATA_VALUE: str = "#555555"     # NO_DATA 数字占位色
    TEXT_COUNTDOWN_IDLE: str = "#5a6b88"    # 倒计时未启动（暗蓝）
    TEXT_COUNTDOWN_RUNNING: str = "#00e5ff" # 倒计时运行中（霓虹青）
    TEXT_COUNTDOWN_WARNING: str = "#ffae42" # 倒计时 < 60s 警告（橙）
    TEXT_COUNTDOWN_EXPIRED: str = "#ff3b5c" # 倒计时归零（红）
    PROGRESS_TRACK: str = "#0f1a30"        # 进度条轨道
    PROGRESS_CHUNK_IDLE: str = "#1a2542"    # 进度条未启动
    PROGRESS_CHUNK_RUNNING: str = "#00bfff" # 进度条运行中
    PROGRESS_CHUNK_WARNING: str = "#ffae42" # 进度条 < 60s
    PROGRESS_CHUNK_EXPIRED: str = "#ff3b5c" # 进度条已结束

    # ---- 3D 机柜视图（GLViewWidget 不走 QSS，颜色直接用 RGB tuple）----------
    # 这些是给 pyqtgraph OpenGL 用的（不是 QSS），RGB int 0-255
    RACK_3D_BG: tuple = (4, 6, 13)              # 与 BG_DEEP 同步（深空黑）
    RACK_3D_GRID: tuple = (40, 60, 100)         # 网格线（暗蓝）
    RACK_3D_PANEL: tuple = (20, 30, 50)         # 机柜面板底色
    RACK_3D_PANEL_EDGE: tuple = (60, 90, 140)   # 机柜边框
    RACK_3D_LABEL: tuple = (180, 200, 230)      # 通道号文字（淡蓝白）
    # LED 状态色：RGBA tuple (r, g, b, a)
    LED_OFFLINE: tuple = (60, 70, 90, 180)      # 暗灰蓝
    LED_RUNNING: tuple = (16, 255, 161, 255)    # 霓虹绿
    LED_PAUSED: tuple = (0, 229, 255, 220)      # 霓虹青
    LED_ALERT: tuple = (255, 59, 92, 255)       # 霓虹红
    LED_WARNING: tuple = (255, 174, 66, 255)    # 警告橙（≤60s）
    LED_SELECTED: tuple = (255, 255, 255, 255)  # 选中态白（叠加层）
    LED_HOVER: tuple = (200, 220, 255, 200)     # hover 高亮

    # ---- 数据标注 · 画框调色板（QGraphicsView 直接用于 QColor，RGB tuple）----
    # 类别 → 框色循环映射，让不同标注类在图片上可区分
    ANNOT_BOX_PALETTE: tuple = (
        (0, 191, 255),      # 亮蓝青（区域框主色）
        (16, 255, 161),     # 霓虹绿
        (255, 174, 66),     # 警告橙
        (167, 139, 250),    # 紫
        (255, 59, 92),      # 霓虹红
        (0, 229, 255),      # 霓虹青
        (255, 255, 255),    # 白
    )
    ANNOT_BOX_SELECTED: tuple = (255, 255, 255)   # 选中框描边（白）

    # ---- 浅色变体（深色背景下的浅色文字/边框/渐变末端）--------------------
    # Phase 4-A：从 templates.py 抽离的 4 个裸 hex 角色色
    TEXT_DANGER_LIGHT: str = "#ffd0d8"           # 危险态浅色（深色背景下红按钮 hover 文字）
    BORDER_DANGER_LIGHT: str = "#ff5a78"         # 危险态浅边框（danger 按钮 hover 边框）
    PROGRESS_CHUNK_WARNING_LIGHT: str = "#ffd166" # 警告渐变末端（warning 进度条高亮段尾）
    PROGRESS_CHUNK_EXPIRED_LIGHT: str = "#ff7090" # 归零渐变末端（expired 进度条高亮段尾）

    # ---- 渐变半透明色（用于 qlineargradient 端点）-------------------------
    # Phase 4-A：从 templates.py 抽离的 rgba 字面量
    GRADIENT_RUNNING_START: str = "rgba(16, 255, 161, 90)"   # 运行态渐变起（绿）
    GRADIENT_RUNNING_END: str = "rgba(16, 200, 130, 70)"     # 运行态渐变末（深绿）
    GRADIENT_RUNNING_BORDER: str = "rgba(16, 255, 161, 110)" # 运行态边框（绿半透明）
    GRADIENT_ALERT_BG_START: str = "rgba(80, 18, 36, 200)"   # 告警背景渐变起（深红）
    GRADIENT_ALERT_BG_END: str = "rgba(40, 8, 18, 200)"      # 告警背景渐变末（更深红）
    GRADIENT_ALERT_BG_HOVER_START: str = "rgba(120, 30, 50, 220)"  # 告警 hover 起
    GRADIENT_ALERT_BG_HOVER_END: str = "rgba(60, 12, 24, 220)"     # 告警 hover 末

    # ---- 光晕蓝（74,217,255 多 alpha 复用）--------------------------------
    # 用于垂直分割线 / 批量段标题 / 边框等需要"淡淡发光蓝"的场景
    GLOW_LIGHT_CYAN_LOW: str = "rgba(74, 217, 255, 0)"     # 渐变两端透明
    GLOW_LIGHT_CYAN_MID: str = "rgba(74, 217, 255, 80)"    # 渐变中段
    GLOW_LIGHT_CYAN_HIGH: str = "rgba(74, 217, 255, 140)"  # hover 中段
    GLOW_LIGHT_CYAN_BORDER: str = "rgba(74, 217, 255, 60)" # 边框
    GLOW_LIGHT_CYAN_ALERT: str = "rgba(255, 59, 92, 100)"  # 告警叠加（注意：实际是红色系，命名沿用方案）
    # ---- 浮窗（nav_bar / floaters 共用）------------------------------------
    # 半透明深色背景（10,15,28 = BG_BASE，alpha 200）
    FLOATER_BG: str = "rgba(10, 15, 28, 200)"
    # 4 种边框色（按 side 区分）
    FLOATER_BORDER_WARNING: str = "rgba(255, 174, 66, 180)"   # 告警浮窗（橙）
    FLOATER_BORDER_RUNNING: str = "rgba(16, 255, 161, 160)"    # LED 矩阵（绿）
    FLOATER_BORDER_CYAN: str = "rgba(0, 229, 255, 180)"       # HUD 浮窗（青）
    FLOATER_BORDER_NEUTRAL: str = "rgba(60, 80, 120, 140)"    # 中性边框（深灰蓝）

    # ---- 复位按钮（ResetViewButton）----------------------------------------
    RESET_BTN_BG: str = "rgba(10, 15, 28, 180)"               # 比浮窗背景深 1 档
    RESET_BTN_BG_HOVER: str = "rgba(20, 30, 50, 220)"          # hover 时略亮
    RESET_BTN_BORDER: str = "rgba(60, 80, 120, 140)"           # 同 FLOATER_BORDER_NEUTRAL


@dataclass(frozen=True)
class Fonts:
    FAMILY_TITLE: str = (
        "'Microsoft YaHei', 'PingFang SC', Consolas, monospace"
    )
    FAMILY_MONO: str = (
        "'Microsoft YaHei', 'PingFang SC', Consolas, monospace"
    )
    FAMILY_DATA: str = "Consolas, monospace"
    FAMILY_BUTTON: str = (
        "'Microsoft YaHei', Consolas, monospace"
    )


@dataclass(frozen=True)
class FontSizes:
    XS: int = 8
    SM: int = 9
    MD: int = 10
    LG: int = 12
    XL: int = 13
    XXL: int = 16
    TITLE: int = 16
    ACCENT: int = 11
    PANEL_TITLE: int = 13
    PANEL_FOOTER: int = 9
    DATA_POINT_LABEL: int = 9
    DATA_POINT_VALUE: int = 13
    DATA_POINT_UNIT: int = 8
    BUTTON: int = 12
    STATUSBAR: int = 10
    CELL_ID: int = 10
    CELL_STATUS: int = 10
    COUNTDOWN_BIG: int = 56      # 倒计时巨字
    COUNTDOWN_STATUS: int = 11   # 倒计时状态文字


@dataclass(frozen=True)
class Sizing:
    # 圆角
    RADIUS_SM: int = 5    # 数据点
    RADIUS_MD: int = 6    # 按钮 / 数据网格
    RADIUS_LG: int = 8    # 数据网格外框
    RADIUS_CELL: int = 10  # 数据单元

    # 边框宽度
    BORDER_THIN: int = 1
    BORDER_THICK: int = 2

    # 垂直分组分割线
    VLINE_TOTAL_W: int = 18   # vline 容器宽度（含两侧空气）
    VLINE_CORE_W: int = 2     # 中心高亮实线宽
    VLINE_MARGIN: int = 8     # vline 上下边距，避免顶满

    # 详情页
    CHART_MIN_H: int = 240
    DETAIL_MIN_W: int = 900
    DETAIL_MIN_H: int = 720

    # 最小尺寸（widget 几何）
    TITLE_BAR_H: int = 40
    HEADER_BAR_H: int = 22
    BUTTON_MIN_H: int = 54
    DATA_POINT_MIN_W: int = 50
    DATA_POINT_MIN_H: int = 40
    DATA_CELL_MIN_W: int = 280
    DATA_CELL_MIN_H: int = 150
    DATA_GRID_MARGIN: int = 3
    DATA_GRID_SPACING: int = 3
    DATA_POINT_MARGIN_H: int = 3
    DATA_POINT_MARGIN_V: int = 1
    HEADER_BAR_MARGIN_LR: int = 4
    HEADER_BAR_MARGIN_B: int = 4
    CELL_OUTER_MARGIN_H: int = 8
    CELL_OUTER_MARGIN_V: int = 6
    CELL_OUTER_SPACING: int = 6
    # 倒计时进度条
    COUNTDOWN_PROGRESS_H: int = 8

    # ---- 导航栏 / 浮窗 / 复位按钮（Phase 4-B/C）----------------------------
    # 顶部 nav bar
    NAV_BAR_H: int = 60

    # 浮窗（4 种 side 共用）
    FLOATER_W: int = 220
    FLOATER_MARGIN_H: int = 16
    FLOATER_MARGIN_V: int = 12
    FLOATER_SPACING: int = 4
    FLOATER_STACK_GAP: int = 14   # 主页浮窗层垂直堆叠间距（4 个浮窗 top→bottom）

    # LED 矩阵浮窗（RightLEDStripFloater）
    FLOATER_LED_SPACING: int = 6       # 容器内子项间距
    FLOATER_LED_ROW_SPACING: int = 2   # 行内点间距
    FLOATER_LED_DOT_SIZE: int = 16     # 单个 LED 点边长（正方形）
    FLOATER_LED_ROW_LABEL_W: int = 20  # 行号标签宽度

    # 右上角"立即复位"按钮
    RESET_BTN_W: int = 96
    RESET_BTN_H: int = 28

    # ---- 详情页（Phase 3 优化新增）-----------------------------------------
    DETAIL_HEADER_H: int = 56
    DETAIL_ACTIONS_H: int = 96
    DETAIL_MARGIN: int = 16            # root 边距
    DETAIL_SPACING: int = 12           # root 内子项间距
    DETAIL_HEADER_MARGIN_H: int = 16   # header layout 左右边距
    DETAIL_ACTIONS_MARGIN_V: int = 8   # actions layout 上下边距

    # ---- 电流页工具条（Phase A.8）------------------------------------------
    TOOLBAR_H: int = 48
    TOOLBAR_BTN_MIN_H: int = 32        # 批量按钮最小高度
    TOOLBAR_SPACING: int = 12
    TOOLBAR_GAP: int = 16              # 标题/按钮组与右侧元素的拉伸间隔

    # ---- 缩版 DataCell / DataPoint（Phase A 缩到小尺寸）--------------------
    DATA_CELL_MIN_W: int = 110
    DATA_CELL_MIN_H: int = 64
    DATA_POINT_MIN_W_NEW: int = 36     # Phase A 缩版（区别于已有 DATA_POINT_MIN_W=50）
    DATA_POINT_MIN_H_NEW: int = 28
    DATA_POINT_TOP_SPACING: int = 2    # DataPoint top hbox 内部子项间距

    # ---- 数据中心（Phase 6）------------------------------------------------
    DATA_PAGE_MARGIN: int = 12         # 页面整体边距
    DATA_PAGE_SPACING: int = 10        # 页面内部子项间距
    DATA_HEADER_H: int = 56            # 顶栏（徽章+标题+副标题+状态）高度
    DATA_HEADER_PAD_L: int = 8         # 顶栏 layout 左内边距
    DATA_HEADER_PAD_R: int = 12        # 顶栏 layout 右内边距
    DATA_HEADER_GAP: int = 12          # 顶栏子项间距
    DATA_HEADER_BADGE_MIN_W: int = 28  # 徽章最小宽
    DATA_HEADER_BADGE_MAX_W: int = 36  # 徽章最大宽
    DATA_TABS_H: int = 40              # 自绘页签栏高度
    DATA_TABS_PAD_L: int = 8           # 页签栏 layout 左内边距
    DATA_TABS_PAD_R: int = 8           # 页签栏 layout 右内边距
    DATA_TABS_GAP: int = 4             # 页签按钮间距
    DATA_CATEGORY_BAR_H: int = 44      # 类别工具条高度
    DATA_CATEGORY_GAP: int = 8         # 类别工具条子项间距
    DATA_CATEGORY_PAD: int = 0         # 类别工具条内边距
    DATA_SIDEBAR_W: int = 220          # 图片列表侧栏宽度
    DATA_SIDEBAR_PAD: int = 10         # 侧栏内边距
    DATA_SIDEBAR_GAP: int = 8          # 侧栏子项间距
    DATA_SIDEBAR_NAV_GAP: int = 6      # 侧栏导航按钮间距
    DATA_CANVAS_MIN_H: int = 420       # 标注画布最小高度
    DATA_CANVAS_PAD_X: int = 10        # 画布角标行左右内边距
    DATA_CANVAS_PAD_T: int = 6         # 画布角标行顶部内边距
    DATA_CANVAS_PAD_B: int = 6         # 画布角标行底部内边距
    DATA_CANVAS_GAP: int = 4           # 画布角标子项间距
    DATA_CANVAS_CENTER_GAP: int = 6    # 画布中心提示子项间距
    DATA_FOOTER_MIN_H: int = 110       # 底部对象列表 + 操作栏最小高度
    DATA_FOOTER_PAD: int = 0           # 底栏内边距
    DATA_FOOTER_GAP: int = 6           # 底栏子项间距
    DATA_FOOTER_HEAD_GAP: int = 8      # 底栏标题行子项间距
    DATA_FOOTER_BTN_GAP: int = 8       # 底栏按钮间距
    DATA_PLACEHOLDER_GAP: int = 8      # 占位页子项间距

    # ---- 数据标注 · 画布交互参数 --------------------------------------------
    ANNOT_BOX_BORDER_W: int = 2       # 标注框描边宽度（正常态）
    ANNOT_BOX_BORDER_W_SEL: int = 3   # 选中框描边宽度
    ANNOT_BOX_MIN_SIZE: int = 10      # 拖拽画框最小边长（小于此不保留）
    ANNOT_PADDING_PX: int = 8        # 图片边距（canvas 内间距）
    # 缩放控制条（画布顶栏）
    ANNOT_ZOOM_BTN_W: int = 32        # 缩放按钮最小宽
    ANNOT_ZOOM_BTN_H: int = 24        # 缩放按钮高度
    ANNOT_ZOOM_PCT_W: int = 56        # 缩放百分比标签宽
    # 画布角标展示的参考尺寸（真实尺寸在图片加载后动态更新）
    ANNOT_CANVAS_REF_W: int = 1920    # 画布角标参考宽（占位展示）
    ANNOT_CANVAS_REF_H: int = 1080    # 画布角标参考高（占位展示）
    ANNOT_ZOOM_PCT_DEFAULT: int = 50  # 画布角标初始缩放百分比（占位展示）
    ANNOT_ZOOM_PCT_SCALE: int = 100   # 缩放比例(0~1)→百分比换算系数


@dataclass(frozen=True)
class DesignTokens:
    colors: Colors
    fonts: Fonts
    font_sizes: FontSizes
    sizing: Sizing

    @classmethod
    def default(cls) -> "DesignTokens":
        return cls(
            colors=Colors(),
            fonts=Fonts(),
            font_sizes=FontSizes(),
            sizing=Sizing(),
        )


# 全局默认 token 实例（绝大多数场景直接用这个）
DEFAULT_TOKENS: DesignTokens = DesignTokens.default()


# ---- rgba 工具：把 #RRGGBB 转 rgba(R, G, B, alpha) -----------------------------
# 用途：消除 templates.py 中"同色不同 alpha"重复（如 rgba(0,191,255,30/40/50)）
# 设计：与 frozen dataclass 平级的模块级函数，避免污染 token 体系
def rgba(color: str, alpha: int) -> str:
    """token 化 rgba 工具。

    Args:
        color: 形如 "#00bfff" 的 hex 字符串（必须 7 字符，含 #）
        alpha: 0-255 的整数透明度

    Returns:
        形如 "rgba(0, 191, 255, 50)" 的字符串，可直接嵌入 QSS

    Example:
        >>> rgba("#00bfff", 50)
        'rgba(0, 191, 255, 50)'
        >>> rgba(c.BORDER_PRIMARY, 30)  # 在 f-string 中使用
        'rgba(0, 191, 255, 30)'
    """
    if not (isinstance(color, str) and color.startswith("#") and len(color) == 7):
        raise ValueError(
            f"rgba() expects '#RRGGBB' format (7 chars), got {color!r}"
        )
    try:
        r = int(color[1:3], 16)
        g = int(color[3:5], 16)
        b = int(color[5:7], 16)
    except ValueError as e:
        raise ValueError(f"rgba() failed to parse {color!r}: {e}") from e
    if not (0 <= alpha <= 255):
        raise ValueError(f"rgba() alpha must be 0-255, got {alpha}")
    return f"rgba({r}, {g}, {b}, {alpha})"


def rgba_from_tuple(rgb_or_rgba, alpha: int = None) -> str:
    """tuple 形式颜色 → rgba 字符串（用于 LED 状态色等 (R, G, B[, A]) 形式 token）。

    Args:
        rgb_or_rgba: 3-tuple (R, G, B) 或 4-tuple (R, G, B, A)
        alpha: 覆盖 alpha（None = 用 tuple 内的 A；0-255）

    Returns:
        形如 "rgba(16, 255, 161, 0.95)" 的字符串

    Example:
        >>> rgba_from_tuple(c.LED_RUNNING, 0.95)  # 强制 0.95 alpha
        'rgba(16, 255, 161, 0.95)'
        >>> rgba_from_tuple(c.LED_OFFLINE)  # 用 tuple 内置 alpha
        'rgba(60, 70, 90, 180)'  # 注意：0-255 整数 alpha
    """
    if len(rgb_or_rgba) == 3:
        r, g, b = rgb_or_rgba
        a = alpha if alpha is not None else 255
    elif len(rgb_or_rgba) == 4:
        r, g, b, a_default = rgb_or_rgba
        a = alpha if alpha is not None else a_default
    else:
        raise ValueError(
            f"rgba_from_tuple() expects 3-tuple or 4-tuple, got len={len(rgb_or_rgba)}"
        )
    # alpha 既支持 0-255 整数（QSS 规范）也支持 0-1 浮点（CSS3 扩展）
    # 这里统一输出整数（QSS 兼容最好）；若 a 是 0-1 浮点自动 *255
    if isinstance(a, float) and 0.0 <= a <= 1.0:
        a = int(a * 255)
    return f"rgba({r}, {g}, {b}, {a})"
