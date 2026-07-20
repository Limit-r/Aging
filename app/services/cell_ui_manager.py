"""CellUIManager：cell 视觉状态统一管理器。

迁移自 d:\\Aging_backup_20260717\\app\\ui\\cell_ui_manager.py

Phase 5 M7 改造：_STATE_TO_STATUS 字典删除，统一走
labels.DETECTION_STATE_PRESENTATION（视觉 + 文本合并表）。
"""

from __future__ import annotations

from typing import Optional

from app.core import labels
from app.services.cell_controller import DetectionState


# CellUIManager 公开常量（供调用方使用，避免散落字符串）
DETECT_RUNNING = DetectionState.RUNNING.value   # "running"
DETECT_PAUSED = DetectionState.PAUSED.value     # "paused"
DETECT_STOPPED = DetectionState.STOPPED.value   # "stopped"


class CellUIManager:
    """cell 视觉状态统一管理器（单例，MainWindow 持有）。

    不持有任何状态 —— 每次调用 apply_state 都是"无状态翻译"：
    输入 (cell, detection_state, expired_pending) → 输出 cell widget 视觉更新。

    视觉 / 文本映射统一来自 labels.DETECTION_STATE_PRESENTATION，
    本类不再维护独立的 _STATE_TO_STATUS 字典。
    """

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
        presentation = labels.DETECTION_STATE_PRESENTATION.get(detection_state)
        if presentation is None:
            raise ValueError(
                f"CellUIManager.apply_state: unknown detection_state={detection_state!r}"
            )
        # 1) 边框 + 状态文字（视觉 status 来自 presentation）
        cell.update_status(presentation.visual_status)
        # 2) 归零闪烁
        if expired_pending:
            cell.set_expired_pending(True)
        else:
            cell.set_expired_pending(False)

    def status_for(self, detection_state: str) -> Optional[str]:
        """查询某 detection_state 对应的视觉 status（供统计/测试用）。"""
        presentation = labels.DETECTION_STATE_PRESENTATION.get(detection_state)
        return presentation.visual_status if presentation else None

    def text_for(self, detection_state: str) -> Optional[str]:
        """查询某 detection_state 对应的用户可见中文文本（供 detail_page 等）。"""
        presentation = labels.DETECTION_STATE_PRESENTATION.get(detection_state)
        return presentation.text_label if presentation else None
