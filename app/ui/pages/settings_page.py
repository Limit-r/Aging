"""系统设置页：老化时长 + 电流单元分组(3×2) + 摄像头绑定（会话内存）。

- 老化时长：全局默认 2h，可修改（仅会话生效，不落盘）。
- 电流单元分组：每 6 个 CH 绑定一台电流 ESP32，按 3 行 × 2 列布局。
- 摄像头绑定：每个 CH 位点绑定一台 ESP32 摄像头。

所有设置由 `settings_changed` 信号在会话内通知其它页面刷新。
文案一律来自 labels；视觉量来自 QSS 模板（tokens），本文件无裸 hex/字号。
"""
from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
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
from app.observability import narrative
from app.services import aging_settings as aging_svc
from app.services.binding import get_binding

_S = DEFAULT_TOKENS.sizing


class SettingsPage(QWidget):
    """系统设置页（v3 落地版）。"""

    settings_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("settingsPage")
        # 会话级服务（懒加载单例）
        self._aging = aging_svc.get_aging_settings(self)
        self._binding = get_binding(self)

        self._aging.changed.connect(self._on_binding_changed)
        self._binding.changed.connect(self._on_binding_changed)

        self._camera_edits: dict[int, QLineEdit] = {}
        self._unit_edits: dict[int, QLineEdit] = {}

        self._build_ui()
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

    # -- ① 老化倒计时 -------------------------------------------------------
    def _build_aging_card(self, parent: QVBoxLayout) -> None:
        card, lay = self._make_card(
            labels.SETTINGS_AGING_TITLE,
            labels.SETTINGS_AGING_DEFAULT_HINT_TEMPLATE.format(hours=2),
        )
        row = QHBoxLayout()
        row.setSpacing(10)
        field = QLabel(labels.SETTINGS_AGING_LABEL)
        field.setObjectName("settingsFieldLabel")
        self._aging_spin = QSpinBox()
        self._aging_spin.setObjectName("settingsSpin")
        self._aging_spin.setRange(aging_svc.MIN_AGING_SECONDS // 60,
                                  aging_svc.MAX_AGING_SECONDS // 60)
        self._aging_spin.setSuffix(" 分钟")
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

    def _apply_aging(self) -> None:
        minutes = self._aging_spin.value()
        seconds = minutes * 60
        if seconds != self._aging.aging_seconds:
            narrative.event(
                "aging_duration_applied",
                note=labels.SETTINGS_AGING_APPLIED.format(
                    minutes=minutes, hours=minutes / 60),
            )
        self._aging.set_aging_seconds(seconds)

    def _reset_aging(self) -> None:
        self._aging.reset()
        self._aging_spin.setValue(
            aging_svc.DEFAULT_AGING_SECONDS // 60)
        narrative.event(
            "aging_duration_reset",
            note=labels.SETTINGS_AGING_RESET_DONE.format(hours=2),
        )

    # -- ② 电流单元分组（3×2） ----------------------------------------------
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

    # -- ③ 摄像头绑定（每 CH 一台） -----------------------------------------
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
        for idx, edit in self._unit_edits.items():
            edit.setText(self._binding.unit_id(idx))
        for cid, edit in self._camera_edits.items():
            edit.setText(self._binding.camera_id(cid))

    def _on_binding_changed(self) -> None:
        self.settings_changed.emit()