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


# ---- 状态栏 · 告警常驻提示（G2） --------------------------------------------
ALERT_WARNING = "[!] {msg}"
ALERT_ERROR = "[ERR] {msg}"
ALERT_CRITICAL = "[CRIT] {msg}"


# ---- 通道状态文字 -----------------------------------------------------------
STATUS_ONLINE_TEXT = "● ON"
STATUS_PAUSED_TEXT = "⏸ PAUSED"
STATUS_ALERT_TEXT = "● ALERT"
STATUS_NO_DATA_TEXT = "○ NO DATA"
STATUS_OFFLINE_TEXT = "○ OFF"


# ---- 检测状态文字 -----------------------------------------------------------
DETECTION_STATE_STOPPED = "已停止"
DETECTION_STATE_RUNNING = "运行中"
DETECTION_STATE_PAUSED = "已暂停"
DETECTION_STATE_UNKNOWN = "未知"   # 详情页 _state_text 兜底


# ---- 检测状态 → 视觉/文本 统一映射（Phase 5 M7 合并） -----------------------
# Phase 5 之前有 3 套独立映射：
#   1) CellUIManager._STATE_TO_STATUS   （state → 视觉边框 status）
#   2) DetailPage._state_text           （state → 中文显示文本）
#   3) DetectionState enum              （state 自身）
# 现在统一到本表：(state_value) → (visual_status, text_label)
#   - visual_status: DataCell 边框 / 状态文字
#   - text_label:    详情页 / 状态栏等用户可见文本
from typing import NamedTuple


class DetectionStatePresentation(NamedTuple):
    """DetectionState 的统一表现层数据（视觉边框 + 文本）。"""
    visual_status: str   # DataCell 视觉 status（"online" / "no_data" 等）
    text_label: str      # 用户可见中文文本


# 与 services/cell_controller.py DetectionState.value 一一对应
# 键使用裸字符串而非 enum，避免循环依赖（labels 处于 core 层，DetectionState 在 services 层）
DETECTION_STATE_PRESENTATION: dict[str, DetectionStatePresentation] = {
    "stopped": DetectionStatePresentation("no_data", DETECTION_STATE_STOPPED),
    "running": DetectionStatePresentation("online",  DETECTION_STATE_RUNNING),
    "paused":  DetectionStatePresentation("paused",  DETECTION_STATE_PAUSED),
}


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
HUD_ALERT_ANOMALY_REASON = "电流异常"
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

# 详情页老化倒计时（按键右侧显示 + 可修改）
DETAIL_AGING_SECTION_TITLE = "老化倒计时"
DETAIL_AGING_VALUE_IDLE = "--:--:--"
DETAIL_AGING_VALUE_RUNNING = "{h:02d}:{m:02d}:{s:02d}"
DETAIL_AGING_EXPIRED = "已结束"
DETAIL_AGING_EDIT_PREFIX = "改时(分)"
DETAIL_AGING_APPLY = "修改"
DETAIL_AGING_HINT_TEMPLATE = "总 {total} 分钟 · 已老化 {consumed} 分 · 余 {remain} 分"


# ---- 顶部导航栏（Phase 4-D）-------------------------------------------------
# 右侧版本号
NAV_VERSION_TEXT = "v3.0"


# ---- 电流页工具条（Phase 4-D）-----------------------------------------------
TOOLBAR_TITLE = "⚡ 电流检测  ·  CURRENT DETECTION"
TOOLBAR_BTN_START_LABEL = "▶ 启动"
TOOLBAR_BTN_PAUSE_LABEL = "⏸ 暂停"
TOOLBAR_BTN_RESUME_LABEL = "↻ 继续"
TOOLBAR_BTN_STOP_LABEL = "■ 停止"
TOOLBAR_BTN_CLEAR_LABEL = "✕ 清空"
# 选区计数：模板用 n=0 时即为默认"已选 0"
TOOLBAR_SELECTION_TEMPLATE = "已选 {n}"


