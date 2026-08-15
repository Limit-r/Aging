"""数据中心页（Phase 6）。

三个页签：
- 历史 / 趋势 / 导出（后续实现）
- 数据标注（Phase B 接入画框标注器）
- 训练 / 转换（后续实现）

懒加载约束：本页顶部**不** import led_pipeline，
保证 Main.py 启动不加载 torch / opencv / openvino 等重型依赖；
数据标注 / 训练能力在后续阶段按需加载。
"""

import os

# 布局：
# ┌─────────────────────────────────────────────────────────────────────────┐
# │ [DC] 数据中心   DATA CENTER · ANNOTATION · TRAINING     [● ACTIVE]      │  顶栏 56
# │ ────────────────────────────────────────────────────────────────────    │
# │ [历史/趋势/导出] [数据标注] [训练/转换]                                   │  页签 40
# │ ┌─[类别工具条]──────────────────────────────────────────────────────┐   │  类别 44
# │ │ 类别 │ ▣FP_SIG_area ▣FP_PWR_area ▣FP_VPL ▣FP_CPL ▣FP_PWR ▣+新增 │   │
# │ │                                              [↻ 类别管理] [⇪ 导入] │   │
# │ └────────────────────────────────────────────────────────────────────┘   │
# │ ┌─[图片列表 220]┐ ┌─[画布]───────────────────────────────────────┐    │
# │ │ ● 图片列表    │ │ ┌─────────────────────────────────────────┐  │    │
# │ │ ▣ frame_450  │ │ │ ⊕ CANVAS 1920×1080      □ □ □  ✕       │  │    │
# │ │ ▣ frame_500  │ │ │                                         │  │    │
# │ │ ▣ frame_536  │ │ │       ★ 等待画框标注器 (Phase B) ★       │  │    │
# │ │              │ │ │                                         │  │    │
# │ │ [◀ 上一张]   │ │ └─────────────────────────────────────────┘  │    │
# │ │ [下一张 ▶]   │ └──────────────────────────────────────────────┘    │
# │ └──────────────┘                                                    │
# │ ┌─[对象列表 + 操作]──────────────────────────────────────────────┐    │
# │ │ 标注对象 (0)                       [取消]   [💾 保存标注]         │    │
# │ └─────────────────────────────────────────────────────────────────┘    │
# └─────────────────────────────────────────────────────────────────────────┘

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QButtonGroup, QFileDialog, QFrame, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QSplitter, QStackedWidget, QVBoxLayout,
    QWidget,
)

from app.core import labels
from app.core.tokens import DEFAULT_TOKENS


# 标注页占位类别（Phase A 接入类别注册表后移除）
_PLACEHOLDER_CATEGORIES = ("FP_SIG_area", "FP_PWR_area", "FP_VPL", "FP_CPL", "FP_PWR")


class DataCenterPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("dataCenterPage")
        self._s = DEFAULT_TOKENS.sizing
        self._tab_group: QButtonGroup
        # 懒加载导入的图片条目（ImageEntry 列表），由 _lazy_annotation_io() 提供类型
        self._entries = []
        # 标注页需要但不随 UI 构建期初始化的引用
        self._image_list: QListWidget
        self._object_list: QListWidget
        self._canvas_hint: QLabel
        self._canvas_corner_lb: QLabel
        self._footer_count: QLabel
        self._canvas = None            # AnnotationCanvas（懒加载）
        self._current_entry = None     # 当前选中 ImageEntry
        self._xml_dir = None           # 当前导入的 XML 目录
        self._skip_item_change = False  # 未保存提示取消时回退选中，避免递归
        self._build_ui()

    # -- UI 构建 -------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(
            self._s.DATA_PAGE_MARGIN,
            self._s.DATA_PAGE_MARGIN,
            self._s.DATA_PAGE_MARGIN,
            self._s.DATA_PAGE_MARGIN,
        )
        root.setSpacing(self._s.DATA_PAGE_SPACING)
        root.addWidget(self._build_header())
        # 先建 stack（自绘页签需要切换它），再建 tabs bar
        self._stack = QStackedWidget()
        self._stack.setObjectName("dataStack")
        self._stack.addWidget(self._build_history_page())
        self._stack.addWidget(self._build_annotate_page())
        self._stack.addWidget(self._build_train_page())
        root.addWidget(self._build_tabs_bar())
        root.addWidget(self._stack, 1)

    # -- 顶栏：徽章 + 标题 + 副标题 + 状态 -------------------------------------
    def _build_header(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("dataHeader")
        bar.setFixedHeight(self._s.DATA_HEADER_H)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(
            self._s.DATA_HEADER_PAD_L, 0,
            self._s.DATA_HEADER_PAD_R, 0,
        )
        lay.setSpacing(self._s.DATA_HEADER_GAP)
        lay.setAlignment(Qt.AlignVCenter)

        badge = QLabel("DC")
        badge.setObjectName("dataHeaderBadge")
        badge.setAlignment(Qt.AlignCenter)
        badge.setMinimumWidth(self._s.DATA_HEADER_BADGE_MIN_W)
        badge.setMaximumWidth(self._s.DATA_HEADER_BADGE_MAX_W)
        lay.addWidget(badge)

        title_col = QVBoxLayout()
        title_col.setSpacing(0)
        title = QLabel(labels.DATA_CENTER_TITLE)
        title.setObjectName("dataHeaderTitle")
        subtitle = QLabel(labels.DATA_CENTER_SUBTITLE)
        subtitle.setObjectName("dataHeaderSubtitle")
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        title_wrap = QWidget()
        title_wrap.setObjectName("dataHeaderTitleWrap")
        title_wrap.setLayout(title_col)
        lay.addWidget(title_wrap)
        lay.addStretch(1)

        status = QLabel("● ACTIVE")
        status.setObjectName("dataHeaderStatus")
        lay.addWidget(status)
        return bar

    # -- 自绘页签栏（QPushButton + ButtonGroup 实现可点击切换） -----------------
    def _build_tabs_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("dataTabsBar")
        bar.setFixedHeight(self._s.DATA_TABS_H)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(
            self._s.DATA_TABS_PAD_L, 0,
            self._s.DATA_TABS_PAD_R, 0,
        )
        lay.setSpacing(self._s.DATA_TABS_GAP)
        lay.setAlignment(Qt.AlignVCenter)

        self._tab_group = QButtonGroup(self)
        self._tab_group.setExclusive(True)
        tabs = (
            (labels.DATA_TAB_HISTORY, 0),
            (labels.DATA_TAB_ANNOTATE, 1),
            (labels.DATA_TAB_TRAIN, 2),
        )
        for text, idx in tabs:
            btn = QPushButton(text)
            btn.setObjectName("dataTab")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _checked=False, i=idx: self._stack.setCurrentIndex(i))
            self._tab_group.addButton(btn, idx)
            lay.addWidget(btn)
        lay.addStretch(1)
        # 默认选中"数据标注"页
        self._tab_group.button(1).setChecked(True)
        self._stack.setCurrentIndex(1)
        return bar

    # -- 三个页内容 -----------------------------------------------------------
    def _build_history_page(self) -> QWidget:
        return self._build_placeholder_page(labels.DATA_TAB_HISTORY, labels.DATA_HISTORY_PLACEHOLDER)

    def _build_train_page(self) -> QWidget:
        return self._build_placeholder_page(labels.DATA_TAB_TRAIN, labels.DATA_TRAIN_PLACEHOLDER)

    def _build_placeholder_page(self, title: str, body: str) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setAlignment(Qt.AlignCenter)
        accent = QLabel(f"// {title}")
        accent.setObjectName("dcTabPlaceholderAccent")
        text = QLabel(body)
        text.setObjectName("dcTabPlaceholder")
        text.setAlignment(Qt.AlignCenter)
        text.setWordWrap(True)
        lay.addWidget(accent, 0, Qt.AlignCenter)
        lay.addSpacing(self._s.DATA_PLACEHOLDER_GAP)
        lay.addWidget(text, 0, Qt.AlignCenter)
        lay.addStretch(1)
        return page

    # -- 数据标注页 ------------------------------------------------------------
    def _build_annotate_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, self._s.DATA_PAGE_SPACING, 0, 0)
        lay.setSpacing(self._s.DATA_PAGE_SPACING)
        lay.addWidget(self._build_category_bar())
        split = QSplitter(Qt.Horizontal)
        split.setObjectName("dataSplitter")
        split.setChildrenCollapsible(False)
        split.addWidget(self._build_image_sidebar())
        split.addWidget(self._build_canvas_panel())
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([self._s.DATA_SIDEBAR_W, self._s.DATA_SIDEBAR_W * 3])
        lay.addWidget(split, 1)
        lay.addWidget(self._build_footer())
        lay.addStretch(0)
        return page

    def _build_category_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("dcCategoryBar")
        bar.setFixedHeight(self._s.DATA_CATEGORY_BAR_H)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(
            self._s.DATA_CATEGORY_PAD, 0,
            self._s.DATA_CATEGORY_PAD, 0,
        )
        lay.setSpacing(self._s.DATA_CATEGORY_GAP)
        lay.setAlignment(Qt.AlignVCenter)
        label = QLabel(labels.ANNOT_CATEGORY_LABEL)
        label.setObjectName("dcBarLabel")
        lay.addWidget(label)
        self._category_group = QButtonGroup(self)
        self._category_group.setExclusive(True)
        self._active_category = None
        self._category_buttons = {}
        for cat in _PLACEHOLDER_CATEGORIES:
            btn = QPushButton(cat)
            btn.setObjectName("dcChipBtn")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _c=False, name=cat: self._on_category_chosen(name))
            self._category_group.addButton(btn)
            self._category_buttons[cat] = btn
            lay.addWidget(btn)
        add = QLabel(labels.ANNOT_CATEGORY_ADD)
        add.setObjectName("dcChipAdd")
        lay.addWidget(add)
        lay.addStretch(1)
        manage = QPushButton(labels.ANNOT_CATEGORY_MANAGE)
        manage.setObjectName("dcGhostBtn")
        lay.addWidget(manage)
        import_btn = QPushButton(labels.ANNOT_IMPORT_BTN)
        import_btn.setObjectName("dcPrimaryBtn")
        import_btn.clicked.connect(self._on_import_folder)
        lay.addWidget(import_btn)
        return bar

    def _on_category_chosen(self, name: str) -> None:
        self._active_category = name
        if self._canvas is not None:
            self._canvas.set_active_category(name)

    def _build_image_sidebar(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("dcSidePanel")
        panel.setFixedWidth(self._s.DATA_SIDEBAR_W)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(
            self._s.DATA_SIDEBAR_PAD,
            self._s.DATA_SIDEBAR_PAD,
            self._s.DATA_SIDEBAR_PAD,
            self._s.DATA_SIDEBAR_PAD,
        )
        lay.setSpacing(self._s.DATA_SIDEBAR_GAP)
        title = QLabel(labels.ANNOT_IMAGE_LIST_TITLE)
        title.setObjectName("dcPanelTitle")
        lay.addWidget(title)
        self._image_list = QListWidget()
        self._image_list.setObjectName("dcList")
        self._image_list.currentItemChanged.connect(self._on_current_item_changed)
        empty_item = QListWidgetItem(labels.ANNOT_IMPORT_EMPTY)
        empty_item.setFlags(Qt.NoItemFlags)
        self._image_list.addItem(empty_item)
        lay.addWidget(self._image_list, 1)
        nav = QHBoxLayout()
        nav.setSpacing(self._s.DATA_SIDEBAR_NAV_GAP)
        prev = QPushButton(f"◀  {labels.ANNOT_PREV_BTN}")
        prev.setObjectName("dcGhostBtn")
        prev.clicked.connect(lambda: self._navigate_image(-1))
        nxt = QPushButton(f"{labels.ANNOT_NEXT_BTN}  ▶")
        nxt.setObjectName("dcGhostBtn")
        nxt.clicked.connect(lambda: self._navigate_image(1))
        nav.addWidget(prev)
        index_lb = QLabel(labels.ANNOT_INDEX_EMPTY)
        index_lb.setObjectName("dcZoomPct")
        index_lb.setAlignment(Qt.AlignCenter)
        self._index_lb = index_lb
        nav.addWidget(index_lb)
        nav.addWidget(nxt)
        lay.addLayout(nav)
        return panel

    def _build_canvas_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("dcCanvasOuter")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        canvas = QFrame()
        canvas.setObjectName("dcCanvas")
        canvas.setMinimumHeight(self._s.DATA_CANVAS_MIN_H)
        cl = QVBoxLayout(canvas)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        # 角标行（左上 CANVAS / 右上 □ □ □ ✕）
        top = QHBoxLayout()
        top.setContentsMargins(
            self._s.DATA_CANVAS_PAD_X,
            self._s.DATA_CANVAS_PAD_T,
            self._s.DATA_CANVAS_PAD_X,
            0,
        )
        top.setSpacing(self._s.DATA_CANVAS_GAP)
        corner_lt = QLabel(labels.ANNOT_CANVAS_CORNER_TEMPLATE.format(
            w=self._s.ANNOT_CANVAS_REF_W,
            h=self._s.ANNOT_CANVAS_REF_H,
            pct=self._s.ANNOT_ZOOM_PCT_DEFAULT,
        ))
        corner_lt.setObjectName("dcCanvasCorner")
        top.addWidget(corner_lt)
        top.addStretch(1)
        # 缩放控制条（− 百分比 +  |  1:1  适应）
        out_btn = QPushButton(labels.ANNOT_ZOOM_OUT)
        out_btn.setObjectName("dcZoomBtn")
        out_btn.setToolTip(labels.ANNOT_ZOOM_TOOLTIP_OUT)
        in_btn = QPushButton(labels.ANNOT_ZOOM_IN)
        in_btn.setObjectName("dcZoomBtn")
        in_btn.setToolTip(labels.ANNOT_ZOOM_TOOLTIP_IN)
        zoom_pct = QLabel(labels.ANNOT_ZOOM_PCT_TEMPLATE.format(
            pct=self._s.ANNOT_ZOOM_PCT_SCALE))
        zoom_pct.setObjectName("dcZoomPct")
        orig_btn = QPushButton(labels.ANNOT_ZOOM_ORIG)
        orig_btn.setObjectName("dcZoomBtn")
        orig_btn.setToolTip(labels.ANNOT_ZOOM_TOOLTIP_ORIG)
        fit_btn = QPushButton(labels.ANNOT_ZOOM_FIT)
        fit_btn.setObjectName("dcZoomBtn")
        fit_btn.setToolTip(labels.ANNOT_ZOOM_TOOLTIP_FIT)
        # 记录引用，待画布创建后接线
        self._zoom_buttons = (out_btn, in_btn, orig_btn, fit_btn)
        self._zoom_pct = zoom_pct
        top.addWidget(out_btn)
        top.addWidget(in_btn)
        top.addWidget(zoom_pct)
        top.addWidget(orig_btn)
        top.addWidget(fit_btn)
        cl.addLayout(top)
        # 中心区域：空状态提示 与 标注器（stack 切换）
        self._canvas_stack = QStackedWidget()
        self._canvas_stack.setObjectName("dcCanvasStack")
        # 空状态页
        empty = QWidget()
        empty.setObjectName("dcCanvasCenter")
        cc = QVBoxLayout(empty)
        cc.setAlignment(Qt.AlignCenter)
        cc.setSpacing(self._s.DATA_CANVAS_CENTER_GAP)
        accent = QLabel("// PHASE B  ·  ANNOTATOR")
        accent.setObjectName("dcCanvasHintAccent")
        hint = QLabel(labels.ANNOT_CANVAS_HINT)
        hint.setObjectName("dcCanvasHint")
        hint.setAlignment(Qt.AlignCenter)
        hint.setWordWrap(True)
        self._canvas_hint = hint
        cc.addWidget(accent, 0, Qt.AlignCenter)
        cc.addWidget(hint, 0, Qt.AlignCenter)
        self._canvas_stack.addWidget(empty)
        # 标注器页（懒加载创建）
        self._canvas_stack.addWidget(self._make_canvas())
        cl.addWidget(self._canvas_stack, 1)
        # 底角标
        bottom = QHBoxLayout()
        bottom.setContentsMargins(
            self._s.DATA_CANVAS_PAD_X,
            0,
            self._s.DATA_CANVAS_PAD_X,
            self._s.DATA_CANVAS_PAD_B,
        )
        bottom.setSpacing(self._s.DATA_CANVAS_GAP)
        corner_lb = QLabel("--  ·  -- OBJECTS  ·  READY")
        corner_lb.setObjectName("dcCanvasCorner")
        self._canvas_corner_lb = corner_lb
        bottom.addWidget(corner_lb)
        bottom.addStretch(1)
        corner_rb = QLabel("FPS  —  ZOOM  1.0×  ·  PX  0,0")
        corner_rb.setObjectName("dcCanvasCorner")
        bottom.addWidget(corner_rb)
        cl.addLayout(bottom)
        lay.addWidget(canvas, 1)
        return panel

    def _build_footer(self) -> QFrame:
        foot = QFrame()
        foot.setObjectName("dcFooter")
        foot.setMinimumHeight(self._s.DATA_FOOTER_MIN_H)
        lay = QVBoxLayout(foot)
        lay.setContentsMargins(
            self._s.DATA_FOOTER_PAD, 0,
            self._s.DATA_FOOTER_PAD, 0,
        )
        lay.setSpacing(self._s.DATA_FOOTER_GAP)
        # 标题行
        head = QHBoxLayout()
        head.setSpacing(self._s.DATA_FOOTER_HEAD_GAP)
        title = QLabel(labels.ANNOT_OBJECT_LIST_TITLE)
        title.setObjectName("dcFooterTitle")
        head.addWidget(title)
        head.addStretch(1)
        count = QLabel("0")
        count.setObjectName("dataHeaderStatus")
        self._footer_count = count
        head.addWidget(count)
        lay.addLayout(head)
        # 对象列表
        self._object_list = QListWidget()
        self._object_list.setObjectName("dcObjectList")
        self._object_list.addItem(labels.ANNOT_OBJECT_LIST_EMPTY)
        lay.addWidget(self._object_list, 1)
        # 操作按钮
        btns = QHBoxLayout()
        btns.setSpacing(self._s.DATA_FOOTER_BTN_GAP)
        btns.addStretch(1)
        delete_btn = QPushButton(labels.ANNOT_DELETE_SELECTED_BTN)
        delete_btn.setObjectName("dcGhostBtn")
        delete_btn.clicked.connect(self._on_delete_selected)
        cancel = QPushButton(labels.ANNOT_CANCEL_BTN)
        cancel.setObjectName("dcGhostBtn")
        save = QPushButton(f"💾  {labels.ANNOT_SAVE_BTN}")
        save.setObjectName("dcPrimaryBtn")
        save.clicked.connect(self._on_save_annotation)
        btns.addWidget(delete_btn)
        btns.addWidget(cancel)
        btns.addWidget(save)
        lay.addLayout(btns)
        return foot

    # -- 懒加载 annotation_io（切到标注页才 import，保持启动轻量） ---------------
    def _lazy_annotation_io(self):
        """懒加载 led_pipeline.annotation_io 模块。"""
        from led_pipeline.annotation_io import (
            ImageEntry, count_mapped, parse_annotation, scan_image_folder,
            write_annotation,
        )
        return ImageEntry, count_mapped, parse_annotation, scan_image_folder, write_annotation

    def _lazy_annotation_widget(self):
        """懒加载 led_pipeline.annotation_widget 模块。"""
        from led_pipeline.annotation_widget import AnnotationCanvas
        return AnnotationCanvas

    def _make_canvas(self):
        """创建（懒加载）标注画布并注入配置。"""
        AnnotationCanvas = self._lazy_annotation_widget()
        canvas = AnnotationCanvas()
        canvas.configure(
            categories=list(_PLACEHOLDER_CATEGORIES),
            palette=DEFAULT_TOKENS.colors.ANNOT_BOX_PALETTE,
            selected_color=DEFAULT_TOKENS.colors.ANNOT_BOX_SELECTED,
            border_w=DEFAULT_TOKENS.sizing.ANNOT_BOX_BORDER_W,
            sel_border_w=DEFAULT_TOKENS.sizing.ANNOT_BOX_BORDER_W_SEL,
            min_size=DEFAULT_TOKENS.sizing.ANNOT_BOX_MIN_SIZE,
            padding=DEFAULT_TOKENS.sizing.ANNOT_PADDING_PX,
        )
        canvas.annotations_changed.connect(self._on_annotations_changed)
        canvas.selection_changed.connect(self._on_annotations_changed)
        canvas.navigate_signal.connect(self._navigate_image)
        canvas.save_requested.connect(self._on_save_annotation)
        canvas.zoom_changed.connect(self._on_zoom_changed)
        # 接线缩放控制条
        out_btn, in_btn, orig_btn, fit_btn = self._zoom_buttons
        out_btn.clicked.connect(canvas.zoom_out)
        in_btn.clicked.connect(canvas.zoom_in)
        orig_btn.clicked.connect(canvas.zoom_to_original)
        fit_btn.clicked.connect(canvas.fit_to_view_trigger)
        self._canvas = canvas
        return canvas

    # -- 导入图片文件夹 + XML 映射 -------------------------------------------------
    def _on_import_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, labels.ANNOT_IMPORT_DIALOG_TITLE, "", QFileDialog.ShowDirsOnly,
        )
        if not folder:
            return
        _, _, _, scan_image_folder, _ = self._lazy_annotation_io()
        try:
            entries = scan_image_folder(folder)
        except FileNotFoundError as exc:
            self._canvas_hint.setText(str(exc))
            return
        self._entries = entries
        self._image_list.clear()
        for entry in entries:
            mark = labels.ANNOT_IMAGE_MAPPED_MARK if entry.has_xml else labels.ANNOT_IMAGE_UNMAPPED_MARK
            item = QListWidgetItem(labels.ANNOT_IMAGE_ENTRY.format(mark=mark, name=entry.image_name))
            item.setData(Qt.UserRole, entry)
            self._image_list.addItem(item)
        mapped = sum(1 for e in entries if e.has_xml)
        self._xml_dir = entries[0].xml_dir if entries else None
        self._canvas_hint.setText(
            labels.ANNOT_IMPORT_SUMMARY.format(total=len(entries), mapped=mapped),
        )
        if entries:
            self._image_list.setCurrentRow(0)

    # -- 选中图片：加载到画布 + 显示标注框 + 刷新对象列表 --------------------------
    def _on_current_item_changed(self, current, previous) -> None:
        """图片列表选中变化。若当前图有未保存改动，先询问再切换。"""
        if self._skip_item_change:
            self._skip_item_change = False
            return
        if current is None:
            return
        row = self._image_list.row(current)
        # 有未保存改动且确实在切换：询问
        if (previous is not None
                and self._canvas is not None
                and self._canvas.is_dirty):
            name = self._current_entry.image_name if self._current_entry else ""
            ret = self._confirm_unsaved(name)
            if ret == QMessageBox.Cancel:
                # 取消：回退选中到上一张，但不触发回调
                self._skip_item_change = True
                self._image_list.setCurrentItem(previous)
                return
            if ret == QMessageBox.Discard:
                self._canvas.mark_saved()
            # Save 分支：先保存再切换
        self._load_image(row)

    def _load_image(self, row: int) -> None:
        """把指定行的图片加载到画布并刷新显示。"""
        canvas = self._canvas
        if canvas is None:
            return
        if not (0 <= row < len(self._entries)):
            self._canvas_corner_lb.setText("--  ·  -- OBJECTS  ·  READY")
            self._index_lb.setText(labels.ANNOT_INDEX_EMPTY)
            return
        entry = self._entries[row]
        self._current_entry = entry
        # 加载图片
        if not canvas.load_pixmap(entry.image_path):
            self._canvas_corner_lb.setText("IMAGE LOAD FAILED")
            return
        # 解析 XML 并显示框
        objs = []
        if entry.has_xml:
            _, _, parse_annotation, _, _ = self._lazy_annotation_io()
            try:
                data = parse_annotation(entry.xml_path)
                objs = data["objects"]
            except Exception:
                objs = []
        canvas.set_objects(objs)
        # 切到标注器页
        self._canvas_stack.setCurrentIndex(1)
        # 更新当前索引
        self._index_lb.setText(labels.ANNOT_INDEX_TEMPLATE.format(
            cur=row + 1, total=len(self._entries),
        ))
        self._refresh_annotation_view(objs)

    def _navigate_image(self, delta: int) -> None:
        """切换图片（按钮 / D / A 快捷键共用入口）。"""
        if not self._entries:
            return
        current = self._image_list.currentRow()
        new_row = (current + delta) % len(self._entries)
        self._image_list.setCurrentRow(new_row)

    def _confirm_unsaved(self, name: str) -> int:
        """弹出未保存提示，返回 QMessageBox 按钮。"""
        box = QMessageBox(self)
        box.setWindowTitle(labels.ANNOT_UNSAVED_TITLE)
        box.setText(labels.ANNOT_UNSAVED_PROMPT_TEMPLATE.format(name=name))
        box.setIcon(QMessageBox.Warning)
        box.addButton(labels.ANNOT_UNSAVED_DISCARD, QMessageBox.DestructiveRole)
        save_btn = box.addButton(labels.ANNOT_UNSAVED_SAVE, QMessageBox.AcceptRole)
        box.addButton(labels.ANNOT_UNSAVED_CANCEL, QMessageBox.RejectRole)
        box.setDefaultButton(save_btn)
        box.exec_()
        clicked = box.clickedButton()
        if clicked == save_btn:
            # 保存当前改动，再继续切换
            self._on_save_annotation()
            return QMessageBox.Save
        if box.buttonRole(clicked) == QMessageBox.DestructiveRole:
            return QMessageBox.Discard
        return QMessageBox.Cancel

    def _on_zoom_changed(self, zoom: float) -> None:
        """画布缩放变化时刷新百分比显示。"""
        self._zoom_pct.setText(labels.ANNOT_ZOOM_PCT_TEMPLATE.format(
            pct=int(round(zoom * self._s.ANNOT_ZOOM_PCT_SCALE)),
        ))

    def confirm_close(self) -> bool:
        """关闭应用前确认未保存标注。返回 True 表示允许关闭。"""
        if (self._canvas is None or self._current_entry is None
                or not self._canvas.is_dirty):
            return True
        ret = self._confirm_unsaved(self._current_entry.image_name)
        return ret != QMessageBox.Cancel

    # -- 画布对象变化：刷新对象列表与角标 ----------------------------------------
    def _on_annotations_changed(self) -> None:
        if self._current_entry is None:
            return
        objs = self._canvas.export_objects() if self._canvas else []
        self._refresh_annotation_view(objs)

    def _refresh_annotation_view(self, objs) -> None:
        entry = self._current_entry
        series = entry.series if entry else "--"
        n = len(objs)
        self._canvas_corner_lb.setText(
            "{series} · {n} OBJECTS · READY".format(series=series or "--", n=n),
        )
        self._footer_count.setText(str(n))
        self._object_list.clear()
        if objs:
            for o in objs:
                self._object_list.addItem(labels.ANNOT_OBJECT_ENTRY.format(
                    name=o["name"],
                    x1=o["xmin"], y1=o["ymin"],
                    x2=o["xmax"], y2=o["ymax"],
                ))
        else:
            self._object_list.addItem(labels.ANNOT_OBJECT_LIST_EMPTY)

    # -- 删除 / 保存 -----------------------------------------------------------
    def _on_delete_selected(self) -> None:
        if self._canvas is not None:
            self._canvas.delete_selected()

    def _on_save_annotation(self) -> None:
        if self._canvas is None or self._current_entry is None:
            return
        objs = self._canvas.export_objects()
        if not objs:
            self._canvas_hint.setText(labels.ANNOT_OBJECTS_EMPTY_SAVE)
            return
        entry = self._current_entry
        w, h = self._canvas.image_size
        xml_dir = self._xml_dir or os.path.dirname(entry.image_path)
        xml_path = os.path.join(xml_dir, entry.stem + ".xml")
        _, _, _, _, write_annotation = self._lazy_annotation_io()
        try:
            write_annotation(xml_path, entry.image_name, w, h, objs)
        except OSError as exc:
            self._canvas_hint.setText(labels.ANNOT_OBJECTS_SAVE_FAILED.format(reason=exc))
            self._canvas_corner_lb.setText("SAVE FAILED")
            return
        # 更新映射状态为已标注
        entry.xml_path = xml_path
        item = self._image_list.item(self._image_list.currentRow())
        if item is not None:
            item.setText(labels.ANNOT_IMAGE_ENTRY.format(
                mark=labels.ANNOT_IMAGE_MAPPED_MARK, name=entry.image_name))
        self._canvas_hint.setText(labels.ANNOT_OBJECTS_SAVED.format(path=xml_path))