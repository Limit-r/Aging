"""v3.0 主页（HomePage）：3D 机柜全屏 + 浮窗层 + 二级页面。

布局（Phase 1.12 之后）：
┌────────────────────────────────────────────────────────┐
│ [⚡ AGING]  [主页][电流][视频][数据][设置]   v3.0       │  TopNavBar (56)
├────────────────────────────────────────────────────────┤
│ ⌚ 左浮窗    AGING RACK (中央)      🔔 右浮窗  [⟲]    │  ← 浮窗层
│           9×8·72 CHANNELS                           │
│                                                        │
│           [        3D 机柜        ]                    │  Rack3DView
│           (全屏，可拖拽 / 缩放 / 自动旋转)             │  (全屏)
│                                                        │
│                              ╔══════════════════╗     │
│                              ║ 系统状态         ║     │  右下浮窗
│                              ║ ▶运行 0/72       ║     │
│                              ║ ⏸暂停 0/72       ║     │
│                              ║ ■停止 72/72      ║     │
│                              ╚══════════════════╝     │
├────────────────────────────────────────────────────────┤
│ ● 72 CHANNELS :: AUTO-ROTATE :: REFRESH 2000ms         │  StatusBar
└────────────────────────────────────────────────────────┘

中央区域由 PageRouter 托管：home / current / video / data / settings 5 个页签。
点击 nav 按钮 → router 切换；点击 3D LED → 暂未处理（Phase 2 接入）。
"""

from __future__ import annotations

import math
import time
from typing import Optional

from PyQt5.QtCore import Qt, QTimer, QEvent
from PyQt5.QtGui import QCloseEvent
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QStatusBar, QLabel,
)
from pyqtgraph import Vector

from app.core import config, labels
from app.core.tokens import DEFAULT_TOKENS
from app.observability import get_logger, narrative
from app.ui.floaters import (
    RightAlertsFloater,
    BottomRightHUDFloater,
    ResetViewButton,
    RightLEDStripFloater,
)
from app.ui.main_3d import (
    Rack3DView, CAMERA_DIST, CAMERA_ELEV, CAMERA_AZIM, CAMERA_CENTER, LEDState,
)
from app.ui.nav_bar import TopNavBar
from app.ui.pages.current_page import CurrentDetectionPage
from app.ui.pages.data_page import DataCenterPage
from app.ui.pages.detail_page import DetailPage
from app.ui.pages.settings_page import SettingsPage
from app.ui.pages.video_page import VideoDetectionPage
from app.ui.router import PageRouter


_log = get_logger("app.ui.home_page")


# 浮窗距边缘的标准 padding
_FLOAT_PADDING = 24