# ---- 视频检测页（v3.0 视频检测）---------------------------------------------
# 视频总览（位置标记页）
VIDEO_OVERVIEW_TITLE = "📹 视频流监控  //  VIDEO STREAMS"
VIDEO_OVERVIEW_HINT = "图表仅标记检测位点 · 双击单元进入该通道视频流检测"
VIDEO_OVERVIEW_SUBTITLE_TEMPLATE = "{rows}×{cols} · {total} 路检测位点"
CELL_HEADER_TEMPLATE = "CH-{cid:02d}"
CELL_MARK_TEMPLATE = "位点 {cid}"
CELL_OPEN_HINT = "双击进入检测 ↗"
# v3.1 顶部 KPI 卡片文案
KPI_TITLE_RUNNING = "运行中"
KPI_TITLE_PAUSED = "已暂停"
KPI_TITLE_ERROR = "出错"
KPI_TITLE_TOTAL = "总计"
KPI_UNIT = "路"

# 视频流检测页（单通道详情）
VIDEO_STREAM_TITLE_TEMPLATE = "视频流检测  ·  CH-{cid:02d}"
VIDEO_BACK_BTN = "◀ 返回总览"
VIDEO_LIVE_TITLE = "实时检测画面"
VIDEO_PANEL_EMPTY_HINT = "未导入视频\n请点击「导入视频」选择本地视频，再「开始」检测"
VIDEO_PANEL_PLACEHOLDER = "检测画面区域"
VIDEO_PANEL_LOADING = "模型加载中…"
VIDEO_STATS_TITLE = "检测结果  ·  LED 状态"
VIDEO_STATS_NONE = "尚未开始检测"
VIDEO_FLASH_SECTION_TITLE = "LED 亮灭波形 · 按系列"
VIDEO_SERIES_TITLE_TEMPLATE = "{series} 系列 · LED 亮灭"
VIDEO_SERIES_SUMMARY_TEMPLATE = "闪烁 {flashes} 次 ｜ 时长 {sec} s"
VIDEO_SERIES_OTHER = "其他"
VIDEO_WS_X_LABEL = "检测时间 (s)"
VIDEO_WS_Y_LABEL = "LED 位点"
VIDEO_CH_TABLE_TITLE_TEMPLATE = "通道 {ch} · LED 亮灭"
VIDEO_WORKER_CRASH = "检测 worker 进程异常退出"
VIDEO_TOOLBAR_BTN_IMPORT = "📂 导入视频"
VIDEO_TOOLBAR_BTN_START = "▶ 开始"
VIDEO_TOOLBAR_BTN_STOP = "■ 停止"
VIDEO_TOOLBAR_BTN_PAUSE = "⏸ 暂停"
VIDEO_TOOLBAR_BTN_RESUME = "▶ 继续"
VIDEO_DETECT_STATUS_RUNNING = "检测中…"
VIDEO_DETECT_STATUS_PAUSED = "已暂停"
VIDEO_DETECT_STATUS_IDLE = "就绪"
VIDEO_DETECT_STATUS_ERROR = "检测出错"
VIDEO_NEED_CURRENT_RUNNING = "该通道电流检测未运行，已跳过视频检测（视频检测跟随电流）；请先在电流页启动该通道。"
VIDEO_CELL_STANDBY = "待机"
VIDEO_CELL_NO_SOURCE = "无源"
VIDEO_CELL_LOADING_TEXT = "加载模型…"
VIDEO_CELL_STATE_RUNNING = "运行中"
VIDEO_CELL_STATE_DONE = "检测完成"
VIDEO_CELL_STATE_ERROR = "出错"
VIDEO_CELL_NO_CLASS_TEMPLATE = "未检出目标"
VIDEO_CELL_COUNT_TEMPLATE = "{name}: {n}"
VIDEO_CELL_FLASH_TEMPLATE = "{lid}: {n}"
VIDEO_CELL_LABEL_TOOLTIP = "LED 亮灭检测结果（H=亮 / L=灭）"
VIDEO_IMPORT_DIALOG_TITLE = "选择要导入的视频"
VIDEO_IMPORT_FILTER = "视频文件 (*.mp4 *.avi *.mkv *.mov *.wmv *.flv *.m4v *.mpg *.mpeg *.mts);;所有文件 (*)"

