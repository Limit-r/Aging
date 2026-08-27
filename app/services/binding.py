"""设备绑定（会话内存模型）——不落盘，重启即恢复默认。

业务语义（来自用户澄清）：
- **每个 CH 位点绑定一台 ESP32 摄像头**（默认 `CAM-{cid:02d}`，可改）。
- **每 6 个 CH 绑定一台回传电流数据的 ESP32**，电流 ESP 按 **3 行 × 2 列** 布局：
  在 9×8 网格中恰好铺成 3×4=12 个电流单元，每单元覆盖 6 通道。
      单元索引（row-major）：`(行块 × units_per_row) + 列块`

设计：
- 纯业务，可脱离 GUI 单测；会话内单例（`get_binding()`）。
- 只维护「覆盖（override）」字典，未覆盖时返回默认值，满足最小改动。
- `changed` 信号供设置页/其它页面在会话内联动刷新。
"""
from __future__ import annotations

from PyQt5.QtCore import QObject, pyqtSignal

from app.core import config


# 电流单元分块尺寸：每单元 3 行 × 2 列 = 6 通道
BLOCK_ROWS = 3
BLOCK_COLS = 2

# 会话级单例（模块加载时惰性创建）
_BINDING_SESSION: "DeviceBinding | None" = None


class DeviceBinding(QObject):
    """72 通道设备绑定：摄像头归属 + 电流单元（3×2）分组。"""

    # 任一绑定变化时发出（payload 不含具体项，UI 全量刷新即可）
    changed = pyqtSignal()

    def __init__(self, parent: "QObject | None" = None):
        super().__init__(parent)
        self._grid_rows = config.GRID_ROWS
        self._grid_cols = config.GRID_COLS
        self._n = self._grid_rows * self._grid_cols
        self._unit_rows = BLOCK_ROWS
        self._unit_cols = BLOCK_COLS
        # 覆盖字典：cid -> 摄像头ID；unit_index -> 电流ESP ID
        self._camera_overrides: dict[int, str] = {}
        self._unit_overrides: dict[int, str] = {}

    # -- 几何属性 -----------------------------------------------------------
    @property
    def cell_count(self) -> int:
        return self._n

    @property
    def units_per_row(self) -> int:
        """一行放几个电流单元（列方向）：8/2 = 4。"""
        return self._grid_cols // self._unit_cols

    @property
    def units_per_col(self) -> int:
        """一列放几个电流单元（行方向）：9/3 = 3。"""
        return self._grid_rows // self._unit_rows

    @property
    def num_units(self) -> int:
        return self.units_per_col * self.units_per_row  # 3×4 = 12

    # -- 电流单元分组 ---------------------------------------------------------
    def unit_of(self, cid: int) -> "int | None":
        """cid(1..N) 所属电流单元索引（0-based）。越界返回 None。"""
        if not (1 <= cid <= self._n):
            return None
        row = (cid - 1) // self._grid_cols
        col = (cid - 1) % self._grid_cols
        rb = row // self._unit_rows
        cb = col // self._unit_cols
        return rb * self.units_per_row + cb

    def unit_cids(self, unit: int) -> list:
        """某电流单元覆盖的 cid 列表（升序，最多 6 个）。"""
        if not (0 <= unit < self.num_units):
            return []
        rb = unit // self.units_per_row
        cb = unit % self.units_per_row
        r0 = rb * self._unit_rows
        c0 = cb * self._unit_cols
        out = []
        for r in range(r0, r0 + self._unit_rows):
            for cc in range(c0, c0 + self._unit_cols):
                cid = r * self._grid_cols + cc + 1
                if 1 <= cid <= self._n:
                    out.append(cid)
        return sorted(out)

    def each_unit(self) -> list:
        """返回全部电流单元视图：[{index, id, cids}, ...]"""
        return [
            {"index": u, "id": self.unit_id(u), "cids": self.unit_cids(u)}
            for u in range(self.num_units)
        ]

    # -- 电流 ESP ID（每单元对应一台）----------------------------------------
    def default_unit_id(self, unit: int) -> str:
        return f"ESP-I{unit + 1:02d}"

    def unit_id(self, unit: int) -> str:
        return self._unit_overrides.get(unit, self.default_unit_id(unit))

    def set_unit_id(self, unit: int, value: str) -> None:
        value = (value or "").strip()
        if not value:
            value = self.default_unit_id(unit)
        if self.unit_id(unit) != value:
            self._unit_overrides[unit] = value
            self._emit_change()

    def reset_all_units(self) -> None:
        if self._unit_overrides:
            self._unit_overrides = {}
            self._emit_change()

    # -- 摄像头绑定（每 CH 一台）--------------------------------------------
    def default_camera_id(self, cid: int) -> str:
        return f"CAM-{cid:02d}"

    def camera_id(self, cid: int) -> str:
        return self._camera_overrides.get(cid, self.default_camera_id(cid))

    def set_camera_id(self, cid: int, value: str) -> None:
        value = (value or "").strip()
        if not value:
            value = self.default_camera_id(cid)
        if self.camera_id(cid) != value:
            self._camera_overrides[cid] = value
            self._emit_change()

    def reset_camera(self, cid: int) -> None:
        if self._camera_overrides.pop(cid, None) is not None:
            self._emit_change()

    def reset_all_cameras(self) -> None:
        if self._camera_overrides:
            self._camera_overrides = {}
            self._emit_change()

    def all_camera_ids(self) -> dict:
        return {cid: self.camera_id(cid) for cid in range(1, self._n + 1)}

    # -- 内部 ----------------------------------------------------------------
    def _emit_change(self) -> None:
        try:
            self.changed.emit()
        except RuntimeError:
            pass  # 退出阶段控件可能已销毁


def get_binding(parent: "QObject | None" = None) -> DeviceBinding:
    """会话级单例访问器（懒加载）。"""
    global _BINDING_SESSION
    if _BINDING_SESSION is None:
        _BINDING_SESSION = DeviceBinding(parent)
    return _BINDING_SESSION