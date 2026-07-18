"""3D 机柜视图（v3.0 主页核心）。

视觉：
- 1 个机柜面板（长方体线框），8 行 × 9 列 = 72 个 LED 灯点
- 背景网格 + 略带俯视的相机角度
- LED 颜色 = 通道状态（灰/绿/红/橙/青）
- 鼠标：左键拖拽旋转 / 滚轮缩放（GLViewWidget 内置）

实现：
- pyqtgraph.opengl.GLViewWidget（OpenGL viewport）
- GLGridItem（背景网格）
- GLLinePlotItem（机柜边框线框）
- GLScatterPlotItem（72 个 LED 点）
- GLTextItem（机柜标题 + 通道号标签）

依赖：PyOpenGL 3.1.x（已在 environment.yml 锁定）

设计原则：
- 单一职责：只管 3D 渲染，状态由上层 CellController 推入
- API 极简：set_led_state(cid, state)、set_all_leds_state(state)、
           set_leds_batch(state_dict)
- 信号：led_clicked(int) — 鼠标点击 LED 时发，参数为 cid（1..72）
       （Phase 1 仅占位实现，Phase 2 接入 CellController）
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, Optional

import numpy as np
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QCursor
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSizePolicy
from pyqtgraph.opengl import (
    GLViewWidget,
    GLGridItem,
    GLLinePlotItem,
    GLScatterPlotItem,
    GLTextItem,
)
import pyqtgraph as pg
from pyqtgraph import Vector

from app.core import config, labels
from app.core.formatting import format_cid
from app.core.tokens import DEFAULT_TOKENS
from app.observability import get_logger


_log = get_logger("app.ui.main_3d")


# ---- LED 状态枚举（与 CellController.DetectionState 对齐 + 扩展） --------
class LEDState(str, Enum):
    """LED 灯点状态。"""
    OFFLINE = "offline"     # 灰（停机/初始）
    RUNNING = "running"     # 绿（运行中）
    PAUSED = "paused"       # 青（已暂停）
    ALERT = "alert"         # 红（异常）
    WARNING = "warning"     # 橙（≤60s 警告）


# ---- 3D 场景几何常量 -------------------------------------------------------
GRID_ROWS = config.GRID_ROWS            # 8 行
GRID_COLS = config.GRID_COLS            # 9 列
LED_SPACING = 2.25                      # LED 间距（Phase 1.25 再放大 1.5×：1.5→2.25）
LED_SIZE = 0.675                        # 散点大小（Phase 1.25 再放大 1.5×：0.45→0.675）
PANEL_THICKNESS = 0.9                   # 机柜面板深度（Phase 1.25：0.6→0.9）
PANEL_PAD_X = 1.35                      # 面板左右留白（Phase 1.25：0.9→1.35）
PANEL_PAD_Y = 1.35                      # 面板上下留白（Phase 1.25：0.9→1.35）
CAMERA_DIST = 30.0                      # 初始相机距离（保持）
CAMERA_ELEV = 35.0                      # 俯视角（保持）
CAMERA_AZIM = 5.0                       # 方位角（保持）
CAMERA_CENTER = (0, 0.45, -3.6)           # 视角中心下移 Z（世界 Z ↓ = 屏幕 ↑，~500px）


class Rack3DView(QWidget):
    """3D 机柜视图（GLViewWidget + 72 LED + 机柜框 + 网格 + 标题）。"""

    # 鼠标点击 LED 时发出 cid（1..72）
    led_clicked = pyqtSignal(int)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._led_states: Dict[int, LEDState] = {
            cid: LEDState.OFFLINE for cid in range(1, GRID_ROWS * GRID_COLS + 1)
        }
        # Phase 3：最近一次 hover 命中的 cid（None = 未命中）
        # 供 HomeDashboard.eventFilter 在 MouseButtonDblClick 时读取
        self._best_hovered_cid: Optional[int] = None
        self._build_ui()
        self._build_scene()
        # 默认所有 LED 设为 OFFLINE
        self._refresh_led_colors()
        _log.info("Rack3DView initialized: %d rows x %d cols = %d LEDs",
                  GRID_ROWS, GRID_COLS, GRID_ROWS * GRID_COLS)

    # -- UI 布局 ---------------------------------------------------------------
    def _build_ui(self) -> None:
        # Phase 1.12：标题改由中央浮窗承载，Rack3DView 只负责 3D 渲染
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        # 3D 视口
        self._gl = GLViewWidget()
        self._gl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # 背景色
        bg = DEFAULT_TOKENS.colors.RACK_3D_BG
        self._gl.setBackgroundColor(bg[0] / 255.0, bg[1] / 255.0, bg[2] / 255.0, 1.0)
        layout.addWidget(self._gl, 1)

    # -- 3D 场景构建 -----------------------------------------------------------
    def _build_scene(self) -> None:
        # 1) 背景网格（XZ 平面，y=0 之下）
        grid = GLGridItem()
        grid_color = DEFAULT_TOKENS.colors.RACK_3D_GRID
        grid.setColor((grid_color[0] / 255.0,
                       grid_color[1] / 255.0,
                       grid_color[2] / 255.0,
                       0.5))
        grid.setSize(20, 20)
        grid.setSpacing(1, 1)
        grid.translate(0, -PANEL_THICKNESS - 0.1, 0)  # 放在面板下方
        self._gl.addItem(grid)

        # 2) 机柜面板：线框（12 条边）
        self._add_rack_frame()

        # 3) 72 个 LED（GLScatterPlotItem）
        #    pos:  shape (72, 3)
        #    size: shape (72,) per-point size
        #    color: shape (72, 4) per-point RGBA
        #    pxMode=True → 屏幕空间恒定像素大小（避免远小近大）
        self._led_positions = self._compute_led_positions()
        n = len(self._led_positions)
        self._led_colors = np.zeros((n, 4), dtype=np.float32)
        self._led_sizes = np.full(n, LED_SIZE * 30, dtype=np.float32)  # pxMode 缩放
        self._led_scatter = GLScatterPlotItem(
            pos=self._led_positions,
            size=self._led_sizes,
            color=self._led_colors,
            pxMode=True,
        )
        self._gl.addItem(self._led_scatter)
        # hover tooltip（Phase A.8.3：用 QTimer 50ms 轮询鼠标位置）
        self._hover_label = QLabel("", self)
        self._hover_label.setObjectName("hoverTooltip")
        self._hover_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._hover_label.hide()
        # 缓存 LED 2D 屏幕位置
        self._led_screen_pos: list = []
        self._proj_dirty = True
        # 定时器：50ms 轮询鼠标位置（GLViewWidget 没有 mouseMoved 信号）
        self._hover_timer = QTimer(self)
        self._hover_timer.setInterval(50)  # 20fps
        self._hover_timer.timeout.connect(self._tick_hover)
        self._hover_timer.start()

        # 4) 通道号标签（72 个，悬浮在 LED 下方/右侧）
        self._add_led_labels()

        # 5) 相机（传入 CAMERA_CENTER 让 3D 主体上移生效）
        self._gl.setCameraPosition(
            pos=Vector(*CAMERA_CENTER),
            distance=CAMERA_DIST,
            elevation=CAMERA_ELEV,
            azimuth=CAMERA_AZIM,
        )
        # Phase 3 fix：连 sigCameraChanged 让相机变化（拖拽/自动旋转/复位）
        # 立即标记 _proj_dirty，下一次 _tick_hover / pick_led_at 自动重算 LED 屏幕坐标
        if hasattr(self._gl, "sigCameraChanged"):
            self._gl.sigCameraChanged.connect(self._on_camera_changed)

    def _compute_led_positions(self) -> np.ndarray:
        """生成 72 个 LED 的 3D 坐标。

        返回 shape (72, 3) 的 numpy 数组，顺序与 cid 1..72 对应：
        - cid 1: 左下角 (row=GRID_ROWS-1, col=0)
        - cid 72: 右上角 (row=0, col=GRID_COLS-1)
        与 v2.0 MainWindow 9×8 网格"从右到左、从下到上"一致
        （保留用户已有的视觉锚定习惯）。
        """
        positions = np.zeros((GRID_ROWS * GRID_COLS, 3), dtype=np.float32)
        x_offset = -(GRID_COLS - 1) / 2.0
        y_offset = -(GRID_ROWS - 1) / 2.0
        idx = 0
        for row in range(GRID_ROWS):
            for col in range(GRID_COLS):
                # row 0 = 顶，row GRID_ROWS-1 = 底（与 v2.0 9×8 一致）
                y = (GRID_ROWS - 1 - row - (GRID_ROWS - 1) / 2.0) * LED_SPACING
                x = (col - (GRID_COLS - 1) / 2.0) * LED_SPACING
                z = PANEL_THICKNESS / 2.0 + 0.05  # 略浮于面板前
                positions[idx] = (x, y, z)
                idx += 1
        return positions

    def _add_rack_frame(self) -> None:
        """机柜面板线框（12 条边）+ 上下刻度边框（Phase 1.19）。"""
        # 面板尺寸（以 LED 阵列外缘 + padding）
        w = (GRID_COLS - 1) * LED_SPACING + 2 * PANEL_PAD_X
        h = (GRID_ROWS - 1) * LED_SPACING + 2 * PANEL_PAD_Y
        d = PANEL_THICKNESS
        hx, hy, hz = w / 2, h / 2, d / 2
        # 8 个顶点
        v = [
            (-hx, -hy, -hz), (+hx, -hy, -hz), (+hx, +hy, -hz), (-hx, +hy, -hz),
            (-hx, -hy, +hz), (+hx, -hy, +hz), (+hx, +hy, +hz), (-hx, +hy, +hz),
        ]
        # 12 条边（成对的索引）
        edges = [
            (0, 1), (1, 2), (2, 3), (3, 0),  # 后面 4 条
            (4, 5), (5, 6), (6, 7), (7, 4),  # 前面 4 条
            (0, 4), (1, 5), (2, 6), (3, 7),  # 连接前后 4 条
        ]
        edge_color = DEFAULT_TOKENS.colors.RACK_3D_PANEL_EDGE
        rgba = (edge_color[0] / 255.0,
                edge_color[1] / 255.0,
                edge_color[2] / 255.0,
                0.85)
        for a, b in edges:
            pts = np.array([v[a], v[b]], dtype=np.float32)
            line = GLLinePlotItem(
                pos=pts,
                color=rgba,
                width=2,
                mode="lines",
                antialias=True,
            )
            self._gl.addItem(line)
        # ---- 上下刻度边框（Phase 1.19 视觉增强）----------------------------
        # 在机柜面板外侧（顶部 +hy+offset / 底部 -hy-offset）画两条水平参考线
        # + 在参考线上均匀分布 8 个短刻度（垂直方向突出），模拟"工业刻度尺"
        tick_color = edge_color
        tick_rgba = (tick_color[0] / 255.0,
                     tick_color[1] / 255.0,
                     tick_color[2] / 255.0,
                     0.70)
        tick_offset_z = hz + 0.05  # 略浮于面板前
        tick_short_len = 0.15       # 短刻度突出长度
        # 8 个 x 位置（水平线上均匀分布）
        tick_xs = np.linspace(-hx + 0.4, +hx - 0.4, GRID_ROWS)
        for y_pos, direction in [(-hy - 0.20, "BOTTOM"), (+hy + 0.20, "TOP")]:
            # 1) 主水平参考线（贯穿整个机柜宽度）
            line_pts = np.array([
                [-hx, y_pos, tick_offset_z],
                [+hx, y_pos, tick_offset_z],
            ], dtype=np.float32)
            main_line = GLLinePlotItem(
                pos=line_pts, color=tick_rgba, width=1, mode="lines",
            )
            self._gl.addItem(main_line)
            # 2) 8 个短刻度（垂直方向，从主参考线向外突出）
            sign = +1.0 if direction == "TOP" else -1.0
            for x_pos in tick_xs:
                tick_pts = np.array([
                    [x_pos, y_pos, tick_offset_z],
                    [x_pos, y_pos + sign * tick_short_len, tick_offset_z],
                ], dtype=np.float32)
                tick_line = GLLinePlotItem(
                    pos=tick_pts, color=tick_rgba, width=1, mode="lines",
                )
                self._gl.addItem(tick_line)

    def _add_led_labels(self) -> None:
        """Phase 1.16：改为 hover 浮动显示，此函数保留为空以备扩展。"""
        return

    # -- 公共 API --------------------------------------------------------------
    def apply_breath(self, size_mul: float = 1.0, alpha_mul: float = 1.0) -> None:
        """Phase 1.15：LED 辉光呼吸（按 size/alpha 系数刷新散点）。

        size_mul  : 1.0× ~ 1.25×，影响每个 LED 视觉大小
        alpha_mul : 0.90 ~ 1.0，影响每个 LED 颜色 alpha
        """
        # 1) 刷新 size（按当前状态色映射 × size_mul）
        n = len(self._led_positions)
        base_size = LED_SIZE * 30  # pxMode 缩放基准
        self._led_sizes[:] = base_size * size_mul
        # 2) 刷新 alpha：取每 LED 当前颜色的 r/g/b，alpha 替换为 alpha_mul
        for cid in range(1, GRID_ROWS * GRID_COLS + 1):
            rgba = self._led_colors[cid - 1]
            self._led_colors[cid - 1, 3] = alpha_mul
        # 3) 推送到 GL（仅当有变化时调用）
        self._led_scatter.setData(
            pos=self._led_positions,
            size=self._led_sizes,
            color=self._led_colors,
        )

    def set_led_state(self, cid: int, state: LEDState) -> None:
        """设置单个 LED 状态。cid 范围 1..72。"""
        if cid < 1 or cid > GRID_ROWS * GRID_COLS:
            _log.warning("set_led_state: cid=%d out of range", cid)
            return
        if self._led_states.get(cid) == state:
            return
        self._led_states[cid] = state
        self._refresh_led_colors()

    def flash_led_alert(self, cid: int, duration_ms: int = 200) -> None:
        """Phase 3：临时把指定 LED 设为 ALERT 状态 duration_ms 毫秒后恢复。

        用于"双击 LED 进入详情页"的视觉反馈。
        注意：仅当 LED 真实状态不是 ALERT 时才临时闪烁（避免覆盖真实告警）。
        """
        if cid < 1 or cid > GRID_ROWS * GRID_COLS:
            return
        if self._led_states.get(cid) == LEDState.ALERT:
            return  # 不覆盖真实告警
        original = self._led_states.get(cid, LEDState.OFFLINE)
        self._led_states[cid] = LEDState.ALERT
        self._refresh_led_colors()
        # duration_ms 后恢复
        from PyQt5.QtCore import QTimer as _QTimer
        _QTimer.singleShot(
            duration_ms,
            lambda: self._restore_led(cid, original),
        )

    def _restore_led(self, cid: int, original: "LEDState") -> None:
        """恢复 LED 到原状态（flash_led_alert 用）。"""
        if cid < 1 or cid > GRID_ROWS * GRID_COLS:
            return
        self._led_states[cid] = original
        self._refresh_led_colors()

    def set_all_leds_state(self, state: LEDState) -> None:
        """批量设置所有 LED 同一状态。"""
        changed = False
        for cid in range(1, GRID_ROWS * GRID_COLS + 1):
            if self._led_states[cid] != state:
                self._led_states[cid] = state
                changed = True
        if changed:
            self._refresh_led_colors()

    def set_leds_batch(self, state_map: Dict[int, LEDState]) -> None:
        """批量设置多个 LED 状态。"""
        changed = False
        for cid, state in state_map.items():
            if (1 <= cid <= GRID_ROWS * GRID_COLS
                    and self._led_states.get(cid) != state):
                self._led_states[cid] = state
                changed = True
        if changed:
            self._refresh_led_colors()

    def led_state(self, cid: int) -> LEDState:
        return self._led_states.get(cid, LEDState.OFFLINE)

    @property
    def best_hovered_cid(self) -> Optional[int]:
        """最近一次 hover 命中的 LED cid（1..72）；无命中返回 None。

        Phase 3：HomeDashboard.eventFilter 在 MouseButtonDblClick 时读取，
        避免在双击瞬间重新做 ray-pick（_tick_hover 已每 50ms 更新一次）。
        """
        return self._best_hovered_cid

    # -- 鼠标 hover（Phase A.8.3） --------------------------------------------
    def _on_camera_changed(self, *args) -> None:
        """相机参数变化时，标记 LED 2D 位置缓存失效。"""
        self._proj_dirty = True

    def _refresh_led_screen_pos(self) -> None:
        """用 GLViewWidget.project 把每个 LED 3D 位置转 2D 屏幕坐标。"""
        if not self._gl.isVisible():
            return
        self._led_screen_pos = []
        view_w = self._gl.width()
        view_h = self._gl.height()
        # Phase 3 fix：若 viewport 尺寸为 0，project 会失败，先记日志
        if view_w <= 0 or view_h <= 0:
            _log.warning(
                "_refresh_led_screen_pos: gl viewport size=0 (%dx%d), skipped",
                view_w, view_h,
            )
            return
        for pos3d in self._led_positions:
            try:
                p2d = self._gl.project(pos3d)
                # pyqtgraph 0.14.0 returns QPointF-like
                if hasattr(p2d, "x"):
                    x, y = float(p2d.x()), float(p2d.y())
                else:
                    x, y = float(p2d[0]), float(p2d[1])
                self._led_screen_pos.append((x, y))
            except Exception as e:
                # Phase 3 fix：原代码 silent except，违反项目记忆"禁止吞错"
                _log.error(
                    "_refresh_led_screen_pos: project failed at pos3d=%r: %r",
                    pos3d, e, exc_info=True,
                )
                self._led_screen_pos.append((None, None))
        self._proj_dirty = False

    def pick_led_at(self, pos) -> Optional[int]:
        """Phase 3 fix：同步 ray-pick。

        在指定屏幕坐标 pos 周围找最近 LED（< 28px 算命中）。
        与 _tick_hover 共享 _led_screen_pos 缓存，确保 hover + click 一致。

        解决了双击依赖 hover 缓存的脆弱性：
        - 用户单击时立即 ray-pick（不再需要先悬停）
        - 抗相机拖拽吃 dblclick 事件（单击 release 即可触发）
        - 抗 50ms hover 定时器滞后

        Args:
            pos: QPointF-like（event.pos() / QCursor.pos()）

        Returns:
            命中的 cid (1..72)，未命中返回 None
        """
        # 若缓存失效（相机移动过），先刷新
        if self._proj_dirty:
            self._refresh_led_screen_pos()
        # 缓存为空说明 widget 还没就绪，返回 None
        if not self._led_screen_pos:
            _log.debug(
                "pick_led_at: _led_screen_pos empty, no LED to pick",
            )
            return None
        THRESHOLD_PX = 28
        px = float(pos.x()) if hasattr(pos, "x") else float(pos[0])
        py = float(pos.y()) if hasattr(pos, "y") else float(pos[1])
        best_cid: Optional[int] = None
        best_dist = THRESHOLD_PX
        for i, (x, y) in enumerate(self._led_screen_pos):
            if x is None:
                continue
            d = ((px - x) ** 2 + (py - y) ** 2) ** 0.5
            if d < best_dist:
                best_dist = d
                best_cid = i + 1
        return best_cid

    def _tick_hover(self) -> None:
        """Phase A.8.3：QTimer 50ms 轮询检测鼠标位置，找最近 LED 显示 tooltip。

        pyqtgraph 0.14 的 GLViewWidget 不提供 mouseMoved 信号，
        所以用 QTimer 轮询 QCursor.pos() + mapFromGlobal 转 Rack3DView 局部坐标。
        """
        if not self.isVisible():
            return
        if self._proj_dirty:
            self._refresh_led_screen_pos()
        # 1) 屏幕鼠标位置 → Rack3DView 局部坐标
        global_pos = QCursor.pos()
        local_pos = self.mapFromGlobal(global_pos)
        if not self.rect().contains(local_pos):
            if self._hover_label.isVisible():
                self._hover_label.hide()
            return
        mx, my = local_pos.x(), local_pos.y()
        # 2) 找最近 LED（< 28px 算命中）
        THRESHOLD_PX = 28
        best_cid = None
        best_dist = THRESHOLD_PX
        for i, (x, y) in enumerate(self._led_screen_pos):
            if x is None:
                continue
            d = ((mx - x) ** 2 + (my - y) ** 2) ** 0.5
            if d < best_dist:
                best_dist = d
                best_cid = i + 1
        if best_cid is None:
            self._best_hovered_cid = None
            if self._hover_label.isVisible():
                self._hover_label.hide()
            return
        # 命中：缓存到实例属性供双击事件读取
        self._best_hovered_cid = best_cid
        # 3) 显示 tooltip
        state = self._led_states.get(best_cid, LEDState.OFFLINE)
        state_name = {
            LEDState.OFFLINE: "离线",
            LEDState.RUNNING: "运行",
            LEDState.PAUSED: "暂停",
            LEDState.ALERT: "告警",
            LEDState.WARNING: "警告",
        }.get(state, "未知")
        self._hover_label.setText(f"{format_cid(best_cid)}  ·  {state_name}")
        self._hover_label.adjustSize()
        self._hover_label.move(int(mx) + 14, int(my) + 10)
        if not self._hover_label.isVisible():
            self._hover_label.show()
            self._hover_label.raise_()

    # -- 内部：颜色刷新 --------------------------------------------------------
    def _refresh_led_colors(self) -> None:
        color_map = {
            LEDState.OFFLINE: DEFAULT_TOKENS.colors.LED_OFFLINE,
            LEDState.RUNNING: DEFAULT_TOKENS.colors.LED_RUNNING,
            LEDState.PAUSED:  DEFAULT_TOKENS.colors.LED_PAUSED,
            LEDState.ALERT:   DEFAULT_TOKENS.colors.LED_ALERT,
            LEDState.WARNING: DEFAULT_TOKENS.colors.LED_WARNING,
        }
        for cid in range(1, GRID_ROWS * GRID_COLS + 1):
            state = self._led_states[cid]
            rgba = color_map[state]
            # numpy alpha 是 0-1，token 里是 0-255
            self._led_colors[cid - 1] = (
                rgba[0] / 255.0,
                rgba[1] / 255.0,
                rgba[2] / 255.0,
                rgba[3] / 255.0,
            )
        # setData 支持 color 参数（但它是单一颜色），所以用 pos+color 重新设置
        self._led_scatter.setData(
            pos=self._led_positions,
            size=self._led_sizes,
            color=self._led_colors,
        )