# ---- 54 路静默集中监控（monitor）--------------------------------------------
MONITOR_CHOOSE_BTN = "选择视频…"
MONITOR_LOAD_MANIFEST_BTN = "加载清单…"
MONITOR_MANIFEST_DIALOG_TITLE = "选择监控清单（.txt，每行一个视频绝对/相对路径，行序对应 CH-01…）"
MONITOR_MANIFEST_FILTER = "监控清单 (*.txt);;所有文件 (*)"
MONITOR_MANIFEST_LOADED = "已加载 {n} 路监控清单（首路 CH-01，行序即通道）"
MONITOR_MANIFEST_EMPTY = "清单为空或格式错误"
MONITOR_MANIFEST_MISSING = "清单中第 {idx} 行视频不存在：{path}"
MONITOR_START_BTN = "开始静默监控"
MONITOR_STOP_BTN = "停止监控"
MONITOR_CHOOSE_DIALOG_TITLE = "选择设备视频（一次最多 {max} 路，按所选顺序对应位点）"
MONITOR_EMPTY_ERROR = "未选择任何视频"
MONITOR_TOO_MANY_ERROR = "最多选择 {max} 路视频，当前 {n}"
MONITOR_RUNNING_HINT = "静默监控运行中（{count} 路 @ {fps} fps，{size}）"
MONITOR_IDLE_HINT = "选择设备视频后可开始静默集中监控（不预览，后台统计 LED 闪烁）"
MONITOR_POLLING_ERROR = "静默监控返回错误：{msg}"
CELL_MONITOR_TEMPLATE = "闪 {n}"
CELL_MONITOR_LOOP_TEMPLATE = "闪 {n} · 圈 {loops}"
CELL_MONITOR_PAUSED = "暂停 · 闪 {n} · 圈 {loops}"
MONITOR_DEFAULT_AUTO = "已载入 {n} 路默认测试视频作为映射源：电流启动对应通道时自动拉起其视频检测（也可手动「开始静默监控」）"
MONITOR_DONE = "静默监控已完成"
MONITOR_ABNORMAL_FINISH = "监控线程意外结束（可能异常或运行了旧代码）。循环检测已停止，请完全退出系统后重试，并查看日志。"
CELL_MONITOR_OPENING = "…"
CELL_MONITOR_DONE = "✓"
CELL_MONITOR_ERROR = "✗"


# ---- 系统设置页（设备绑定 + 老化时长 + 访问密码）-------------------------------
SETTINGS_PAGE_TITLE = "⚙ 系统设置  //  SYSTEM SETTINGS"
SETTINGS_PAGE_HINT = "密码与老化时长持久化（重启保留）；设备绑定为会话内存"

# 老化倒计时全局设置
SETTINGS_AGING_TITLE = "老化倒计时  //  AGING COUNTDOWN"
SETTINGS_AGING_DEFAULT_HINT_TEMPLATE = "全局默认 {hours} 小时，修改后持久化（重启保留），作为新一轮老化倒计时时长"
SETTINGS_AGING_LABEL = "老化时长（分钟）"
SETTINGS_AGING_SPIN_SUFFIX = " 分钟"
SETTINGS_AGING_APPLY = "应用"
SETTINGS_AGING_RESET = "恢复默认"
SETTINGS_AGING_APPLIED = "已应用老化时长：{minutes} 分钟（{hours} 小时 {mins} 分）"
SETTINGS_AGING_RESET_DONE = "已恢复默认老化时长：{hours} 小时"

# 设置访问安全门禁
SETTINGS_LOCK_TITLE = "设置访问验证"
SETTINGS_LOCK_HINT = "进入系统设置需验证密码"
SETTINGS_LOCK_HINT_DEFAULT = "当前为默认密码，进入后建议立即修改"
SETTINGS_LOCK_CONFIRM = "进入"
SETTINGS_LOCK_CANCEL = "取消"
SETTINGS_LOCK_ERROR = "密码错误，请重试"

SETTINGS_PASSWORD_TITLE = "设置访问密码  //  ACCESS PASSWORD"
SETTINGS_PASSWORD_HINT = "进入系统设置需验证密码；默认密码 admin123，建议修改"
SETTINGS_PASSWORD_CURRENT = "当前密码"
SETTINGS_PASSWORD_NEW = "新密码"
SETTINGS_PASSWORD_CONFIRM = "确认新密码"
SETTINGS_PASSWORD_APPLY = "修改密码"
SETTINGS_PASSWORD_RESET = "恢复默认密码"
SETTINGS_PASSWORD_APPLIED = "密码已更新"
SETTINGS_PASSWORD_RESET_DONE = "已恢复默认密码 admin123"
SETTINGS_PASSWORD_IS_DEFAULT = "⚠ 当前为默认密码，建议尽快修改"
SETTINGS_PASSWORD_FILL_ALL = "请填写完整（当前密码 / 新密码 / 确认新密码）"
SETTINGS_PASSWORD_ERR_WRONG_CURRENT = "当前密码不正确"
SETTINGS_PASSWORD_ERR_TOO_SHORT = "新密码至少 6 位"
SETTINGS_PASSWORD_ERR_MISMATCH = "两次输入的新密码不一致"
SETTINGS_PASSWORD_PLACEHOLDER = "••••••"

