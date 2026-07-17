"""自然语言化 + 结构化日志工具。

将代码化的日志（缩写 / 数字 / 内部表示）翻译成"开发者友好"的中文叙述，
同时保留 key=value 结构便于 grep / 解析。

设计目标
--------
1. **自然语言**：状态名翻译成中文，秒数转成「小时分秒」，缩写 r/p/s 展开
2. **结构化**：event=xxx actor=xxx channel=N from=停止 to=运行中 形式
3. **可读性**：单行能读完一个事件，不需要查代码

典型用法
--------
```python
from app.observability import narrative as nv

# 业务事件
nv.event("cell_state_change", actor="user_start_all", channel=1,
         from_="stopped", to="running")

# 倒计时
nv.event("countdown_started", channel=16, duration=1800, total_running=1)

# 状态机聚合
nv.event("batch_action", action="start", actor="user", requested=72,
         transitioned=70, skipped=2)
```

输出示例
--------
```
event=cell_state_change actor=user_start_all channel=1 from=停止 to=运行中
event=countdown_started channel=16 duration=30分钟 (1800s) total_running=1
event=batch_action action=start actor=user requested=72 transitioned=70 skipped=2
```

落盘
----
所有 event() 调用走 _log.info()，自然进入 file handler (DEBUG+) + console handler (INFO+)。
"""

from typing import Any

from app.core.formatting import format_cid
from app.observability.log_signals import LogLevel
from app.observability.logger import get_logger


_log = get_logger("app.narrative")


# ---- 枚举值 → 自然语言映射 ---------------------------------------------------
_STATE_ZH = {
    # cell_controller.DetectionState
    "stopped": "已停止",
    "running": "运行中",
    "paused":  "已暂停",
    # countdown.CountdownService
    "idle":     "未启动",
    "warning":  "即将到期",
    "expired":  "已到期",
}

_ACTION_ZH = {
    "start":  "启动",
    "pause":  "暂停",
    "resume": "恢复",
    "stop":   "停止",
}

_ACTOR_ZH = {
    "user":               "用户",
    "user_start_all":     "用户-全部开始",
    "user_pause_all":     "用户-全部暂停",
    "user_resume_all":    "用户-全部恢复",
    "user_stop_all":      "用户-全部停止",
    "user_start_button":  "用户-单cell开始",
    "user_pause_button":  "用户-单cell暂停",
    "user_resume_button": "用户-单cell恢复",
    "user_stop_button":   "用户-单cell停止",
    "detail_window":      "详情页",
    "detail_start":       "详情页-开始",
    "detail_cancel":      "详情页-取消",
    "countdown_expired":  "倒计时-到期",
    "system":             "系统",
    "system_close":       "系统-关闭",
}


# ---- 工具函数 ---------------------------------------------------------------
def state_zh(s: str) -> str:
    """状态枚举值 → 中文。例：'running' → '运行中'"""
    return _STATE_ZH.get(s, s)


def action_zh(a: str) -> str:
    """动作 → 中文。例：'start' → '启动'"""
    return _ACTION_ZH.get(a, a)


def actor_zh(a: str) -> str:
    """触发者 → 中文。例：'user_start_all' → '用户-全部开始'"""
    return _ACTOR_ZH.get(a, a)


def format_duration(seconds: int) -> str:
    """秒数 → 自然语言。例：7183 → '1小时59分43秒 (7183s)'"""
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    parts: list[str] = []
    if h:
        parts.append(f"{h}小时")
    if m:
        parts.append(f"{m}分")
    if s or not parts:
        parts.append(f"{s}秒")
    return f"{''.join(parts)} ({seconds}s)"


def format_counts(r: int, p: int, s: int) -> str:
    """状态计数器 → 自然语言。例：(1, 0, 71) → '1个运行中 / 0个暂停 / 71个已停止'"""
    return f"{r}个运行中 / {p}个暂停 / {s}个已停止"


def format_cids(cids) -> str:
    """cid 列表 → 自然语言。例：[1, 2, 3] → 'CH-01,CH-02,CH-03'"""
    if not cids:
        return "无"
    return ",".join(format_cid(c) for c in cids)


# ---- 字段值格式化（自动识别语义） -------------------------------------------
# 哪些 key 自动翻译（其他原样输出）
_STATE_KEYS = {"from_", "from", "to", "state", "old", "new"}
_ACTION_KEYS = {"action"}
_ACTOR_KEYS = {"actor"}
_DURATION_KEYS = {"duration", "remain", "elapsed"}
# 列表语义：传 list/tuple 时展开为 CH-XX，传 int 时按"X个"格式
_CID_LIST_KEYS = {"channels", "cids", "skipped", "transitioned"}
# 数量语义：任何数字都按"X"格式
_COUNT_KEYS = {"requested", "selected", "n", "count", "total"}


def _format_value(key: str, value: Any) -> str:
    """根据 key 决定 value 的格式化方式。"""
    base_key = key.rstrip("_")
    # 状态 key：支持 enum（自动 .value）和 str
    if base_key in _STATE_KEYS:
        if hasattr(value, "value"):  # enum 兼容
            value = value.value
        if isinstance(value, str):
            return state_zh(value)
        return str(value)
    if base_key in _ACTION_KEYS and isinstance(value, str):
        return action_zh(value)
    if base_key in _ACTOR_KEYS and isinstance(value, str):
        return actor_zh(value)
    if base_key in _DURATION_KEYS and isinstance(value, (int, float)):
        return format_duration(int(value))
    if base_key in _CID_LIST_KEYS:
        if isinstance(value, (list, tuple, set)):
            return format_cids(value)
        if isinstance(value, (int, float)):
            # 0 或 N 统一为数字（避免 0 → CH-00；note 里通常带"个 cell"）
            return str(int(value))
    if base_key in _COUNT_KEYS and isinstance(value, (int, float)):
        return str(int(value))
    return str(value)


def format_event(name: str, **fields: Any) -> str:
    """组装 event 行。例：

    format_event("cell_state_change", actor="user", channel=1,
                 from_="stopped", to="running", counts=(1, 0, 71))
    → "event=cell_state_change actor=用户 channel=1 from=停止 to=运行中 counts=1个运行中 / 0个暂停 / 71个已停止"
    """
    parts: list[str] = [f"event={name}"]
    for k, v in fields.items():
        base_key = k.rstrip("_")
        if base_key == "counts" and isinstance(v, tuple) and len(v) == 3:
            formatted = format_counts(*v)
        else:
            formatted = _format_value(k, v)
        parts.append(f"{base_key}={formatted}")
    return " ".join(parts)


def event(name: str, level: int = LogLevel.INFO, **fields: Any) -> None:
    """输出结构化 + 自然语言化的事件日志。默认 INFO 级别（控制台可见）。

    字段 key 自动按语义翻译：
    - actor    → 中文（"user_start_all" → "用户-全部开始"）
    - from/to  → 中文（"running" → "运行中"）
    - duration → 自然语言（1800 → "30分钟 (1800s)"）
    - cids     → 中文（[1,2] → "CH-01,CH-02"）
    """
    msg = format_event(name, **fields)
    if level >= LogLevel.CRITICAL:
        _log.critical(msg)
    elif level >= LogLevel.ERROR:
        _log.error(msg)
    elif level == LogLevel.WARNING:
        _log.warning(msg)
    elif level == LogLevel.INFO:
        _log.info(msg)
    else:
        _log.debug(msg)
