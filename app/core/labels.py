"""所有用户可见字符串的集中管理。

设计原则：
- 本文件是**唯一**可以出现用户可见中文/英文文案的位置
- `app/ui/` 和 `app/widgets/` 不允许出现裸字符串字面量（除文档/日志外）
- 模板字符串用 `str.format(**)` 注入参数，避免散落的 f-string 拼接
"""


# ---- 应用标题 ---------------------------------------------------------------
WINDOW_TITLE = (
    "老化检测系统控制台  ||  AGING DETECTION SYSTEM CONSOLE  v2.0"
)


# ---- 状态栏 / accent / footer / 按钮反馈 -----------------------------------
STATUS_BAR_TEMPLATE = (
    "● SYSTEM ONLINE   ::   72 CHANNELS NOMINAL   ::   "
    "REFRESH {refresh_ms}ms"
)
STATUS_BAR_DETAIL_TEMPLATE = (
    "● SYSTEM ONLINE   ::   RUN {running}  PAUSED {paused}  ::   "
    "REFRESH {refresh_ms}ms   ::   DETAIL OPEN {open_detail}"
)
ACCENT_OK_BADGE = "[ OK ]"
FOOTER_TEMPLATE = (
    "AGING CONSOLE\n"
    "v2.0.0  /  {date}\n"
    "GRID  {grid_rows}x{grid_cols}  /  {button_count} ACT"
)
FOOTER_DATE = "2026-07-07"
CMD_TRIGGERED_TEMPLATE = (
    "[ CMD ]  {label}  ::  triggered @ {timestamp}"
)


# ---- 通道状态文字 -----------------------------------------------------------
STATUS_ONLINE_TEXT = "● ON"
STATUS_ALERT_TEXT = "● ALERT"
STATUS_NO_DATA_TEXT = "○ NO DATA"
STATUS_OFFLINE_TEXT = "○ OFF"


# ---- 检测状态文字 -----------------------------------------------------------
DETECTION_STATE_STOPPED = "已停止"
DETECTION_STATE_RUNNING = "运行中"
DETECTION_STATE_PAUSED = "已暂停"
DETECTION_STATE_UNKNOWN = "未知"   # 详情页 _state_text 兜底


# ---- 右侧按钮区 -------------------------------------------------------------
BUTTON_AREA_TITLE = "功能区  //  CONTROL"
PANEL_NO_SELECTION_TEXT = "（请先点击数据卡片）"
PANEL_SELECTION_TEMPLATE = "CH-{cid:02d}  //  {state}"

# ---- 批量按钮区（v2：多选 + 批量控制） -------------------------------------
BATCH_SECTION_TITLE = "── 批量 ──"
DETECTION_SECTION_TITLE = "── 检测控制 (选区) ──"
DANGER_SECTION_TITLE = "── 危险 ──"
BUTTON_BATCH_SELECT_ALL_LABEL = "全选"
BUTTON_BATCH_SELECT_ALL_GLYPH = "☑"
BUTTON_BATCH_START_ALL_LABEL = "全部开始"
BUTTON_BATCH_START_ALL_GLYPH = "▶▶"
BUTTON_BATCH_PAUSE_ALL_LABEL = "全部暂停"
BUTTON_BATCH_PAUSE_ALL_GLYPH = "⏸⏸"
BUTTON_BATCH_STOP_ALL_LABEL = "全部结束"
BUTTON_BATCH_STOP_ALL_GLYPH = "■■"
# 帮助文本：标明批量按钮与选区无关
BATCH_HELP_TEXT_TEMPLATE = "作用于全部 {total} 台 · 与选区无关"
# 检测控制按钮作用域提示：与选区相关，需先点选 cell
DETECTION_HELP_TEXT = "作用于当前选区 · 需先点选 cell"
# 全部结束的二次确认
CONFIRM_STOP_ALL_TITLE = "确认全部结束？"
CONFIRM_STOP_ALL_TEXT_TEMPLATE = (
    "将停止全部 {total} 台设备：\n"
    "  • {running} 台运行中\n"
    "  • {paused} 台已暂停\n"
    "  • {detail} 个详情页已打开\n"
    "\n此操作不可撤销，是否继续？"
)
CONFIRM_STOP_ALL_NOOP_TEXT = "当前没有运行/暂停中的设备，无需结束。"
CONFIRM_STOP_ALL_OK = "是 · 全部结束"
CONFIRM_STOP_ALL_CANCEL = "取消"
# ---- 选中标签（双行：primary + secondary） -------------------------------
PANEL_SELECTION_PRIMARY_EMPTY = "（请先点击数据卡片）"
PANEL_SELECTION_PRIMARY_TEMPLATE = "已选 {n_sel} / {total} 台"
PANEL_SELECTION_SECONDARY_TEMPLATE = (
    "RUN {running} / PAUSED {paused} / STOP {stopped}"
)


