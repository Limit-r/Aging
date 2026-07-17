"""CellUIManager：cell 视觉状态统一管理器。

迁移自 d:\\Aging_backup_20260717\\app\\ui\\cell_ui_manager.py
"""

from __future__ import annotations

from typing import Optional

from app.services.cell_controller import DetectionState


# CellUIManager 公开常量（供调用方使用，避免散落字符串）
DETECT_RUNNING = DetectionState.RUNNING.value   # "running"
DETECT_PAUSED = DetectionState.PAUSED.value     # "paused"
DETECT_STOPPED = DetectionState.STOPPED.value   # "stopped"


class CellUIManager:
    """cell 视觉状态统一管理器（单例，MainWindow 持有）。

    不持有任何状态 —— 每次调用 apply_state 都是"无状态翻译"：
    输入 (cell, detection_state, expired_pending) → 输出 cell widget 视觉更新。
    """

    # 业务态 → DataCell.STATUS_* 字符串值（视觉字符串）
    # 注意：PAUSED → "online"（与 RUNNING 共用绿色边框，区分靠 set_expired_pending）
    _STATE_TO_STATUS: dict[str, str] = {
        DETECT_STOPPED: "no_data",
        DETECT_RUNNING: "online",
        DETECT_PAUSED:  "online",
    }

    def apply_state(
        self,
        cell,
        detection_state: str,
        *,
        expired_pending: bool = False,
    ) -> None:
        """应用 cell 视觉状态。

        Args:
            cell: DataCell widget（需要支持 update_status / set_expired_pending）
            detection_state: "stopped" / "running" / "paused"
            expired_pending: True 显示"归零闪烁"

        Raises:
            ValueError: detection_state 不是合法 DetectionState 值
        """
        if detection_state not in self._STATE_TO_STATUS:
            raise ValueError(
                f"CellUIManager.apply_state: unknown detection_state={detection_state!r}"
            )
        # 1) 边框 + 状态文字
        status = self._STATE_TO_STATUS[detection_state]
        cell.update_status(status)
        # 2) 归零闪烁
        if expired_pending:
            cell.set_expired_pending(True)
        else:
            cell.set_expired_pending(False)

    def status_for(self, detection_state: str) -> Optional[str]:
        """查询某 detection_state 对应的视觉 status（供统计/测试用）。"""
        return self._STATE_TO_STATUS.get(detection_state)