# 设置页空闲超时自动返回主页
SETTINGS_IDLE_AUTOBACK_NOTE = "长时间无操作，已自动返回系统主页面"

# 电流单元分组（每 6 CH 一组，3×2 布局）
SETTINGS_CURRENT_UNIT_TITLE = "电流单元分组  //  CURRENT UNITS (3×2)"
SETTINGS_CURRENT_UNIT_HINT_TEMPLATE = (
    "每 6 个 CH 绑定一台电流 ESP32 · 按 3 行 × 2 列布局 · 共 {units} 组"
)
SETTINGS_UNIT_ID_LABEL = "单元 {u}"
SETTINGS_UNIT_CIDS_TEMPLATE = "CH-{cids}"

# 摄像头绑定（每 CH 一台 ESP32）
SETTINGS_CAMERA_TITLE = "摄像头绑定  //  CAMERA BINDING"
SETTINGS_CAMERA_HINT_TEMPLATE = "每个 CH 位点绑定一台 ESP32 摄像头（默认 CAM-{cid:02d}，可改）"
SETTINGS_CAMERA_ID_LABEL_TEMPLATE = "CH-{cid:02d}"
SETTINGS_CAMERA_ID_DEFAULT_TEMPLATE = "CAM-{cid:02d}"

# 分组内部动作
SETTINGS_RESET_ALL_CAMERAS = "全部摄像头恢复默认"
SETTINGS_RESET_ALL_UNITS = "全部电流单元恢复默认"
SETTINGS_RESET_ALL_CAMERAS_DONE = "已恢复全部摄像头默认绑定"
SETTINGS_RESET_ALL_UNITS_DONE = "已恢复全部电流单元默认分组"


# ---- 浮窗层（Phase 4-D）------------------------------------------------------
# LED 状态矩阵浮窗标题
LED_MATRIX_TITLE = "● 状态矩阵  //  STATUS MATRIX"
# 右上角"立即复位"按钮
RESET_BTN_TEXT = "⟲  复位视角"
RESET_BTN_TOOLTIP = "把 3D 视角复位到初始位置（不打断数据）"


# ---- 数据中心（Phase 6）-----------------------------------------------------
# 页面标题 / 副标题 / 页签
DATA_CENTER_TITLE = "数据中心"
DATA_CENTER_SUBTITLE = "历史数据 · 数据标注 · 训练"
DATA_TAB_HISTORY = "历史 / 趋势 / 导出"
DATA_TAB_ANNOTATE = "数据标注"
DATA_TAB_TRAIN = "训练 / 转换"

# 历史 / 趋势 / 导出 页（后续实现）
DATA_HISTORY_PLACEHOLDER = (
    "历史数据查询 / 趋势图 / 数据导出 / 报表生成将在后续阶段实现"
)

