"""数据契约：DataSource Protocol + ChannelReading + ChannelStatus。

数据流：
  ┌─────────────────┐
  │   DataSource    │── on_reading(ChannelReading) ──→ 业务侧
  │ (Mock / File /  │
  │  Serial / ...)  │
  └─────────────────┘

通道状态（NO_DATA/ONLINE/ANOMALY）由业务侧（MainWindow）根据
"该 cell 的检测状态"完全控制，DataSource 不再推 status。
但 ChannelStatus enum 仍保留供 widget 使用。
"""

import enum
import time
from typing import Callable, NamedTuple, Protocol, runtime_checkable


# ---- 通道状态枚举 -----------------------------------------------------------
class ChannelStatus(enum.Enum):
    """单个通道的视觉状态（与 DataCell.set_status 一一对应）。"""
    ONLINE = "online"        # 正常
    ANOMALY = "anomaly"      # 数据超阈值
    NO_DATA = "no_data"      # 无数据：启动前/超时/结束检测
    OFFLINE = "offline"      # 通道未启用/初始


# ---- 数据载体 ----------------------------------------------------------------
class ChannelReading(NamedTuple):
    """一帧完整读数。"""
    channel_id: int
    timestamp_ms: int
    currents: tuple


# ---- 回调签名 ----------------------------------------------------------------
Subscriber = Callable[[ChannelReading], None]


# ---- 时间辅助 ----------------------------------------------------------------
def now_ms() -> int:
    return int(time.time() * 1000)


# ---- 协议 --------------------------------------------------------------------
@runtime_checkable
class DataSource(Protocol):
    """数据源协议。任何数据源实现都需满足此接口。

    通道状态（NO_DATA/ONLINE/ANOMALY/OFFLINE）由业务侧按 cell 控制，
    DataSource 只负责推数据。
    """

    def start(self) -> None:
        """启动推送线程 / 打开数据通道。"""
        ...

    def stop(self) -> None:
        """停止推送。"""
        ...

    def subscribe(self, callback: Subscriber) -> None:
        """订阅读数。"""
        ...
