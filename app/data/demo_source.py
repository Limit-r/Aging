"""v3.0 模拟数据源（Phase A.4 demo）。

每 2s 推一组 72 通道电流读数，让 CurrentPage 看到"实时数据"。

数据特征：
- 每路电流基线 0.5 ~ 4.5 A（每 cell 不同，给视觉变化）
- 随机波动 ±0.15 A（正常）
- 每 ~30 帧（约 60s）随机选 1 个 cell 制造一次"尖峰"（5.5~6.0 A 触发告警）

接口：
- batch_reading(List[ChannelReading]) 信号：每帧推一次
- start() / stop()：控制推送
- pause()：暂停但保留 timer
"""

from __future__ import annotations

import random
import time
from typing import List, Optional

from PyQt5.QtCore import QObject, QTimer, pyqtSignal

from app.core import config
from app.data.protocol import ChannelReading, now_ms
from app.observability import get_logger, narrative


_log = get_logger("app.data.demo_source")


class DemoDataSource(QObject):
    """模拟数据源：每 2s 推一组 72 cell 电流。"""

    batch_reading = pyqtSignal(list)  # List[ChannelReading]

    def __init__(
        self,
        total: int = None,
        interval_ms: int = 2000,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self._total = total or (config.GRID_ROWS * config.GRID_COLS)
        self._interval_ms = interval_ms
        self._frame_count = 0
        self._paused = False
        # 每 cell 每路基线电流（4×72），让数据看起来不同
        self._baselines = [
            [
                round(random.uniform(0.5, 4.5), 2)
                for _ in range(4)
            ]
            for _ in range(self._total + 1)  # index 0 留空，1..total
        ]
        # QTimer
        self._timer = QTimer(self)
        self._timer.setInterval(self._interval_ms)
        self._timer.timeout.connect(self._emit_batch)
        _log.info(
            "DemoDataSource created: total=%s interval=%sms",
            self._total, self._interval_ms,
        )

    # -- 控制 ----------------------------------------------------------------
    def start(self) -> None:
        if not self._timer.isActive():
            self._timer.start()
            narrative.event(
                "demo_data_source_start",
                total=self._total,
                interval_ms=self._interval_ms,
                note="demo 数据源启动",
            )
            _log.info("demo source started")

    def stop(self) -> None:
        if self._timer.isActive():
            self._timer.stop()
            narrative.event(
                "demo_data_source_stop",
                total_frames=self._frame_count,
                note=f"demo 数据源停止（已推 {self._frame_count} 帧）",
            )
            _log.info("demo source stopped (frames=%s)", self._frame_count)
        self._frame_count = 0

    def pause(self) -> None:
        if self._timer.isActive():
            self._timer.stop()
            self._paused = True
            _log.info("demo source paused")

    def resume(self) -> None:
        if self._paused and not self._timer.isActive():
            self._timer.start()
            self._paused = False
            _log.info("demo source resumed")

    @property
    def total(self) -> int:
        return self._total

    @property
    def is_running(self) -> bool:
        return self._timer.isActive() and not self._paused

    def set_running(self, cids) -> None:
        """Phase A.7：设置"运行中" cell 集合，spike 限定在集合内随机。
        cids: Iterable[int]，如 [1, 2, 3, 4]
        """
        self._running_cids = set(cids)
        _log.info("demo running cells updated: %s", sorted(self._running_cids))

    def get_running_cids(self) -> set:
        """Phase 1.28：暴露 running cells 集合，供电流检测页做异常检测双重保险。

        返回当前被标记为"运行中"的 cid 集合。如果从未调用过 set_running，返回空集。
        """
        if not hasattr(self, "_running_cids"):
            return set()
        return set(self._running_cids)

    # -- 内部 ----------------------------------------------------------------
    def _emit_batch(self) -> None:
        self._frame_count += 1
        ts = now_ms()
        # 偶发异常：每 30 帧（约 60s）随机 1 个 cell 拉高到 5.5~6.0A
        # random.choice 要求序列参数，set 不可下标，需 list(...) 包装
        spike_cid = None
        running_list = list(self._running_cids)
        if running_list and self._frame_count > 0 and self._frame_count % 30 == 0:
            spike_cid = random.choice(running_list)
            _log.info("demo spike injected at cid=%s (in running cells)", spike_cid)
        # 生成 72 个 reading
        readings: List[ChannelReading] = []
        for cid in range(1, self._total + 1):
            currents = self._generate_currents(cid, spike_cid=spike_cid)
            readings.append(ChannelReading(
                channel_id=cid,
                timestamp_ms=ts,
                currents=tuple(currents),
            ))
        # 一次性 emit
        self.batch_reading.emit(readings)

    def _generate_currents(
        self, cid: int, spike_cid: Optional[int] = None,
    ) -> List[float]:
        """生成 1 个 cell 的 4 路电流（基于基线 + 随机波动）。"""
        if cid == spike_cid:
            # 制造尖峰：4 路都拉到 5.5~6.0A
            return [round(random.uniform(5.5, 6.0), 2) for _ in range(4)]
        # 正常：基线 ± 0.15
        baseline = self._baselines[cid]
        return [
            round(max(0.0, min(5.0, b + random.uniform(-0.15, 0.15))), 2)
            for b in baseline
        ]