# 数据标注页
ANNOT_CATEGORY_LABEL = "类别"
ANNOT_TOOL_LABEL = "工具"
ANNOT_TOOL_DRAW = "绘  制"
ANNOT_TOOL_EDIT = "编  辑"
ANNOT_TOOL_DRAW_TIP = "拖拽画框；可在已有框内/重叠处连续绘制同类框"
ANNOT_TOOL_EDIT_TIP = "点选/移动/缩放/删除已有标注框"
ANNOT_CATEGORY_ADD = "+ 新增类别"
ANNOT_CATEGORY_DELETE = "删除类别"
ANNOT_CATEGORY_DELETE_TITLE = "删除类别"
ANNOT_CATEGORY_DELETE_PROMPT = "选择要删除的类别（仅显示当前系列）"
ANNOT_CATEGORY_DELETE_EMPTY_HINT = "当前系列暂无类别，可先在顶部「+ 新增类别」"
ANNOT_CATEGORY_ADD_TITLE = "新增类别"
ANNOT_CATEGORY_ADD_SUCCESS = "已新增类别：{name}"
ANNOT_CATEGORY_ADD_EXISTS = "类别已存在：{name}"
ANNOT_CATEGORY_NAME_PROMPT = "输入新的类别名（如 FP_VPL，不带 _H/_L 后缀）"
ANNOT_CATEGORY_NAME_EMPTY = "类别名不能为空"
ANNOT_CATEGORY_KIND_PROMPT = "选择类别类型"
ANNOT_CATEGORY_KIND_AREA = "区域大框（area）"
ANNOT_CATEGORY_KIND_LED = "LED 点（led）"
ANNOT_CATEGORY_HL_PROMPT = "该类别是否带亮/灭（H/L）属性？"
ANNOT_CATEGORY_HL_YES = "是，带亮灭"
ANNOT_CATEGORY_HL_NO = "否，仅位置"
ANNOT_CATEGORY_REMOVE_CONFIRM = "确定删除类别「{name}」吗？"
ANNOT_CATEGORY_REMOVE_YES = "确定删除"
ANNOT_CATEGORY_REMOVE_SUCCESS = "已删除类别：{name}"
ANNOT_CATEGORY_REMOVE_FAILED = "删除类别失败（不存在或已在使用）"
ANNOT_CATEGORY_KIND_ORDER = ["area", "led"]
ANNOT_IMAGE_LIST_TITLE = "图片列表"
ANNOT_PREV_BTN = "上一张"
ANNOT_NEXT_BTN = "下一张"
ANNOT_CANVAS_TITLE = "标注画布"
ANNOT_CANVAS_HINT = "选择类别后在画布上拖拽画框；绘制模式可连续画框，编辑模式移动/缩放已有框"
ANNOT_CANVAS_CORNER_TEMPLATE = "⊕  CANVAS  ·  {w}×{h}  ·  {pct}%"
ANNOT_OBJECT_LIST_TITLE = "当前图标注对象"
ANNOT_OBJECT_LIST_EMPTY = "（暂无标注对象）"
ANNOT_SAVE_BTN = "保存标注"
ANNOT_CANCEL_BTN = "取消"

# 图片文件夹导入 + XML 映射
ANNOT_IMPORT_BTN = "⇪ 导入图片"
ANNOT_IMPORT_PROMPT = "选择图片文件夹（JPEGImages）"
ANNOT_IMPORT_DIALOG_TITLE = "导入图片文件夹"
ANNOT_IMPORT_SUMMARY = "已导入 {total} 张图片，{mapped} 张已有标注"
ANNOT_IMPORT_EMPTY = "（请先导入图片文件夹）"
ANNOT_IMAGE_MAPPED_MARK = "●  "
ANNOT_IMAGE_UNMAPPED_MARK = "○  "
ANNOT_IMAGE_ENTRY = "{mark}{name}"
ANNOT_OBJECT_ENTRY = "{name}  ({x1},{y1})-({x2},{y2})"

# 视频导入抽帧
ANNOT_VIDEO_IMPORT_BTN = "⇪ 导入视频"
ANNOT_VIDEO_DIALOG_TITLE = "导入视频并截取数据集"
ANNOT_VIDEO_FILE_LABEL = "视频文件"
ANNOT_VIDEO_BROWSE = "浏览…"
ANNOT_VIDEO_SERIES_LABEL = "目标系列"
ANNOT_VIDEO_SERIES_A = "A 系列"
ANNOT_VIDEO_SERIES_FP = "FP 系列"
ANNOT_VIDEO_STEP_LABEL = "抽帧间隔（每 N 帧一张）"
ANNOT_VIDEO_INFO_TEMPLATE = "{name} · {w}×{h} · {fps}fps · {frames} 帧"
ANNOT_VIDEO_NO_FILE = "未选择视频文件"
ANNOT_VIDEO_PROBE_FAILED = "无法读取视频：{reason}"
ANNOT_VIDEO_START = "开始抽取"
ANNOT_VIDEO_RUNNING = "正在抽取… {done}/{total} 帧"
ANNOT_VIDEO_DONE = "✅ 已抽取 {saved} 张图片 → {dir}"
ANNOT_VIDEO_EMPTY_STEP = "抽帧间隔必须 ≥ 1"

