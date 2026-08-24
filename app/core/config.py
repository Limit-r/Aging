"""数值型配置常量：窗口尺寸、网格规格、阈值、刷新间隔。

字符串（用户可见文案）已迁到 `app.core.labels`。
颜色 / 字体 / 圆角 / 边距已迁到 `app.core.tokens`。
"""

# ---- 窗口几何 ---------------------------------------------------------------
WINDOW_SIZE = (2560, 1440)
MIN_WINDOW_SIZE = (1600, 900)

# ---- 左侧 9x8 数据网格 ------------------------------------------------------
GRID_ROWS = 9
GRID_COLS = 8
GRID_SPACING = 10
GRID_MARGINS = (24, 20, 24, 20)

# ---- 右侧按钮区几何 ---------------------------------------------------------
BUTTON_AREA_WIDTH = 260
BUTTON_AREA_MARGINS = (14, 16, 14, 16)
BUTTON_AREA_SPACING = 6
BUTTON_COUNT = 8   # 4 检测控制 + 4 批量（全选/全部开始/全部暂停/全部结束）

# ---- 单个数据通道内：1 行 4 列 = 4 个电流数据点 ---------------------------
DATA_POINTS_PER_ROW = 4
DATA_POINT_ROWS = 1
CURRENT_LABELS = ("I1", "I2", "I3", "I4")

# ---- 模拟数据参数 -----------------------------------------------------------
DATA_REFRESH_MS = 2000
ANOMALY_CURRENT_THRESHOLD = 4.5

# ---- NO_DATA 超时 ----------------------------------------------------------
NO_DATA_TIMEOUT_MS = 5000
NO_DATA_PLACEHOLDER = "---"

# ---- 历史缓冲 ---------------------------------------------------------------
HISTORY_FRAMES = 90   # 180s @ 2s/帧（详情页只显示最近 180 秒）
CHART_WINDOW_S = 180  # 折线图 X 轴范围（秒）

# ---- 倒计时（per-cell wall-clock 服务） -------------------------------------
COUNTDOWN_TICK_MS = 1000          # 倒计时推进间隔
DEFAULT_COUNTDOWN_SECONDS_MAIN = 2 * 60 * 60  # 主页面"开始"默认 2 小时 = 7200s
DEFAULT_COUNTDOWN_SECONDS_DETAIL = 30 * 60   # 详情页 spinbox 默认 30 分钟
COUNTDOWN_MAX_SECONDS = 24 * 60 * 60          # spinbox 上限 24h
COUNTDOWN_WARNING_THRESHOLD_S = 60            # 剩余 ≤60s 进入 warning 状态（黄/橙）

# ---- 日志 -------------------------------------------------------------------
LOG_DIR = "logs"
LOG_LEVEL = "DEBUG"  # DEBUG / INFO / WARNING / ERROR / CRITICAL
LOG_STATUS_BAR_TTL_MS = 5000  # 状态栏错误提示持续时间
TRAIN_STOP_GRACE_MS = 5000   # 停止训练：先 terminate，宽限 N ms 后仍未退出再 kill
TRAIN_ELAPSED_TICK_MS = 1000 # 训练页运行耗时 / ETA 刷新间隔
TRAIN_PROGRESS_PCT = 100     # 训练进度条满刻度百分比

# ---- 3D 视图交互反馈 --------------------------------------------------------
LED_FLASH_MS = 200             # 双击 LED → 详情页的视觉闪烁时长
PAGE_CHANGED_STATUS_MS = 2000  # 页面切换时状态栏消息持续时长

# ---- 54 路静默集中监控（monitor）-------------------------------------------
MONITOR_POLL_MS = 1000         # GUI 轮询 worker 聚合快照间隔
MONITOR_MAX_VIDEOS = 54        # 一次最多监控路数
MONITOR_FPS = 4                # 每路静默检测目标帧率
MONITOR_INPUT_TEXT = "320×320"  # 检测输入分辨率（与 worker MONITOR_INPUT_SHAPE 对齐）

# ---- 通道状态 → 文本颜色映射（用于 inline QSS） -----------------------------
# 注：这些值在 DataCell 头部状态文字需要 inline setStyleSheet；
# token 化后从 DEFAULT_TOKENS.colors 取
from app.core.tokens import DEFAULT_TOKENS as _TOKENS  # noqa: E402
COLOR_TEXT_OK = _TOKENS.colors.TEXT_NEON_GREEN
COLOR_TEXT_DANGER = _TOKENS.colors.TEXT_DANGER
COLOR_TEXT_DIM = _TOKENS.colors.TEXT_DIM