# ---- 详情页 ----------------------------------------------------------------
DETAIL_WINDOW_TITLE_TEMPLATE = "CH-{cid:02d}  详情视图  //  DETAIL"
DETAIL_INFO_BAR_TEMPLATE = (
    "通道: CH-{cid:02d}    状态: {state}    "
    "数据帧: {frames}    运行时长: {runtime_s}s"
)
DETAIL_CHART_CURRENT_TITLE = "电流时序  //  CURRENT I-t"
CHART_X_LABEL = "时间 / seconds"
CHART_CURRENT_Y_LABEL = "电流 / A"
CHART_LEGEND_CURRENT_TEMPLATE = (
    "● <span style='color:{color}'>{name}</span> "
    "<span style='color:{text}'>{value:.2f} A</span>"
)
# 图表右上角图例显示名（中文友好）
CHART_LEGEND_CURRENT_NAMES = ("电流1", "电流2", "电流3", "电流4")
CHART_LEGEND_ALL_LABEL = "全部显示"
CHART_LEGEND_ALL_SHORT = "ALL"
COUNTDOWN_SECTION_TITLE = "倒计时设定  //  COUNTDOWN"
COUNTDOWN_DURATION_LABEL = "时长（分钟）"
COUNTDOWN_START_TEXT = "开始"
COUNTDOWN_CANCEL_TEXT = "取消"
COUNTDOWN_REMAINING_TEMPLATE = "剩余: {mmss}"
COUNTDOWN_EXPIRED_TEXT = "● 时间到 · 已联动结束检测"
COUNTDOWN_IDLE_TEXT = "未启动"
COUNTDOWN_STATUS_IDLE = "● IDLE"
COUNTDOWN_STATUS_RUNNING = "● RUNNING"
COUNTDOWN_STATUS_WARNING = "● FINAL 60s"
COUNTDOWN_STATUS_EXPIRED = "● EXPIRED"
DEFAULT_COUNTDOWN_MINUTES = 30
# 倒计时归零：cell 闪烁绿色等待操作人手动停止（不再自动 stop）
COUNTDOWN_EXPIRED_BANNER_TEMPLATE = (
    "■ 倒计时归零 · {channels} 请点击「停止检测」手动结束"
)


# ---- 状态栏错误提示 ---------------------------------------------------------
STATUS_BAR_NORMAL_TEMPLATE = (
    "● SYSTEM ONLINE   ::   RUN {running}  PAUSED {paused}  ::   "
    "REFRESH {refresh_ms}ms   ::   DETAIL OPEN {open_detail}"
    "   ::   {selected}"
)
# 选区状态文本（状态栏尾部）
SELECTION_BAR_NONE = "SEL ∅"
SELECTION_BAR_SINGLE_TEMPLATE = "SEL 1 · CH-{cid:02d}"
SELECTION_BAR_MULTI_TEMPLATE = "SEL {n} · 主 CH-{cid:02d}"
STATUS_BAR_ERROR_BADGE = "● ERR {count}"
DETAIL_ERROR_BAR_DEFAULT_TEXT = "正常运行中"
DETAIL_ERROR_BAR_SHOW_TEXT = "● {message}"


# ---- v3.0 主页 3D 机柜视图 --------------------------------------------------
WINDOW_TITLE_V3 = (
    "老化检测系统控制台  ||  AGING DETECTION SYSTEM CONSOLE  v3.0"
)
NAV_BRAND_TEXT = "AGING CONSOLE"
NAV_BRAND_GLYPH = "⚡"
# 顶部导航（顺序即显示顺序；index 0 是默认主页「3D 机柜」）
NAV_ITEMS = (
    ("home",     "🏠  主页",   "3D 机柜总览"),
    ("current",  "⚡  电流检测", "全通道电流数据"),
    ("video",    "📹  视频检测", "AI 视觉识别"),
    ("data",     "📊  数据中心", "历史 / 趋势 / 导出"),
    ("settings", "⚙   系统设置", "阈值 / 模型 / 设备"),
)
# 3D 机柜视图标题
RACK_3D_TITLE = "3D 机柜  //  RACK VIEW"
RACK_3D_HINT = "鼠标拖拽旋转 · 滚轮缩放 · 点击 LED 进入单通道详情"
# 3D 机柜面板说明（用户问"机柜是什么"时显示）
RACK_3D_PANEL_LABEL_TEMPLATE = "CH-{cid:02d}"