# 图片列表筛选 + 统计
ANNOT_FILTER_LABEL = "筛选"
ANNOT_FILTER_ALL = "全部"
ANNOT_FILTER_MAPPED = "已标注"
ANNOT_FILTER_UNMAPPED = "未标注"
ANNOT_STATS_TEMPLATE = "共 {total} · 已标注 {mapped} · 未标注 {unmapped}"

# 标注器交互
ANNOT_CANVAS_EMPTY_HINT = "选择图片后，拖动鼠标绘制标注框"
ANNOT_CANVAS_NO_CATEGORY = "先在顶部选择标注类别"
ANNOT_CANVAS_CATEGORY_READY = "当前类别：{cat}"
ANNOT_DELETE_SELECTED_BTN = "删除选中"
ANNOT_OBJECTS_SAVED = "标注已保存：{path}"
ANNOT_OBJECTS_SAVE_FAILED = "保存失败：{reason}"
ANNOT_OBJECTS_EMPTY_SAVE = "当前没有标注对象"

# 图片导航 / 当前索引
ANNOT_INDEX_TEMPLATE = "{cur} / {total}"
ANNOT_INDEX_EMPTY = "0 / 0"

# 缩放控制条
ANNOT_ZOOM_OUT = "−"
ANNOT_ZOOM_IN = "+"
ANNOT_ZOOM_FIT = "适应"
ANNOT_ZOOM_ORIG = "1:1"
ANNOT_ZOOM_PCT_TEMPLATE = "{pct}%"
ANNOT_ZOOM_TOOLTIP_OUT = "缩小（Ctrl+滚轮 / -）"
ANNOT_ZOOM_TOOLTIP_IN = "放大（Ctrl+滚轮 / +）"
ANNOT_ZOOM_TOOLTIP_FIT = "适应视图（0）"
ANNOT_ZOOM_TOOLTIP_ORIG = "原始大小（1）"

# 未保存提示
ANNOT_UNSAVED_TITLE = "未保存的标注"
ANNOT_UNSAVED_PROMPT_TEMPLATE = (
    "图片「{name}」有尚未保存的标注改动。\n"
    "切换图片将丢失这些改动，是否继续？"
)
ANNOT_UNSAVED_SAVE = "保存并切换"
ANNOT_UNSAVED_DISCARD = "放弃改动并切换"
ANNOT_UNSAVED_CANCEL = "取消"

# 训练 / 转换 页（Phase 3）
TRAIN_SECTION_CONVERT = "数据集转换"
TRAIN_SECTION_PARAMS = "模型超参数"
TRAIN_SECTION_LOG = "训练日志"
TRAIN_TAB_OVERVIEW = "统一 9 类模型（FP + A 合并）· YOLOv8 检测 + TinyConv 亮灭分类"
TRAIN_BTN_GENDATA = "① 生成统一标注"
TRAIN_BTN_TRAIN_YOLO = "② 训练检测模型"
TRAIN_BTN_MERGE_ROI = "③ 合并亮灭数据"
TRAIN_BTN_TRAIN_CLS = "④ 训练分类器"
TRAIN_BTN_CONVERT = "⑤ 量化转换模型"
TRAIN_BTN_ONECLICK = "▶ 一键完整流程（含量化）"
TRAIN_BTN_STOP = "■ 停止"
TRAIN_BTN_ADVANCED = "高级·单步 ▼"
TRAIN_HINT_RUNNING = "任务运行中，请勿重复启动…"
TRAIN_HINT_IDLE = "点击按钮启动子进程训练，日志实时回显"
TRAIN_HINT_STOPPED = "已被手动停止"
TRAIN_HINT_STOPPING = "正在停止…"
TRAIN_DONE = "✅ 流程完成（耗时 {sec}s）"
TRAIN_FAILED = "❌ 流程失败：{reason}"
TRAIN_STARTING = "── 开始运行：{cmd} ──"
TRAIN_RUNNING = "训练模块"