class HomeDashboard(QWidget):
    """主页 Tab 内容 = 3D 机柜全屏 + 5 个浮窗叠加。

    Phase 1.12：移除 VBox 上下布局，3D 占满，浮窗绝对定位。
    Phase 1.14：空闲 5s 启动自动旋转；用户操作（鼠标 / 滚轮）时暂停。
    Phase 1.15：LED 辉光呼吸（3s 周期）。
    """

    # 自动旋转相关常量
    IDLE_TIMEOUT_MS = 5000        # 空闲 5s 启动自动旋转（Phase 1.27 加回）
    ROTATE_TICK_MS = 33         # 旋转刷新率 ≈ 30fps
    ROTATE_SPEED_DEG_PER_S = 8  # 8°/s 慢速旋转（用户要求不抢眼）

    # LED 呼吸相关常量
    BREATH_PERIOD_S = 3.0       # 3s 周期（用户要求减轻硬件负担）
    BREATH_TICK_MS = 50         # 20fps 呼吸刷新
    BREATH_SIZE_AMP = 0.25      # LED size 振幅 25%（1.0× ~ 1.25×）
    BREATH_ALPHA_AMP = 0.10     # alpha 振幅 10%（0.90 ~ 1.0）

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("homeDashboard")
        # 3D 机柜（占满）
        self._rack = Rack3DView(self)
        # 4 个浮窗（绝对定位，右侧顶部垂直堆叠）
        self._right = RightAlertsFloater(self)
        self._led_strip = RightLEDStripFloater(self)
        self._bottom_right = BottomRightHUDFloater(self)
        self._reset_btn = ResetViewButton(self)
        # 默认计数
        total = config.GRID_ROWS * config.GRID_COLS
        self._bottom_right.set_counts(0, 0, total)
        # 浮窗 z-order：保证 3D 在最底层
        self._rack.lower()
        self._rack.stackUnder(self._right)
        # ---- 自动旋转相关 ----
        self._azimuth_offset = 0.0      # 用户手动调整的方位角
        self._azimuth_offset_before_detail: Optional[float] = None  # Phase 3：进入详情页前暂存
        self._last_interact_ms = int(time.time() * 1000)  # 上次交互时间
        self._auto_rotate_active = False
        self._auto_rotate_enabled = True  # Phase 3：详情页打开时设为 False 暂停旋转
        # Phase 3：双击 LED → 通知 HomePage 路由切到 detail
        self._on_open_detail_callback = None  # type: Optional[Callable[[int], None]]
        self._rotate_timer = QTimer(self)
        self._rotate_timer.setInterval(self.ROTATE_TICK_MS)
        self._rotate_timer.timeout.connect(self._tick_rotate)
        # ---- LED 呼吸相关 ----
        self._breath_phase = 0.0
        self._breath_timer = QTimer(self)
        self._breath_timer.setInterval(self.BREATH_TICK_MS)
        self._breath_timer.timeout.connect(self._tick_breath)
        self._breath_timer.start()
        # ---- 信号接线 ----
        self._reset_btn.clicked_reset.connect(self._on_reset_view)
        # 监听 GLViewWidget 鼠标/滚轮事件（Phase 1.28：用 eventFilter 替代 monkey-patch）
        # 原因：PyQt5 包装层对实例属性覆盖类方法有时不生效，eventFilter 更可靠。
        self._rack._gl.installEventFilter(self)
        # 初始定位
        self._position_floaters()
        # 兜底：3D 初始尺寸 = 窗口大小（resizeEvent 触发前先占位）
        self._rack.resize(config.WINDOW_SIZE[0], config.WINDOW_SIZE[1])
        # 启动空闲检测 timer（用于决定是否开始自动旋转）
        self._idle_timer = QTimer(self)
        self._idle_timer.setInterval(500)
        self._idle_timer.timeout.connect(self._tick_idle)
        self._idle_timer.start()

    # -- 浮窗定位 ---------------------------------------------------------------
    def _position_floaters(self) -> None:
        """按 HomeDashboard 当前尺寸重定位 4 个浮窗（右侧顶部垂直堆叠）。

        间距策略：14px，让浮窗之间有明显"空气感"，避免视觉堆叠。
        配色策略：告警=橙 / LED矩阵=绿 / HUD=青，复位按钮=暗灰，三色分明。
        """
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return
        right_x = w - _FLOAT_PADDING
        gap = DEFAULT_TOKENS.sizing.FLOATER_STACK_GAP  # 浮窗间距
        # 从上往下垂直堆叠：复位按钮 → 告警 → LED 矩阵 → HUD
        y = _FLOAT_PADDING
        # 1) 复位按钮（不显眼，最顶部）
        self._reset_btn.move(
            right_x - self._reset_btn.width(), y
        )
        y += self._reset_btn.height() + gap
        # 2) 告警浮窗
        self._right.move(
            right_x - self._right.width(), y
        )
        y += self._right.height() + gap
        # 3) LED 状态矩阵
        self._led_strip.move(
            right_x - self._led_strip.width(), y
        )
        y += self._led_strip.height() + gap
        # 4) HUD 浮窗
        self._bottom_right.move(
            right_x - self._bottom_right.width(), y
        )

    def resizeEvent(self, event):
        # 1) 3D 机柜必须占满整个 HomeDashboard（否则 LED 全不可见）
        self._rack.setGeometry(0, 0, self.width(), self.height())
        # 2) 浮窗重新定位
        self._position_floaters()
        super().resizeEvent(event)

    # -- 公共 API ---------------------------------------------------------------
    @property
    def rack_view(self) -> Rack3DView:
        return self._rack

    def set_counts(self, running: int, paused: int, stopped: int) -> None:
        self._bottom_right.set_counts(running, paused, stopped)

    def set_alerts(self, alerts) -> None:
        self._right.set_alerts(alerts)

    # -- 自动旋转 ---------------------------------------------------------------
    # 拖拽阈值（逻辑像素）：press 与 release 距离 < 此值视为单击而非拖拽
    # 15px 兼顾手抖容错 + 旋转操作区分（明显拖拽 > 15px）
    _CLICK_DRAG_THRESHOLD_PX = 15.0

    def eventFilter(self, obj, event) -> bool:
        """Phase 1.28 + 3.0 fix-14/15：

        交互策略（双击优先 + 单击兜底）：
        1) MouseButtonDblClick（Qt 系统级双击事件）→ 优先触发详情页打开
           - 不依赖 hover 缓存（Qt 会自己管理双击间隔）
           - 适用于 macOS/Windows 系统级双击习惯
        2) 单击 + 拖拽检测（press + release 距离 < 15px）= ray-pick LED → 打开详情
           - 兜底：若 GL widget 屏蔽 DblClick 事件（OpenGL 上下文问题）
           - 抗相机拖拽吃 dblclick 事件
        3) 任何鼠标事件都暂停自动旋转
        """
        if obj is self._rack._gl:
            et = event.type()
            if et in (
                QEvent.MouseButtonPress,
                QEvent.MouseMove,
                QEvent.Wheel,
            ):
                self._mark_interact()
                if et == QEvent.MouseButtonPress:
                    # 记录 press 位置 + 时间，用于后续 release 做拖拽检测
                    self._press_pos = event.pos()
            elif et == QEvent.MouseButtonRelease:
                self._mark_interact()
                # 拖拽检测：release 距 press < 15px 视为单击
                if hasattr(self, "_press_pos") and self._press_pos is not None:
                    release_pos = event.pos()
                    dx = release_pos.x() - self._press_pos.x()
                    dy = release_pos.y() - self._press_pos.y()
                    drag_d = (dx * dx + dy * dy) ** 0.5
                    if drag_d < self._CLICK_DRAG_THRESHOLD_PX:
                        # 同步 ray-pick（不再依赖 _best_hovered_cid 缓存）
                        cid = self._rack.pick_led_at(release_pos)
                        _log.info(
                            "click detected: pos=(%d,%d) drag=%.1fpx cid=%s",
                            int(release_pos.x()), int(release_pos.y()),
                            drag_d, cid,
                        )
                        if cid is not None:
                            self._open_detail(cid)
                    else:
                        _log.debug(
                            "release too far from press (%.1fpx > %.0fpx threshold), treated as drag",
                            drag_d, self._CLICK_DRAG_THRESHOLD_PX,
                        )
                    self._press_pos = None
            elif et == QEvent.MouseButtonDblClick:
                # Qt 系统级双击：忽略 hover 缓存，直接 ray-pick 当前双击位置
                self._mark_interact()
                dbl_pos = event.pos()
                cid = self._rack.pick_led_at(dbl_pos)
                _log.info(
                    "dblclick detected: pos=(%d,%d) cid=%s",
                    int(dbl_pos.x()), int(dbl_pos.y()), cid,
                )
                if cid is not None:
                    self._open_detail(cid)
        return super().eventFilter(obj, event)

    # -- Phase 3：详情页接入 ---------------------------------------------------
    def _open_detail(self, cid: int) -> None:
        """双击 LED → HomePage 路由切到 detail + 暂停自动旋转 + 暂存 azimuth。

        实际路由切换由 HomePage 完成（持有 router 引用），这里只发信号。
        """
        # Phase 3 C1：双击视觉反馈（200ms LED 闪烁）
        self._rack.flash_led_alert(cid, duration_ms=config.LED_FLASH_MS)
        self._azimuth_offset_before_detail = self._azimuth_offset
        # 暂停自动旋转（避免详情页打开后视图还在跳）
        self.set_auto_rotate(False)
        # 通知 HomePage
        if self._on_open_detail_callback is not None:
            self._on_open_detail_callback(cid)

    def set_auto_rotate(self, enabled: bool) -> None:
        """Phase 3：详情页打开/关闭时启用/禁用 3D 自动旋转。"""
        self._auto_rotate_enabled = enabled
        if not enabled and self._auto_rotate_active:
            self._auto_rotate_active = False
            self._rotate_timer.stop()
        if enabled and not self._auto_rotate_active:
            # 恢复：标记为刚交互过，等 IDLE_TIMEOUT_MS 后再自动启动
            self._mark_interact()

    def _mark_interact(self) -> None:
        """用户与 3D 交互时记录时间，停止自动旋转。"""
        self._last_interact_ms = int(time.time() * 1000)
        if self._auto_rotate_active:
            self._auto_rotate_active = False
            self._rotate_timer.stop()
            _log.debug("auto-rotate paused (user interact)")

    def _tick_idle(self) -> None:
        """空闲检测：5s 无交互 → 启动自动旋转。"""
        if not self._auto_rotate_enabled:
            return
        if self._auto_rotate_active:
            return
        now = int(time.time() * 1000)
        if (now - self._last_interact_ms) >= self.IDLE_TIMEOUT_MS:
            self._auto_rotate_active = True
            self._rotate_timer.start()
            _log.info("auto-rotate activated (idle %ds)",
                      self.IDLE_TIMEOUT_MS // 1000)

    def _tick_rotate(self) -> None:
        """每 33ms 推进自动旋转角度。"""
        # 每次 tick 推进 ROTATE_SPEED_DEG_PER_S * (TICK_MS/1000) 度
        delta_deg = self.ROTATE_SPEED_DEG_PER_S * (self.ROTATE_TICK_MS / 1000.0)
        self._azimuth_offset = (self._azimuth_offset + delta_deg) % 360.0
        self._rack._gl.setCameraPosition(
            pos=Vector(*CAMERA_CENTER),
            distance=CAMERA_DIST,
            elevation=CAMERA_ELEV,
            azimuth=CAMERA_AZIM + self._azimuth_offset,
        )

    def _on_reset_view(self) -> None:
        """用户点击"立即复位"按钮：相机归位 + 重置空闲计时。"""
        self._azimuth_offset = 0.0
        self._rack._gl.setCameraPosition(
            pos=Vector(*CAMERA_CENTER),
            distance=CAMERA_DIST,
            elevation=CAMERA_ELEV,
            azimuth=CAMERA_AZIM,
        )
        self._mark_interact()
        _log.info("view reset to initial position")

    # -- LED 呼吸 ---------------------------------------------------------------
    def _tick_breath(self) -> None:
        """每 50ms 推进 LED 呼吸相位。"""
        self._breath_phase += self.BREATH_TICK_MS / 1000.0
        if self._breath_phase >= self.BREATH_PERIOD_S:
            self._breath_phase -= self.BREATH_PERIOD_S
        # 0..1 → sin 曲线 → 0..1
        omega = 2.0 * math.pi / self.BREATH_PERIOD_S
        s = 0.5 + 0.5 * math.sin(omega * self._breath_phase - math.pi / 2.0)
        # size 振幅 1.0× ~ 1.25×；alpha 振幅 0.90 ~ 1.0
        size_mul = 1.0 + self.BREATH_SIZE_AMP * s
        alpha_mul = 0.90 + self.BREATH_ALPHA_AMP * s
        self._rack.apply_breath(size_mul=size_mul, alpha_mul=alpha_mul)

    # -- 异常告警联动槽（Phase A.7） ------------------------------------------
    def set_led_from_visual(self, cid: int, visual: str) -> None:
        """CurrentDetectionPage.cell_visual_state 槽。
        visual ∈ {"anomaly", "online", "offline"} → 映射到 LED 状态。
        """
        if visual == "anomaly":
            self._rack.set_led_state(cid, LEDState.ALERT)
        elif visual == "online":
            self._rack.set_led_state(cid, LEDState.RUNNING)
        else:
            self._rack.set_led_state(cid, LEDState.OFFLINE)


class HomePage(QMainWindow):
    """v3.0 主窗口：3D 主页 + 4 个二级页面。"""
    def __init__(self):
        super().__init__()
        self.setWindowTitle(labels.WINDOW_TITLE_V3)
        self.resize(*config.WINDOW_SIZE)
        self.setMinimumSize(*config.MIN_WINDOW_SIZE)
        self._build_ui()
        narrative.event(
            "home_page_init",
            note="v3.0 主页初始化完成：3D 机柜全屏 + 4 浮窗（右侧堆叠） + 路由",
        )

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 1) 顶部 nav
        self._nav = TopNavBar()
        root.addWidget(self._nav)

        # 2) 中央：PageRouter 包裹 5 个页面 + Phase 3 详情页
        self._router = PageRouter()
        self._dashboard = HomeDashboard()
        self._current_page = CurrentDetectionPage()  # 保留引用（A.7 联动需要）
        # Phase 3：详情页（双击 LED 打开，从 current_page 拿 controller/buffer 引用）
        self._detail_page = DetailPage(
            history=self._current_page.history_buffer,
            cell_controller=self._current_page.cell_controller,
        )
        self._router.register("home", self._dashboard)
        self._router.register("current", self._current_page)
        self._router.register("video", VideoDetectionPage())
        self._data_page = DataCenterPage()
        self._router.register("data", self._data_page)
        self._router.register("settings", SettingsPage())
        self._router.register("detail", self._detail_page)
        # Phase 3：HomeDashboard 双击 → HomePage 路由切到 detail
        self._dashboard._on_open_detail_callback = self._on_open_detail
        self._detail_page.requested_back.connect(self._on_detail_back)
        self._detail_page.action_requested.connect(self._on_detail_action)
        root.addWidget(self._router, 1)

        # 3) 底部状态栏
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._status_bar.showMessage(
            labels.STATUS_BAR_NORMAL_TEMPLATE.format(
                refresh_ms=config.DATA_REFRESH_MS,
                running=0, paused=0, open_detail=0,
                selected=labels.SELECTION_BAR_NONE,
            )
        )

        # 接线
        self._nav.nav_requested.connect(self._on_nav)
        self._router.page_changed.connect(self._on_page_changed)
        # Phase A.7：异常告警 → 主页 3D LED 联动
        self._wire_3d_anomaly_link()
        # Phase 3 fix：HUD 数字（运行/暂停/停止）需要跟随 CellController 状态变化
        # 原代码：HUD 只在 __init__ 时被设为 0/0/72，从不更新
        self._current_page.cell_controller.state_changed.connect(
            self._on_cell_state_for_hud
        )
        # 同步初始状态（demo 默认启动 1-4）
        self._refresh_hud_counts()

    # -- slots -----------------------------------------------------------------
    def _on_nav(self, key: str) -> None:
        """nav 按钮点击 → 路由切换。"""
        self._router.navigate(key)

    def _on_page_changed(self, key: str) -> None:
        """页面切换：状态栏提示。"""
        self._status_bar.showMessage(
            f"● 切换到页面：{key}", config.PAGE_CHANGED_STATUS_MS,
        )
        _log.info("page changed: %s", key)

    # -- 异常告警联动（Phase A.7） ---------------------------------------------
    def _wire_3d_anomaly_link(self) -> None:
        """接线：CurrentDetectionPage.cell_visual_state → HomeDashboard 3D LED。
        修复：连接后立即同步一次当前所有 cell 的 visual state，
        避免 1-4 启动时 HomeDashboard 还没连接错过 emit。
        """
        if self._current_page is None:
            _log.warning("wire_3d_anomaly_link: current page is None")
            return
        self._current_page.cell_visual_state.connect(
            self._dashboard.set_led_from_visual
        )
        # 同步初始 state：1-4 已 RUNNING → 1-4 LED 立即变绿
        states = self._current_page.get_all_visual_states()
        for cid, visual in states.items():
            self._dashboard.set_led_from_visual(cid, visual)
        _log.info(
            "wired: current_page.cell_visual_state → home_dashboard.3d_led, "
            "synced %d initial states: %s",
            len(states), states,
        )

    def _toggle_heartbeat(self) -> None:
        """心跳点 1Hz 闪烁（Phase 1.19 视觉增强）。"""
        self._heartbeat.setVisible(not self._heartbeat.isVisible())

    # -- Phase 3：详情页接线 ---------------------------------------------------
    def _on_open_detail(self, cid: int) -> None:
        """HomeDashboard 双击 LED → 切到详情页 + 切换 chart 数据。"""
        self._detail_page.set_channel(cid)
        self._router.navigate("detail")
        _log.info("home → detail: cid=%d", cid)

    def _on_detail_back(self) -> None:
        """详情页点"返回主页" → 路由回 home + 恢复 3D 旋转 + 恢复 azimuth。"""
        self._router.navigate("home")
        # 恢复 azimuth
        saved = self._dashboard._azimuth_offset_before_detail
        if saved is not None:
            self._dashboard._azimuth_offset = saved
            self._dashboard._rack._gl.setCameraPosition(
                pos=Vector(*CAMERA_CENTER),
                distance=CAMERA_DIST,
                elevation=CAMERA_ELEV,
                azimuth=CAMERA_AZIM + saved,
            )
            self._dashboard._azimuth_offset_before_detail = None
        # 恢复自动旋转（标记刚交互，等 IDLE_TIMEOUT 后再启动）
        self._dashboard.set_auto_rotate(True)
        _log.info("detail → home: rotation & azimuth restored")

    def _on_detail_action(self, action: str, cid: int) -> None:
        """详情页操作按钮 → 转发给 CellController。"""
        if hasattr(self, "_current_page") and self._current_page is not None:
            self._current_page.cell_controller.apply(action, [cid])
        _log.info("detail action forwarded: %s cid=%d", action, cid)

    # -- Phase 3 fix：HUD 状态同步 -------------------------------------------
    def _on_cell_state_for_hud(self, cid: int, old: str, new: str) -> None:
        """任意 cell 状态变化 → 重算 HUD 三项计数。"""
        self._refresh_hud_counts()

    def _refresh_hud_counts(self) -> None:
        """从 CellController 读最新计数 → 推送给 HomeDashboard HUD。"""
        try:
            controller = self._current_page.cell_controller
            self._dashboard.set_counts(
                controller.n_running(),
                controller.n_paused(),
                controller.n_stopped(),
            )
        except Exception as e:
            _log.error(
                "_refresh_hud_counts failed: %r", e, exc_info=True,
            )

    # -- 关闭应用前：确认未保存的标注改动 ------------------------------------
    def closeEvent(self, event: QCloseEvent) -> None:
        if hasattr(self, "_data_page") and self._data_page is not None \
                and not self._data_page.confirm_close():
            event.ignore()
            return
        super().closeEvent(event)