# ---- v3.0 主页 HUD 卡片 -----------------------------------------------------
HUD_SYSTEM_STATS_TITLE = "系统状态  //  SYSTEM"
HUD_SYSTEM_STATS_RUNNING_TEMPLATE = "▶  运行 {n} / {total}"
HUD_SYSTEM_STATS_PAUSED_TEMPLATE = "⏸  暂停 {n} / {total}"
HUD_SYSTEM_STATS_STOPPED_TEMPLATE = "■  停止 {n} / {total}"
HUD_ALERTS_TITLE = "实时告警  //  ALERTS"
HUD_ALERTS_EMPTY = "（无告警）"
HUD_ALERT_ITEM_TEMPLATE = "⚠ CH-{cid:02d}  ·  {reason}"
HUD_SHORTCUTS_TITLE = "快捷操作  //  ACTIONS"
SHORTCUT_BATCH_START_LABEL = "▶▶  全部开始"
SHORTCUT_BATCH_START_GLYPH = "▶▶"
SHORTCUT_BATCH_PAUSE_LABEL = "⏸⏸  全部暂停"
SHORTCUT_BATCH_PAUSE_GLYPH = "⏸⏸"
SHORTCUT_BATCH_STOP_LABEL = "■■  全部结束"
SHORTCUT_BATCH_STOP_GLYPH = "■■"
SHORTCUT_EXPORT_LABEL = "💾  导出数据"
SHORTCUT_EXPORT_GLYPH = "💾"


# ---- v3.0 二级页面占位 -----------------------------------------------------
PAGE_PLACEHOLDER_TEMPLATE = "「{name}」\n\n{desc}\n\n（本页面将在 Phase {phase} 实现）"
PAGE_PHASE_CURRENT = "3"
PAGE_PHASE_VIDEO = "4"
PAGE_PHASE_DATA = "6"
PAGE_PHASE_SETTINGS = "6"


# ---- v3.0 3D LED 状态标签（用于 hover tooltip / 控制台输出）---------------
LED_STATE_OFFLINE = "○ OFF"
LED_STATE_RUNNING = "● RUN"
LED_STATE_PAUSED = "⏸ PAUSE"
LED_STATE_ALERT = "● ALERT"
LED_STATE_WARNING = "● WARN"

# ---- 详情页 v3.0（v2 内嵌页，区别于 v2 独立窗口）---------------------------
DETAIL_TITLE_TEMPLATE = "详情  //  {cid}  ·  {state}"
DETAIL_BACK_TEXT = "← 返回主页"
DETAIL_NO_CHANNEL_TEXT = "（请从主页双击 LED 打开详情）"

DETAIL_CHART_TITLE = "电流时序  //  CURRENT I-t"
# 注：DETAIL_CHART_X_LABEL / DETAIL_CHART_Y_LABEL 复用现有 CHART_X_LABEL / CHART_CURRENT_Y_LABEL
DETAIL_ZERO_LINE_LABEL = "归零阈值 0A"
DETAIL_ZERO_ANOMALY_TEMPLATE = "⚠ {cid} 电流归零异常"

DETAIL_ACTIONS_TITLE = "操作  //  ACTIONS"
DETAIL_ACTION_START_TEXT = "▶ 开始"
DETAIL_ACTION_PAUSE_TEXT = "⏸ 暂停"
DETAIL_ACTION_RESUME_TEXT = "↻ 继续"
DETAIL_ACTION_STOP_TEXT = "■ 停止"
DETAIL_ACTION_LABELS = (
    DETAIL_ACTION_START_TEXT,
    DETAIL_ACTION_PAUSE_TEXT,
    DETAIL_ACTION_RESUME_TEXT,
    DETAIL_ACTION_STOP_TEXT,
)


# ---- 顶部导航栏（Phase 4-D）-------------------------------------------------
# 右侧版本号
NAV_VERSION_TEXT = "v3.0"


# ---- 电流页工具条（Phase 4-D）-----------------------------------------------
TOOLBAR_TITLE = "⚡ 电流检测  ·  CURRENT DETECTION"
TOOLBAR_BTN_START_LABEL = "▶ 启动"
TOOLBAR_BTN_PAUSE_LABEL = "⏸ 暂停"
TOOLBAR_BTN_STOP_LABEL = "■ 停止"
TOOLBAR_BTN_CLEAR_LABEL = "✕ 清空"
# 选区计数：模板用 n=0 时即为默认"已选 0"
TOOLBAR_SELECTION_TEMPLATE = "已选 {n}"


# ---- 浮窗层（Phase 4-D）------------------------------------------------------
# LED 状态矩阵浮窗标题
LED_MATRIX_TITLE = "● 状态矩阵  //  STATUS MATRIX"
# 右上角"立即复位"按钮
RESET_BTN_TEXT = "⟲  复位视角"
RESET_BTN_TOOLTIP = "把 3D 视角复位到初始位置（不打断数据）"