# ---- 训练页 · 状态 / 进度区（深度优化） --------------------------------------
TRAIN_SECTION_STATUS = "训练状态"
TRAIN_STAGE_IDLE = "空闲"
TRAIN_STAGE_NAMES = {
    "DATA": "生成统一标注",
    "YOLO": "训练检测模型",
    "ROI": "合并亮灭数据",
    "CLS": "训练分类器",
    "CONVERT": "量化转换模型",
}
TRAIN_STATUS_STAGE = "阶段：{stage}"
TRAIN_STATUS_BUSY = "运行中… {elapsed}"
TRAIN_STATUS_ETA_IDLE = "待命"
TRAIN_STATUS_EPOCH = "第 {cur}/{total} 轮 · 已用 {elapsed} · 剩余 {eta}"
TRAIN_METRICS_EMPTY = "指标：--"
TRAIN_METRICS = "指标：mAP {m} · P {p} · R {r} · F1 {f}"
TRAIN_STAGE_DONE_TEMPLATE = "✅ 阶段「{stage}」完成，耗时 {sec}s"
TRAIN_STAGE_FAILED = "❌ 阶段「{stage}」失败"

# ---- 训练页 · 自动部署（训练结束自动部署新模型到 ml/deploy/） ----------------
TRAIN_DEPLOY_START = "🚀 训练完成，开始自动部署新模型…"
TRAIN_DEPLOY_DONE = "✅ 模型已部署 → {dir}"
TRAIN_DEPLOY_FAILED = "❌ 部署失败：{reason}"

# ---- 训练页 · 数据集概览 / 环境检测（深度优化） -------------------------------
TRAIN_STOP_CONFIRM_TITLE = "确认停止"
TRAIN_STOP_CONFIRM_MSG = "确定要停止当前训练任务吗？已保存的 checkpoint 不会丢失。"
TRAIN_LOG_FILE_OPENED = "训练日志已写入：{path}"
TRAIN_DATASET_LABEL = "数据集"
TRAIN_DATASET_EMPTY = "尚未生成数据，请先运行「① 生成统一标注」"
TRAIN_DATASET_TEMPLATE = "train {tr} / val {va} / test {te} · 框 {boxes}"
TRAIN_BTN_REFRESH = "刷新概览"
TRAIN_DEVICE_LABEL = "设备"
TRAIN_DEVICE_EMPTY = "未检测，点击「检测环境」"
TRAIN_DEVICE_PROBING = "检测中…"
TRAIN_DEVICE_TEMPLATE = "{avail} · {name} ×{count} · 显存 {mem}G"
TRAIN_DEVICE_CPU = "CPU（未检测到 GPU）"
TRAIN_BTN_DEVICE = "检测环境"

# ---- 训练页 · 自动分配参数（深度优化 Phase 4） --------------------------------
TRAIN_BTN_RECOMPUTE = "重新评估"
TRAIN_AUTO_PROBING = "正在检测环境与数据集…"
TRAIN_AUTO_WAIT = "点击「开始」或「重新评估」，自动检测电脑配置与数据集规模并分配参数"
TRAIN_AUTO_SUMMARY = "模型 {phi} · 检测轮次 {yep} · 检测批次 {ybatch} · 分类轮次 {cep} · 分类批次 {cbatch}"
TRAIN_AUTO_NOTE_GPU = "检测到 GPU：{name}（{mem}G 显存）"
TRAIN_AUTO_NOTE_CPU = "未检测到 GPU，使用 CPU 训练（参数已调小）"
TRAIN_AUTO_NOTE_DATA = "训练集 {n} 图 → 检测轮次 {yep}、批次 {ybatch}"
TRAIN_AUTO_NOTE_EMPTY = "训练集尚未生成，按默认参数启动"

# ---- 训练页 · 数据集前置校验（启动前拦截，防止跑空失败） ----------------------
TRAIN_PRECHECK_TITLE = "无法启动训练"
TRAIN_PRECHECK_BLOCKED = "⛔ 训练未启动：{reason}"
ANNOT_OK_BTN = "知道了"

# ---- 训练页 · 部署后冒烟验证（自动部署后加载模型回测） ------------------------
TRAIN_SMOKE_START = "🔬 正在对部署产物做冒烟验证（加载 YOLO + 分类器跑图）…"
TRAIN_SMOKE_OK = "✅ 部署产物冒烟验证通过"
TRAIN_SMOKE_FAILED = "❌ 部署产物冒烟验证失败（exit={exit}），请检查训练产物"
