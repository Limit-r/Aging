"""老化自动检测：电流从 0 转稳定浮动 → 判定"已接入老化"（自动开始倒计时）。

业务语义（来自用户）：
- 一般情况下，ESP32 未接入设备老化时反馈电流 ≈ 0（空载）。
- 一旦回传电流开始**稳定浮动**（持续非零、高于空载阈值），判定该 CH 已在老化，
  触发 `triggered(cid)`，由调用方负责自动开始倒计时并把对应 CH 标记为检测中。

判定算法（过滤毛刺）：
- `idle`：电流 ≤ AUTO_IDLE_CURRENT_A（空载）。
- `active_confirm`：电流 ≥ AUTO_ACTIVE_CURRENT_A 连续 AUTO_CONFIRM_FRAMES 帧
  → 触发一次 `triggered(cid)`，进入 `active`。
- `active` → 若连续 AUTO_REARM_FRAMES 帧回到空载 → 回到 `idle`，允许下次再触发。

设计：
- 纯业务，可脱离 GUI 单测；不持有 controller/countdown，只发事件。
- 每 CH 独立状态，无共享锁（feed 由单线程数据流驱动）。
"""
from __future__ import annotations

from PyQt5.QtCore import QObject, pyqtSignal

from app.core import config


class AutoAgingDetector(QObject):
    """按 CH 检测电流"从空载到稳定有载"的自动老化判定器。"""

    # cid：检测到稳定电流、应自动开始倒计时的通道
    triggered = pyqtSignal(int)

    SIMPLE_STATE_IDLE = "idle"
    SIMPLE_STATE_ACTIVE = "active"

    def __init__(self, parent: "QObject | None" = None) -> None:
        super().__init__(parent)
        self._idle_a = config.AUTO_IDLE_CURRENT_A
        self._active_a = config.AUTO_ACTIVE_CURRENT_A
        self._confirm_frames = config.AUTO_CONFIRM_FRAMES
        self._rearm_frames = config.AUTO_REARM_FRAMES
        # cid -> 内部状态机
        self._state: dict[int, str] = {}
        self._active_streak: dict[int, int] = {}   # 连续有载帧
        self._idle_streak: dict[int, int] = {}     # 连续空载帧（用于 rearm）
        self._triggered_latch: dict[int, bool] = {}  # 当前 active 周期是否已触发

    # -- 主入口 -------------------------------------------------------------
    def feed(self, cid: int, currents) -> bool:
        """喂入一帧电流（currents 为 4 路数值的可迭代）。

        Returns:
            是否在本帧触发了 `triggered`。
        """
        if self._is_active(currents):
            self._idle_streak[cid] = 0
            self._active_streak[cid] = self._active_streak.get(cid, 0) + 1
            self._state[cid] = self.SIMPLE_STATE_ACTIVE
            # 连续 N 帧有载且本周期未触发 → 触发一次
            if (self._active_streak[cid] >= self._confirm_frames
                    and not self._triggered_latch.get(cid, False)):
                self._triggered_latch[cid] = True
                self._active_streak[cid] = 0  # 同名帧窗口避免重复触发
                self.triggered.emit(cid)
                return True
            return False
        # 空载：累计 idle 帧，用于 rearm
        self._active_streak[cid] = 0
        self._idle_streak[cid] = self._idle_streak.get(cid, 0) + 1
        if self._idle_streak[cid] >= self._rearm_frames:
            self._idle_streak[cid] = 0
            if self._state.get(cid) == self.SIMPLE_STATE_ACTIVE:
                self._state[cid] = self.SIMPLE_STATE_IDLE
                self._triggered_latch[cid] = False
        return False

    # -- 查询 ---------------------------------------------------------------
    def is_active(self, cid: int) -> bool:
        """当前是否处于"有载"判定中（不必已触发）。"""
        return self._state.get(cid) == self.SIMPLE_STATE_ACTIVE

    def reset(self, cid: int) -> None:
        """手动复位某 CH（如用户手动 stop 后），清空累计帧，允许下次再触发。"""
        self._state.pop(cid, None)
        self._active_streak.pop(cid, None)
        self._idle_streak.pop(cid, None)
        self._triggered_latch.pop(cid, None)

    def reset_all(self) -> None:
        self._state.clear()
        self._active_streak.clear()
        self._idle_streak.clear()
        self._triggered_latch.clear()

    # -- 内部 ---------------------------------------------------------------
    def _is_active(self, currents) -> bool:
        """4 路电流中存在任一路超过有载阈值即判定为"有载"。"""
        return any(c > self._active_a for c in currents)