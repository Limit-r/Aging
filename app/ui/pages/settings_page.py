"""系统设置页：访问密码 + 老化时长 + 电流单元分组(3×2) + 摄像头绑定。

- 访问密码：进入需验证；页面内可修改/恢复默认（持久化）。
- 老化时长：全局默认，可修改并持久化（重启保留），修改后热加载全局运行中倒计时。
- 电流单元分组：每 6 个 CH 绑定一台电流 ESP32，按 3 行 × 2 列布局。
- 摄像头绑定：每个 CH 位点绑定一台 ESP32 摄像头。
- 空闲超时返回：停留无操作超时自动返回系统主页面（home）。

所有设置由 `settings_changed` 信号在会话内通知其它页面刷新。
文案一律来自 labels；视觉量来自 QSS 模板（tokens），本文件无裸 hex/字号。
"""
from __future__ import annotations

from PyQt5.QtCore import QEvent, QTimer, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.core import config, labels
from app.core.tokens import DEFAULT_TOKENS
from app.observability import get_logger, narrative
from app.services import aging_settings as aging_svc
from app.services import settings_access as access_svc
from app.services.binding import get_binding

_S = DEFAULT_TOKENS.sizing
_log = get_logger("app.ui.pages.settings_page")


class SettingsPage(QWidget):
    """系统设置页（v3 落地版）。"""

    settings_changed = pyqtSignal()
    requested_back = pyqtSignal()  # 空闲超时 → 自动返回系统主页面

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("settingsPage")
        # 会话级服务（懒加载单例）
        self._aging = aging_svc.get_aging_settings(self)
        self._binding = get_binding(self)
        self._access = access_svc.get_settings_access(self)

        self._aging.changed.connect(self._on_binding_changed)
        self._binding.changed.connect(self._on_binding_changed)
        self._access.password_changed.connect(self._refresh_pw_hint)

        self._camera_edits: dict[int, QLineEdit] = {}
        self._unit_edits: dict[int, QLineEdit] = {}

        self._build_ui()
        self._build_idle_lock()
        self._load_current_values()

    # -- 页面骨架 -----------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        toolbar = QFrame()
        toolbar.setObjectName("settingsToolbar")
        toolbar.setFixedHeight(_S.TOOLBAR_H * 2)
        tb = QHBoxLayout(toolbar)
        tb.setContentsMargins(16, 12, 16, 12)
        tb.setSpacing(12)
        title = QLabel(labels.SETTINGS_PAGE_TITLE)
        title.setObjectName("settingsTitle")
        hint = QLabel(labels.SETTINGS_PAGE_HINT)
        hint.setObjectName("settingsHint")
        tb.addWidget(title)
        tb.addSpacing(8)
        tb.addWidget(hint)
        tb.addStretch(1)
        root.addWidget(toolbar)

        # 滚动主体：老化时长 + 电流单元 + 摄像头
        scroll = QScrollArea()
        scroll.setObjectName("settingsScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("settingsBody")
        self._body_layout = QVBoxLayout(body)
        self._body_layout.setContentsMargins(16, 16, 16, 16)
        self._body_layout.setSpacing(14)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        self._build_password_card(self._body_layout)
        self._build_aging_card(self._body_layout)
        self._build_units_card(self._body_layout)
        self._build_cameras_card(self._body_layout)

    # -- 卡片工厂 -----------------------------------------------------------
    def _make_card(self, title: str, hint: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("settingsCard")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 12, 14, 14)
        lay.setSpacing(8)
        t = QLabel(title)
        t.setObjectName("settingsCardTitle")
        lay.addWidget(t)
        h = QLabel(hint)
        h.setObjectName("settingsCardHint")
        h.setWordWrap(True)
        lay.addWidget(h)
        return card, lay

    # -- ① 设置访问密码 -------------------------------------------------------
    def _build_password_card(self, parent: QVBoxLayout) -> None:
        card, lay = self._make_card(
            labels.SETTINGS_PASSWORD_TITLE,
            labels.SETTINGS_PASSWORD_HINT,
        )
        self._pw_fields: dict[str, QLineEdit] = {}
        for key, label_text in (
            ("current", labels.SETTINGS_PASSWORD_CURRENT),
            ("new", labels.SETTINGS_PASSWORD_NEW),
            ("confirm", labels.SETTINGS_PASSWORD_CONFIRM),
        ):
            row = QHBoxLayout()
            row.setSpacing(10)
            lab = QLabel(label_text)
            lab.setObjectName("settingsFieldLabel")
            edit = QLineEdit()
            edit.setObjectName("settingsEdit")
            edit.setEchoMode(QLineEdit.Password)
            edit.setCursor(Qt.IBeamCursor)
            self._pw_fields[key] = edit
            row.addWidget(lab)
            row.addWidget(edit, 1)
            lay.addLayout(row)
        btns = QHBoxLayout()
        btns.setSpacing(10)
        apply_btn = QPushButton(labels.SETTINGS_PASSWORD_APPLY)
        apply_btn.setObjectName("settingsApply")
        apply_btn.setCursor(Qt.PointingHandCursor)
        apply_btn.clicked.connect(self._apply_password)
        reset_btn = QPushButton(labels.SETTINGS_PASSWORD_RESET)
        reset_btn.setObjectName("settingsReset")
        reset_btn.setCursor(Qt.PointingHandCursor)
        reset_btn.clicked.connect(self._reset_password)
        btns.addWidget(apply_btn)
        btns.addWidget(reset_btn)
        btns.addStretch(1)
        lay.addLayout(btns)
        self._pw_status = QLabel("")
        self._pw_status.setObjectName("settingsPwStatus")
        self._pw_status.setProperty("err", False)
        lay.addWidget(self._pw_status)
        parent.addWidget(card)

    def _apply_password(self) -> None:
        current = self._pw_fields["current"].text()
        new = self._pw_fields["new"].text()
        confirm = self._pw_fields["confirm"].text()
        if not current or not new or not confirm:
            self._set_pw_status(labels.SETTINGS_PASSWORD_FILL_ALL, err=True)
            return
        err = self._access.change_password(current, new, confirm)
        if err == access_svc.ERR_WRONG_CURRENT:
            self._set_pw_status(labels.SETTINGS_PASSWORD_ERR_WRONG_CURRENT, err=True)
        elif err == access_svc.ERR_TOO_SHORT:
            self._set_pw_status(labels.SETTINGS_PASSWORD_ERR_TOO_SHORT, err=True)
        elif err == access_svc.ERR_MISMATCH:
            self._set_pw_status(labels.SETTINGS_PASSWORD_ERR_MISMATCH, err=True)
        else:
            self._clear_pw_fields()
            self._set_pw_status(labels.SETTINGS_PASSWORD_APPLIED, err=False)
            narrative.event("settings_password_changed",
                            note=labels.SETTINGS_PASSWORD_APPLIED)

    def _reset_password(self) -> None:
        self._access.reset_password()
        self._clear_pw_fields()
        self._set_pw_status(labels.SETTINGS_PASSWORD_RESET_DONE, err=False)
        narrative.event("settings_password_reset",
                        note=labels.SETTINGS_PASSWORD_RESET_DONE)

    def _clear_pw_fields(self) -> None:
        for edit in self._pw_fields.values():
            edit.clear()

    def _set_pw_status(self, text: str, err: bool) -> None:
        self._pw_status.setText(text)
        self._pw_status.setProperty("err", err)
        self._pw_status.style().unpolish(self._pw_status)
        self._pw_status.style().polish(self._pw_status)

    def _refresh_pw_hint(self) -> None:
        """密码被修改/重置后刷新提示（默认密码则警告）。"""
        if self._access.is_default_password():
            self._set_pw_status(labels.SETTINGS_PASSWORD_IS_DEFAULT, err=True)
        else:
            self._pw_status.setText("")
            self._pw_status.setProperty("err", False)

    # -- ② 老化倒计时 -------------------------------------------------------
    def _build_aging_card(self, parent: QVBoxLayout) -> None:
        card, lay = self._make_card(
            labels.SETTINGS_AGING_TITLE,
            labels.SETTINGS_AGING_DEFAULT_HINT_TEMPLATE.format(
                hours=aging_svc.DEFAULT_AGING_SECONDS // 3600),
        )
        row = QHBoxLayout()
        row.setSpacing(10)
        field = QLabel(labels.SETTINGS_AGING_LABEL)
        field.setObjectName("settingsFieldLabel")
        self._aging_spin = QSpinBox()
        self._aging_spin.setObjectName("settingsSpin")
        self._aging_spin.setRange(aging_svc.MIN_AGING_SECONDS // 60,
                                  aging_svc.MAX_AGING_SECONDS // 60)
        self._aging_spin.setSuffix(labels.SETTINGS_AGING_SPIN_SUFFIX)
        apply_btn = QPushButton(labels.SETTINGS_AGING_APPLY)
        apply_btn.setObjectName("settingsApply")
        apply_btn.setCursor(Qt.PointingHandCursor)
        apply_btn.clicked.connect(self._apply_aging)
        reset_btn = QPushButton(labels.SETTINGS_AGING_RESET)
        reset_btn.setObjectName("settingsReset")
        reset_btn.setCursor(Qt.PointingHandCursor)
        reset_btn.clicked.connect(self._reset_aging)
        row.addWidget(field)
        row.addWidget(self._aging_spin)
        row.addSpacing(4)
        row.addWidget(apply_btn)
        row.addWidget(reset_btn)
        row.addStretch(1)
        lay.addLayout(row)
        self._aging_status = QLabel("")
        self._aging_status.setObjectName("settingsCardHint")
        lay.addWidget(self._aging_status)
        parent.addWidget(card)

    @staticmethod
    def _fmt_h_m(seconds: int) -> tuple[int, int]:
        h, rem = divmod(int(seconds), 3600)
        return h, rem // 60

    def _apply_aging(self) -> None:
        minutes = self._aging_spin.value()
        seconds = minutes * 60
        h, m = self._fmt_h_m(seconds)
        self._aging.set_aging_seconds(seconds)
        text = labels.SETTINGS_AGING_APPLIED.format(minutes=minutes, hours=h, mins=m)
        self._aging_status.setText(text)
        narrative.event("aging_duration_applied", note=text)

    def _reset_aging(self) -> None:
        self._aging.reset()
        self._aging_spin.setValue(aging_svc.DEFAULT_AGING_SECONDS // 60)
        h, _m = self._fmt_h_m(aging_svc.DEFAULT_AGING_SECONDS)
        text = labels.SETTINGS_AGING_RESET_DONE.format(hours=h)
        self._aging_status.setText(text)
        narrative.event("aging_duration_reset", note=text)

    # -- ③ 电流单元分组（3×2） ----------------------------------------------
    def _build_units_card(self, parent: QVBoxLayout) -> None:
        units_view = self._binding.each_unit()
        card, lay = self._make_card(
            labels.SETTINGS_CURRENT_UNIT_TITLE,
            labels.SETTINGS_CURRENT_UNIT_HINT_TEMPLATE.format(
                units=self._binding.num_units),
        )
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        for i, u in enumerate(units_view):
            box = QWidget()
            box.setObjectName("settingsBody")
            box_layout = QVBoxLayout(box)
            box_layout.setContentsMargins(8, 6, 8, 6)
            box_layout.setSpacing(2)
            header = QLabel(labels.SETTINGS_UNIT_ID_LABEL.format(u=u["index"] + 1))
            header.setObjectName("settingsUnitId")
            cids = ", ".join(str(c) for c in u["cids"])
            cid_label = QLabel(labels.SETTINGS_UNIT_CIDS_TEMPLATE.format(cids=cids))
            cid_label.setObjectName("settingsUnitCids")
            edit = QLineEdit(u["id"])
            edit.setObjectName("settingsEdit")
            edit.setCursor(Qt.IBeamCursor)
            edit.editingFinished.connect(
                lambda idx=u["index"], e=edit: self._set_unit_id(idx, e))
            self._unit_edits[u["index"]] = edit
            box_layout.addWidget(header)
            box_layout.addWidget(cid_label)
            box_layout.addWidget(edit)
            grid.addWidget(box, i // 4, i % 4)
        lay.addLayout(grid)
        reset_btn = QPushButton(labels.SETTINGS_RESET_ALL_UNITS)
        reset_btn.setObjectName("settingsReset")
        reset_btn.setCursor(Qt.PointingHandCursor)
        reset_btn.clicked.connect(self._reset_all_units)
        lay.addWidget(reset_btn, 0, Qt.AlignLeft)
        parent.addWidget(card)

    def _reset_all_units(self) -> None:
        self._binding.reset_all_units()
        for idx, edit in self._unit_edits.items():
            edit.setText(self._binding.unit_id(idx))
        narrative.event("binding_units_reset",
                        note=labels.SETTINGS_RESET_ALL_UNITS_DONE)

    # -- ④ 摄像头绑定（每 CH 一台） -----------------------------------------
    def _build_cameras_card(self, parent: QVBoxLayout) -> None:
        rows, cols = config.GRID_ROWS, config.GRID_COLS
        card, lay = self._make_card(
            labels.SETTINGS_CAMERA_TITLE,
            labels.SETTINGS_CAMERA_HINT_TEMPLATE.format(cid=1),
        )
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        for cid in range(1, self._binding.cell_count + 1):
            r_ = (cid - 1) // cols
            c_ = (cid - 1) % cols
            lab = QLabel(labels.SETTINGS_CAMERA_ID_LABEL_TEMPLATE.format(cid=cid))
            lab.setObjectName("settingsCamLabel")
            lab.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            edit = QLineEdit(self._binding.camera_id(cid))
            edit.setObjectName("settingsEdit")
            edit.setCursor(Qt.IBeamCursor)
            edit.editingFinished.connect(
                lambda c=cid, e=edit: self._set_camera_id(c, e))
            self._camera_edits[cid] = edit
            grid.addWidget(lab, r_, c_ * 2)
            grid.addWidget(edit, r_, c_ * 2 + 1)
        lay.addLayout(grid)
        reset_btn = QPushButton(labels.SETTINGS_RESET_ALL_CAMERAS)
        reset_btn.setObjectName("settingsReset")
        reset_btn.setCursor(Qt.PointingHandCursor)
        reset_btn.clicked.connect(self._reset_all_cameras)
        lay.addWidget(reset_btn, 0, Qt.AlignLeft)
        parent.addWidget(card)

    def _reset_all_cameras(self) -> None:
        self._binding.reset_all_cameras()
        for cid, edit in self._camera_edits.items():
            edit.setText(self._binding.camera_id(cid))
        narrative.event("binding_cameras_reset",
                        note=labels.SETTINGS_RESET_ALL_CAMERAS_DONE)

    def _set_unit_id(self, idx: int, edit: QLineEdit) -> None:
        self._binding.set_unit_id(idx, edit.text().strip())
        edit.setText(self._binding.unit_id(idx))

    def _set_camera_id(self, cid: int, edit: QLineEdit) -> None:
        self._binding.set_camera_id(cid, edit.text().strip())
        edit.setText(self._binding.camera_id(cid))

    # -- 值读写 / 联动 ------------------------------------------------------
    def _load_current_values(self) -> None:
        self._aging_spin.setValue(self._aging.aging_seconds // 60)
        # 回显当前生效老化时长
        current = self._aging.aging_seconds
        h, m = self._fmt_h_m(current)
        self._aging_status.setText(
            labels.SETTINGS_AGING_APPLIED.format(
                minutes=current // 60, hours=h, mins=m))
        # 默认密码则提示尽快修改
        self._refresh_pw_hint()
        for idx, edit in self._unit_edits.items():
            edit.setText(self._binding.unit_id(idx))
        for cid, edit in self._camera_edits.items():
            edit.setText(self._binding.camera_id(cid))

    def _on_binding_changed(self) -> None:
        self.settings_changed.emit()

    # -- 空闲超时自动返回主页 --------------------------------------------------
    # 活动判定：点击 / 双击 / 键盘 / 滚轮（移动鼠标不单独计活动，防挂机）
    _IDLE_ACTIVE_EVENTS = (
        QEvent.MouseButtonPress,
        QEvent.MouseButtonDblClick,
        QEvent.KeyPress,
        QEvent.Wheel,
    )

    def _build_idle_lock(self) -> None:
        """空闲超时自动返回主页：单次计时器 + 全局活动事件过滤。"""
        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.setInterval(config.SETTINGS_IDLE_AUTOBACK_MS)
        self._idle_timer.timeout.connect(self._on_idle_timeout)
        # 全局事件过滤：仅当本页可见时，页面内活动重置计时
        QApplication.instance().installEventFilter(self)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._kick_idle_timer()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._idle_timer.stop()

    def eventFilter(self, obj, event) -> bool:
        """页面内活动（点击/按键/滚轮）重置空闲计时。"""
        if (self.isVisible()
                and isinstance(obj, QWidget)
                and event.type() in self._IDLE_ACTIVE_EVENTS
                and (obj is self or self.isAncestorOf(obj))):
            self._kick_idle_timer()
        return super().eventFilter(obj, event)

    def _kick_idle_timer(self) -> None:
        self._idle_timer.start()

    def _on_idle_timeout(self) -> None:
        """空闲超时：自动返回系统主页面（home）。"""
        narrative.event("settings_idle_autoback",
                        note=labels.SETTINGS_IDLE_AUTOBACK_NOTE)
        _log.info("settings page idle timeout → back to home")
        self.requested_back.emit()