"""CellController：72 cell 状态机的真理源。纯业务，可脱离 GUI 单测。

迁移自 d:\\Aging_backup_20260717\\app\\services\\cell_controller.py
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, Iterable, List, Optional

from PyQt5.QtCore import QObject, pyqtSignal

from app.observability import get_logger, narrative
from app.observability.log_signals import LogLevel


_log = get_logger("app.services.cell_controller")


class DetectionState(Enum):
    STOPPED = "stopped"
    RUNNING = "running"
    PAUSED = "paused"


# 转移表：哪些 (action, 当前状态) 是合法的
# 命中则转为右侧状态；未命中 = 该 cell 对此 action 无效
_STATE_TRANSITIONS: Dict[str, Dict[DetectionState, DetectionState]] = {
    "start":  {DetectionState.STOPPED: DetectionState.RUNNING},
    "pause":  {DetectionState.RUNNING: DetectionState.PAUSED},
    "resume": {DetectionState.PAUSED:  DetectionState.RUNNING},
    "stop":   {
        DetectionState.RUNNING: DetectionState.STOPPED,
        DetectionState.PAUSED:  DetectionState.STOPPED,
    },
}


class CellController(QObject):
    """72 cell 状态机的真理源。纯业务，可脱离 GUI 单测。"""

    # cid, old.value, new.value
    state_changed = pyqtSignal(int, str, str)

    def __init__(self, total: int, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._total = total
        self._states: Dict[int, DetectionState] = {
            cid: DetectionState.STOPPED for cid in range(1, total + 1)
        }
        self._counts = {"running": 0, "paused": 0, "stopped": total}
        # 详情页「开始」触发的自定义倒计时秒数：apply 前写入，state_changed slot 内 take
        self._pending_countdown: Dict[int, int] = {}

    # -- 查询 API ----------------------------------------------------------
    @property
    def total(self) -> int:
        return self._total

    def state_of(self, cid: int) -> DetectionState:
        return self._states.get(cid, DetectionState.STOPPED)

    def n_running(self) -> int:
        return self._counts["running"]

    def n_paused(self) -> int:
        return self._counts["paused"]

    def n_stopped(self) -> int:
        return self._counts["stopped"]

    def count_actionable(self, action: str, cids: Iterable[int]) -> int:
        """cids 中可被 action 转移的 cell 数。"""
        return len(self.actionable_cids(action, cids))

    def actionable_cids(self, action: str, cids: Iterable[int]) -> List[int]:
        """cids 中可被 action 转移的子集。"""
        valid = set(_STATE_TRANSITIONS.get(action, {}).keys())
        return [cid for cid in cids if self._states.get(cid) in valid]

    def take_pending_countdown(self, cid: int, default: int) -> int:
        """取出某 cid 的自定义倒计时秒数（取后即清）。"""
        return self._pending_countdown.pop(cid, default)

    # -- 写 API ------------------------------------------------------------
    def apply(
        self,
        action: str,
        cids: Iterable[int],
        *,
        countdown_seconds: Optional[int] = None,
    ) -> List[int]:
        """对 cids 执行 action。返回成功转移的 cid 列表。"""
        transitions = _STATE_TRANSITIONS.get(action, {})
        transitioned: List[int] = []
        invalid: List[tuple[int, DetectionState]] = []
        for cid in cids:
            old = self._states.get(cid)
            if old is None:
                _log.warning(
                    "event=cell_state_apply action=%s cid=CH-%s reason=unknown_cid",
                    action, cid,
                )
                continue
            new = transitions.get(old)
            if new is None or new == old:
                invalid.append((cid, old))
                continue
            self._states[cid] = new
            self._update_counts(old, new)
            self.state_changed.emit(cid, old.value, new.value)
            transitioned.append(cid)
        # 收尾：成功转移 1 条聚合 event
        if transitioned:
            narrative.event(
                "cell_state_apply",
                level=LogLevel.DEBUG,
                action=action,
                transitioned=transitioned,
                counts=(
                    self._counts["running"], self._counts["paused"],
                    self._counts["stopped"],
                ),
                note=f"成功转移 {len(transitioned)} 个 cell",
            )
            if countdown_seconds is not None:
                for cid in transitioned:
                    self._pending_countdown[cid] = countdown_seconds
        # 收尾：聚合 invalid 日志
        if len(invalid) == 1:
            cid, old = invalid[0]
            _log.debug(
                "event=cell_state_apply action=%s cid=CH-%s reason=invalid_transition current_state=%s",
                action, cid, old.value,
            )
        elif len(invalid) > 1:
            narrative.event(
                "cell_state_apply_invalid",
                level=LogLevel.DEBUG,
                action=action,
                skipped=[c for c, _ in invalid],
                note=f"{len(invalid)} 个 cell 状态不兼容，已跳过",
            )
        if not transitioned:
            narrative.event(
                "cell_state_apply",
                level=LogLevel.DEBUG,
                action=action,
                note="无任何 cell 转移（全部无效或 cid 未知）",
            )
        return transitioned

    # -- 内部 --------------------------------------------------------------
    def _update_counts(self, old: DetectionState, new: DetectionState) -> None:
        self._counts[old.value] -= 1
        self._counts[new.value] += 1
