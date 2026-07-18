"""全局历史数据环形缓冲（按 channel_id 索引）。

设计要点：
- 容量 = HISTORY_FRAMES（默认 90 帧 = 180s @ 2s/帧，对应详情页只显示最近 180 秒）
- 每帧存完整 ChannelReading
- append(reading) O(1)
- snapshot(cid) 返回该 channel 的 (timestamps, currents_matrix)
  - currents_matrix: shape (4, N) 用于 I-t 曲线
- 详情页订阅 append 信号即可

线程安全：append 由 MainWindow 接收 on_reading 时调用（来自 DataSource 线程），
读取 snapshot 由 UI 线程调用。GIL + collections.deque + 不可变 NamedTuple 足够。

日志策略：使用 30s 周期定时器（_SUMMARY_INTERVAL_MS）输出 1 条聚合 summary，
不再在每 100 帧触发 DEBUG。Summary 包含总 appends、平均长度、最后 cid。
"""

import collections
from typing import Deque, List, Optional, Tuple

from PyQt5.QtCore import QObject, QTimer, pyqtSignal

from app.core import config
from app.data.protocol import ChannelReading
from app.observability import get_logger


_log = get_logger("app.data.history_buffer")


class HistoryBuffer(QObject):
    """单实例全局缓冲，72 通道共享。继承 QObject 以承载内部 30s summary timer。"""

    # Phase 3：详情页订阅此信号实现事件驱动重绘
    # 信号名用过去式（与 CellController.state_changed 风格一致），
    # 避免与同名方法 append() 冲突（PyQt5 类内同名 method 会覆盖 signal 描述符）。
    appended = pyqtSignal(object)  # ChannelReading

    _SUMMARY_INTERVAL_MS = 30_000  # 30s 1 条聚合 summary

    def __init__(
        self,
        channel_count: int,
        capacity: Optional[int] = None,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self._capacity = capacity or config.HISTORY_FRAMES
        self._buffers: dict[int, Deque[ChannelReading]] = {
            cid: collections.deque(maxlen=self._capacity)
            for cid in range(1, channel_count + 1)
        }
        self._append_count = 0
        self._last_cid: Optional[int] = None
        # 30s 周期 timer：输出 1 条聚合 summary（取代原"每 100 帧 1 条"）
        self._summary_timer = QTimer(self)
        self._summary_timer.setInterval(self._SUMMARY_INTERVAL_MS)
        self._summary_timer.timeout.connect(self._log_summary)
        self._summary_timer.start()
        _log.info("HistoryBuffer created (channels=%s, capacity=%s, summary=%ds)",
                  channel_count, self._capacity,
                  self._SUMMARY_INTERVAL_MS // 1000)

    def append(self, reading: ChannelReading) -> None:
        self._buffers[reading.channel_id].append(reading)
        self._append_count += 1
        self._last_cid = reading.channel_id
        # Phase 3：emit appended 信号供详情页事件驱动重绘
        # Qt signal emit 是 noop 若无 slot 连接，零成本
        self.appended.emit(reading)
        # 不再每 100 帧打 DEBUG；由 _summary_timer 每 30s 统一打 1 条

    def _log_summary(self) -> None:
        """30s 周期 summary：总 appends + 平均 buffer 长度 + channels + last_cid。"""
        if self._append_count == 0:
            return
        total_len = sum(len(buf) for buf in self._buffers.values())
        avg_len = total_len / len(self._buffers) if self._buffers else 0
        _log.debug(
            "history_buffer: total=%d, avg_len=%.1f, channels=%d, last_cid=%s",
            self._append_count, avg_len, len(self._buffers), self._last_cid,
        )

    def snapshot(
        self, channel_id: int
    ) -> Tuple[List[float], List[List[float]]]:
        """返回 (相对秒数列表, currents[4][N])。

        相对时间 = 第一个数据点为 0 秒。N 最多为 capacity。
        """
        buf = self._buffers[channel_id]
        if not buf:
            return [], [[] for _ in range(4)]

        t0_ms = buf[0].timestamp_ms
        ts: List[float] = []
        currents: List[List[float]] = [[] for _ in range(4)]
        for r in buf:
            ts.append((r.timestamp_ms - t0_ms) / 1000.0)
            for i in range(4):
                currents[i].append(r.currents[i])
        return ts, currents

    def clear(self, channel_id: int) -> None:
        before = len(self._buffers[channel_id])
        self._buffers[channel_id].clear()
        _log.info("clear cid=%s (dropped %d frames)", channel_id, before)
