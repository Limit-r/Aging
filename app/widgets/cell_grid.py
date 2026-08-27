"""72 cell 网格 + 选区（Phase A.8）。

设计：
- 9 列 × 8 行 = 72 个 DataCell（与 v3.0 主页 3D 视图对应）
- Phase A：去掉 QScrollArea，cell 缩小到 min(110, 64)，QGridLayout 自动撑满
- Phase A.8 选区逻辑：
    - 单击 = 单选（清空旧选区）
    - Shift+点击 = 连续选区（从 anchor 到当前 cid）
    - Ctrl+点击 = 切换（加入/移出选区）
    - Esc（外部） = 清空选区
- 选区变化 emit selection_changed 供工具条更新"已选 N 个"显示
"""

from __future__ import annotations

from typing import Dict, Optional, Set

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QWidget, QGridLayout,
)

from app.core import config
from app.data.protocol import ChannelReading
from app.services.cell_controller import DetectionState
from app.services.cell_ui_manager import CellUIManager
from app.widgets.data_cell import DataCell


class CellGrid(QWidget):
    """72 cell 网格 + 选区（Phase A.8）。"""

    H_SPACING = 6
    V_SPACING = 6
    MARGIN = 6

    # 选区变化信号（emit 选中的 cid 集合）
    selection_changed = pyqtSignal(set)
    # 双击 cell → 打开详情页（emit cid）
    cell_double_clicked = pyqtSignal(int)

    def __init__(
        self,
        total: int = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.setObjectName("cellGrid")
        self.setMouseTracking(True)  # 让 mouseMoveEvent 持续触发
        self._total = total or (config.GRID_ROWS * config.GRID_COLS)
        self._cells: Dict[int, DataCell] = {}
        self._ui_mgr = CellUIManager()
        # 选区状态
        self._selection: Set[int] = set()
        self._anchor_cid: Optional[int] = None
        self._build_ui()
        self._init_cells()

    def _build_ui(self) -> None:
        self._grid_layout = QGridLayout(self)
        self._grid_layout.setContentsMargins(
            self.MARGIN, self.MARGIN, self.MARGIN, self.MARGIN,
        )
        self._grid_layout.setHorizontalSpacing(self.H_SPACING)
        self._grid_layout.setVerticalSpacing(self.V_SPACING)
        for c in range(config.GRID_COLS):
            self._grid_layout.setColumnStretch(c, 1)
        for r in range(config.GRID_ROWS):
            self._grid_layout.setRowStretch(r, 1)

    def _init_cells(self) -> None:
        for cid in range(1, self._total + 1):
            cell = DataCell(cid, self)
            self._ui_mgr.apply_state(cell, DetectionState.STOPPED.value)
            # 选中/打开由 DataCell 信号驱动：DataCell 内部子控件已对鼠标透明，
            # 点击事件稳定落到 DataCell 本体（不再依赖 CellGrid.mousePress 里的
            # childAt 是否命中 DataCell，那方式点击会命中 QLabel 等子控件而失效）。
            cell.clicked.connect(self._on_cell_clicked)
            cell.double_clicked.connect(self._on_cell_double_clicked)
            self._cells[cid] = cell
            row = (cid - 1) // config.GRID_COLS
            col = (cid - 1) % config.GRID_COLS
            self._grid_layout.addWidget(cell, row, col)

    # -- 选区公共 API --------------------------------------------------------
    def selection(self) -> Set[int]:
        return set(self._selection)

    def clear_selection(self) -> None:
        if not self._selection:
            return
        self._selection.clear()
        self._anchor_cid = None
        self._apply_selection_visual()
        self.selection_changed.emit(set(self._selection))

    def select_all(self) -> None:
        """全选所有 CH（Ctrl+A 触发，用于全局批量操作）。"""
        self._selection = set(range(1, self._total + 1))
        self._anchor_cid = None
        self._apply_selection_visual()
        self.selection_changed.emit(set(self._selection))

    # -- 鼠标交互 ------------------------------------------------------------
    # 说明：fyv3.0 起，选中/打开不再通过 CellGrid.mousePressEvent + childAt 判断
    #（点击命中 DataCell 内部子控件时会判定失败），改由 DataCell 的 clicked /
    # double_clicked 信号驱动（见 _on_cell_clicked / _on_cell_double_clicked）。
    def _on_cell_clicked(self, cid: int, modifiers: int) -> None:
        """单击/多选 cell（Ctrl=切换 / Shift=连续 / 其他=单选）。"""
        mods = Qt.KeyboardModifiers(modifiers)
        if mods & Qt.ControlModifier:
            # Ctrl+点击：切换
            if cid in self._selection:
                self._selection.discard(cid)
            else:
                self._selection.add(cid)
            self._anchor_cid = cid
        elif mods & Qt.ShiftModifier:
            # Shift+点击：连续选区
            if self._anchor_cid is None:
                self._selection.add(cid)
                self._anchor_cid = cid
            else:
                start, end = sorted([self._anchor_cid, cid])
                for i in range(start, end + 1):
                    self._selection.add(i)
        else:
            # 单击：单选
            self._selection.clear()
            self._selection.add(cid)
            self._anchor_cid = cid
        self._apply_selection_visual()
        self.selection_changed.emit(set(self._selection))

    def _on_cell_double_clicked(self, cid: int) -> None:
        """双击 cell → 打开对应详情页（与 3D 视图双击语义一致）。"""
        self.cell_double_clicked.emit(cid)

    # -- 视觉同步 ------------------------------------------------------------
    def _apply_selection_visual(self) -> None:
        for cid, cell in self._cells.items():
            cell.set_selected(cid in self._selection)

    # -- 业务公共 API --------------------------------------------------------
    def cell(self, cid: int) -> Optional[DataCell]:
        return self._cells.get(cid)

    def update_cell_data(self, reading: ChannelReading) -> None:
        cell = self._cells.get(reading.channel_id)
        if cell is not None:
            cell.update_data(reading)

    def update_batch(self, readings) -> None:
        for r in readings:
            self.update_cell_data(r)

    def set_cell_state(self, cid: int, state: str) -> None:
        cell = self._cells.get(cid)
        if cell is not None:
            self._ui_mgr.apply_state(cell, state)
