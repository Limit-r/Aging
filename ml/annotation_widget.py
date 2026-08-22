# -*- coding: utf-8 -*-
"""数据标注 - 画框标注器（QGraphicsView）。

数据中心「数据标注」页的 Phase B 核心组件：
- 在图片上显示已有 VOC XML 标注框（矩形 + 类别标签）
- 画框（W 进入画框模式，拖拽创建；需先选活动类别）
- 点选 / 移动 / 调整大小 / 修改类别 / 删除已有框
- 撤销 / 重做（Ctrl+Z / Ctrl+Y）
- 脏标记（is_dirty）与保存 API，供上层处理未保存提示

与 labelImg 对齐的快捷键（按键在此组件内处理，导航类信号上抛给 data_page）：
- W         进入「画框」模式（需活动类别）；Esc 退出
- Del       删除选中框
- Ctrl+Z    撤销
- Ctrl+Y    重做
- Ctrl+E    修改选中框类别（循环切换）
- Ctrl+S    保存（发 save_requested 信号，由上层写 XML）
- D / A     下一张 / 上一张（发 navigate_signal，由上层切换图片）
- +/- / 滚轮  缩放；0 适应视图；1 原始大小

设计要点：
- 纯 PyQt5 + 标准库实现，不 import torch / opencv / openvino，懒加载轻量。
- 不依赖 app.core：颜色 / 线宽等视觉量由上层（data_page）注入。
- 坐标均以图片原始像素为单位（scene 坐标 = 图片像素），便于直接写 XML。
- 只读已有数据，标注结果通过 API 导出，由上层决定保存。

对外主入口：
    AnnotationCanvas(categories, palette, selected_color, border_w, ...)
"""

import os

from PyQt5.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QCursor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PyQt5.QtWidgets import (
    QGraphicsItem, QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsScene,
    QGraphicsTextItem, QGraphicsView,
)

# 手柄角点索引（用于调整大小）
_TL, _TR, _BR, _BL = 0, 1, 2, 3
_HANDLE_KEYS = {_TL: "tl", _TR: "tr", _BR: "br", _BL: "bl"}
_HANDLE_SIZE = 8          # 手柄边长（视图固定像素，非场景坐标）
_HANDLE_HIT_R = 6         # 手柄命中半径（场景坐标）

# 模式
_MODE_CREATE = "create"    # 画框模式
_MODE_EDIT = "edit"        # 编辑模式（点选/移动/调整）


class _BoxItem(QGraphicsRectItem):
    """一个标注框：矩形 + 类别标签 + 选中手柄。"""

    def __init__(self, rect: QRectF, name: str, color: QColor,
                 border_w: int, sel_border_w: int, parent=None):
        super().__init__(rect, parent)
        self._name = name
        self._color = color
        self._border_w = border_w
        self._sel_border_w = sel_border_w
        self._font = QFont("Consolas, monospace")
        self._font.setPixelSize(11)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemIsMovable, False)  # 移动由 canvas 托管，避免历史紊乱
        self.setZValue(2)
        self._refresh_pen()

    # -- 属性 -------------------------------------------------------------
    @property
    def name(self):
        return self._name

    def set_name(self, name: str, color: QColor) -> None:
        self._name = name
        self._color = color
        self._refresh_pen()
        self.update()

    def set_color(self, color: QColor) -> None:
        self._color = color
        self._refresh_pen()
        self.update()

    def _refresh_pen(self) -> None:
        if self.isSelected():
            pen = QPen(self._color, self._sel_border_w)
        else:
            pen = QPen(self._color, self._border_w)
        self.setPen(pen)

    # -- 手柄（仅选中时绘制与命中）----------------------------------------
    def handle_positions(self):
        """返回 4 个角点在 item 局部坐标的 QPointF 列表。"""
        r = self.rect()
        return [r.topLeft(), r.topRight(), r.bottomRight(), r.bottomLeft()]

    def paint(self, painter, option, widget=None) -> None:
        super().paint(painter, option, widget)
        # 类别标签：画在矩形内部顶部，避免超出 boundingRect 造成移动拖影
        label = self._name
        font = self._font
        painter.setFont(font)
        metrics = painter.fontMetrics()
        tw, th = metrics.horizontalAdvance(label), metrics.height()
        x, y = self.rect().left(), self.rect().top()
        bg = QColor(self._color)
        bg.setAlpha(200)
        painter.setPen(Qt.NoPen)
        painter.setBrush(bg)
        label_rect = QRectF(x, y, tw + 6, th + 2)
        painter.drawRect(label_rect)
        painter.setPen(Qt.white)
        painter.drawText(label_rect.adjusted(3, 0, -3, 0), Qt.AlignVCenter | Qt.AlignLeft, label)
        # 选中时画 4 角手柄（固定视图像素尺寸，不受缩放影响）
        if self.isSelected():
            painter.save()
            # 切到视图坐标：逆变换 worldMatrix，随后按视图像素绘制
            inv = painter.worldTransform().inverted()[0]
            painter.setWorldTransform(inv)
            painter.setPen(QPen(QColor(255, 255, 255), 1))
            painter.setBrush(QColor(0, 191, 255))
            for hp in self.handle_positions():
                sp = self.mapToScene(hp)
                vp = self.mapFromScene(sp)
                painter.drawRect(QRectF(
                    vp.x() - _HANDLE_SIZE / 2, vp.y() - _HANDLE_SIZE / 2,
                    _HANDLE_SIZE, _HANDLE_SIZE))
            painter.restore()

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemSelectedChange:
            self._refresh_pen()
        return super().itemChange(change, value)


class AnnotationCanvas(QGraphicsView):
    """标注画布：显示图片 + 可编辑标注框。"""

    # 信号
    selection_changed = pyqtSignal()
    annotations_changed = pyqtSignal()
    dirty_changed = pyqtSignal(bool)
    navigate_signal = pyqtSignal(int)      # -1 上一张 / +1 下一张
    save_requested = pyqtSignal()
    zoom_changed = pyqtSignal(float)
    mode_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setRenderHint(QPainter.Antialiasing, True)
        self.setRenderHint(QPainter.SmoothPixmapTransform, True)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setBackgroundBrush(QColor(8, 12, 24))

        self._pixmap_item = None
        self._boxes: list[_BoxItem] = []
        self._category_color = {}
        self._categories = []
        self._active_category = None
        self._border_w = 2
        self._sel_border_w = 3
        self._min_size = 10
        self._padding = 8
        self._image_path = None
        self._image_w = 0
        self._image_h = 0

        self._mode = _MODE_EDIT
        self._dirty = False

        # 历史栈（元素为 (name, QRectF) 列表）
        self._undo_stack = []
        self._redo_stack = []

        # 画框状态
        self._drawing = False
        self._draw_start = QPointF()
        self._draw_item = None
        # 调整大小 / 移动状态
        self._resizing = False
        self._resize_handle = None
        self._resize_box = None
        self._resize_start_rect = None
        self._move_start = None
        self._move_box = None
        self._move_orig = None

        self.setObjectName("annotationCanvas")

    # -- 配置 -------------------------------------------------------------
    def configure(self, categories, palette, selected_color,
                  border_w=2, sel_border_w=3, min_size=10, padding=8) -> None:
        """注入类别与视觉量（由上层 data_page 传入 tokens 值）。"""
        self._categories = list(categories)
        self._border_w = border_w
        self._sel_border_w = sel_border_w
        self._min_size = min_size
        self._padding = padding
        self._category_color = {}
        for i, cat in enumerate(self._categories):
            rgb = palette[i % len(palette)]
            self._category_color[cat] = QColor(*rgb)
        self._selected_color = QColor(*selected_color)

    @property
    def active_category(self):
        return self._active_category

    def set_active_category(self, name) -> None:
        self._active_category = name
        if name:
            self.set_mode(_MODE_CREATE)

    @property
    def mode(self):
        return self._mode

    def set_mode(self, mode: str) -> None:
        if mode == self._mode:
            return
        self._mode = mode
        if mode == _MODE_CREATE:
            self.setCursor(QCursor(Qt.CrossCursor))
        else:
            self.setCursor(QCursor(Qt.ArrowCursor))
        self.mode_changed.emit(mode)

    @property
    def is_dirty(self) -> bool:
        return self._dirty

    @property
    def image_path(self):
        return self._image_path

    # -- 图片 -------------------------------------------------------------
    def load_pixmap(self, image_path: str) -> bool:
        """加载图片并重置画布。失败返回 False。"""
        if not image_path or not os.path.isfile(image_path):
            return False
        pix = QPixmap(image_path)
        if pix.isNull():
            return False
        self._scene.clear()
        self._pixmap_item = None
        self._boxes = []
        self._image_path = image_path
        self._image_w, self._image_h = pix.width(), pix.height()
        self._pixmap_item = self._scene.addPixmap(pix)
        self._pixmap_item.setPos(self._padding, self._padding)
        self._pixmap_item.setZValue(0)
        self._pixmap_item.setFlag(QGraphicsItem.ItemIsSelectable, False)
        self._scene.setSceneRect(
            QRectF(0, 0, self._image_w + 2 * self._padding,
                   self._image_h + 2 * self._padding))
        self._clear_history()
        self._set_dirty(False)
        self._fit_to_view()
        return True

    def _fit_to_view(self) -> None:
        self.resetTransform()
        if self._image_w and self._image_h:
            margin = 8
            view_w = max(1, self.viewport().width() - 2 * margin)
            view_h = max(1, self.viewport().height() - 2 * margin)
            hpad = 2 * self._padding
            scale = min(view_w / (self._image_w + hpad),
                        view_h / (self._image_h + hpad))
            self.scale(scale, scale)
            self.ensureVisible(self._scene.sceneRect(), margin, margin)
        self._emit_zoom()

    def _emit_zoom(self) -> None:
        self.zoom_changed.emit(self.current_zoom)

    @property
    def current_zoom(self) -> float:
        t = self.transform()
        return t.m11()

    @property
    def image_size(self):
        return (self._image_w, self._image_h)

    # -- 历史 / 脏标记 ----------------------------------------------------
    def _snapshot(self):
        return [(b.name, QRectF(b.rect())) for b in self._boxes]

    def _restore(self, snap) -> None:
        for b in list(self._boxes):
            self._scene.removeItem(b)
        self._boxes = []
        for name, rect in snap:
            color = self._category_color.get(name, self._selected_color)
            item = _BoxItem(rect, name, color,
                            self._border_w, self._sel_border_w)
            self._scene.addItem(item)
            self._boxes.append(item)

    def _push_history(self) -> None:
        self._undo_stack.append(self._snapshot())
        if len(self._undo_stack) > 200:
            self._undo_stack.pop(0)
        self._redo_stack.clear()
        self._set_dirty(True)

    def undo(self) -> None:
        if not self._undo_stack:
            return
        self._redo_stack.append(self._snapshot())
        snap = self._undo_stack.pop()
        self._restore(snap)
        self._set_dirty(True)
        self.annotations_changed.emit()

    def redo(self) -> None:
        if not self._redo_stack:
            return
        self._undo_stack.append(self._snapshot())
        snap = self._redo_stack.pop()
        self._restore(snap)
        self._set_dirty(True)
        self.annotations_changed.emit()

    def _clear_history(self) -> None:
        self._undo_stack.clear()
        self._redo_stack.clear()

    @property
    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo_stack)

    def _set_dirty(self, value: bool) -> None:
        if value != self._dirty:
            self._dirty = value
            self.dirty_changed.emit(value)

    def mark_saved(self) -> None:
        self._set_dirty(False)

    # -- 标注框 -----------------------------------------------------------
    def _add_box(self, name: str, x: float, y: float, w: float, h: float) -> _BoxItem:
        color = self._category_color.get(name, self._selected_color)
        rect = QRectF(x + self._padding, y + self._padding, w, h)
        item = _BoxItem(rect, name, color,
                        self._border_w, self._sel_border_w)
        item.setSelected(False)
        self._scene.addItem(item)
        self._boxes.append(item)
        return item

    def set_objects(self, objects) -> None:
        """objects: list[dict]，字段 name/xmin/ymin/xmax/ymax。"""
        if self._pixmap_item is None:
            return
        for box in self._boxes:
            self._scene.removeItem(box)
        self._boxes = []
        for o in objects:
            self._add_box(
                o["name"], o["xmin"], o["ymin"],
                o["xmax"] - o["xmin"], o["ymax"] - o["ymin"],
            )
        self._clear_history()
        self._set_dirty(False)
        self.annotations_changed.emit()

    def export_objects(self):
        """导出当前全部对象为 list[dict]。坐标已还原为图片像素。"""
        result = []
        for box in self._boxes:
            r = box.rect()
            x = r.left() - self._padding
            y = r.top() - self._padding
            result.append({
                "name": box.name,
                "xmin": int(round(x)),
                "ymin": int(round(y)),
                "xmax": int(round(x + r.width())),
                "ymax": int(round(y + r.height())),
                "difficult": 0,
            })
        return result

    def selected_box(self):
        for box in self._boxes:
            if box.isSelected():
                return box
        return None

    def delete_selected(self) -> bool:
        box = self.selected_box()
        if box is None:
            return False
        self._push_history()
        self._scene.removeItem(box)
        self._boxes.remove(box)
        self.annotations_changed.emit()
        return True

    def cycle_selected_category(self) -> None:
        """修改选中框类别：在当前类别列表中循环切换。"""
        box = self.selected_box()
        if box is None or not self._categories:
            return
        self._push_history()
        cur = box.name
        try:
            idx = self._categories.index(cur)
        except ValueError:
            idx = -1
        new = self._categories[(idx + 1) % len(self._categories)]
        box.set_name(new, self._category_color.get(new, self._selected_color))
        self.annotations_changed.emit()

    # -- 鼠标交互 ---------------------------------------------------------
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            pos = self.mapToScene(event.pos())
            box = self._hit_box(pos)
            if self._mode == _MODE_CREATE:
                # 绘制模式：任意位置（含已有框内/重叠处）均开始画新框
                self._drawing = True
                self._draw_start = pos
                self._draw_item = self._make_draw_item(pos)
                self.setDragMode(QGraphicsView.NoDrag)
                return
            # 编辑模式
            if box is not None:
                self._select_only(box)
                handle = self._handle_at_view(box, event.pos())
                if handle is not None:
                    # 开始调整大小
                    self._resizing = True
                    self._resize_handle = handle
                    self._resize_box = box
                    self._resize_start_rect = QRectF(box.rect())
                    return
                # 开始移动（按下即定格基准，立即跟随）
                self._move_box = box
                self._move_orig = QRectF(box.rect())
                self._move_start = pos
                self.setDragMode(QGraphicsView.NoDrag)
                self.selection_changed.emit()
                return
            # 未命中 item，但可能恰好点在某个框的角手柄上（手柄在角外）
            for b in self._boxes:
                h = self._handle_at_view(b, event.pos())
                if h is not None:
                    self._select_only(b)
                    self._resizing = True
                    self._resize_handle = h
                    self._resize_box = b
                    self._resize_start_rect = QRectF(b.rect())
                    return
            # 空白处：取消选中
            self._clear_selection()
            super().mousePressEvent(event)
            return
        super().mousePressEvent(event)
        self.selection_changed.emit()

    def _hit_box(self, pos: QPointF):
        item = self._scene.itemAt(pos, self.transform())
        if isinstance(item, _BoxItem):
            return item
        return None

    def _handle_at_view(self, box, view_pos) -> int or None:
        """按视图像素判断 view_pos 是否命中 box 的某个角手柄。"""
        for idx, hp in enumerate(box.handle_positions()):
            sp = box.mapToScene(hp)
            vp = self.mapFromScene(sp)
            if (vp - QPointF(view_pos)).manhattanLength() <= _HANDLE_HIT_R:
                return idx
        return None

    def _select_only(self, box) -> None:
        for b in self._boxes:
            b.setSelected(b is box)
        self.selection_changed.emit()

    def _clear_selection(self) -> None:
        for b in self._boxes:
            b.setSelected(False)
        self.selection_changed.emit()

    def _make_draw_item(self, pos: QPointF):
        color = self._category_color.get(self._active_category, self._selected_color)
        rect = QRectF(pos, pos)
        pen = QPen(color, 2, Qt.DashLine)
        item = QGraphicsRectItem(rect)
        item.setPen(pen)
        # 半透明填充，让待画区域实时可见
        fill = QColor(color)
        fill.setAlpha(40)
        item.setBrush(fill)
        item.setZValue(3)
        self._scene.addItem(item)
        return item

    def mouseMoveEvent(self, event):
        pos = self.mapToScene(event.pos())
        if self._drawing and self._draw_item is not None:
            r = QRectF(self._draw_start, pos).normalized()
            self._draw_item.setRect(r)
            return
        if self._resizing and self._resize_box is not None:
            self._apply_resize(pos)
            return
        if self._move_box is not None and self._move_orig is not None:
            delta = pos - self._move_start
            new_rect = QRectF(self._move_orig).translated(delta)
            self._clamp_rect(new_rect)
            self._move_box.setRect(new_rect)
            return
        super().mouseMoveEvent(event)

    def _apply_resize(self, pos: QPointF) -> None:
        box = self._resize_box
        base = self._resize_start_rect
        handle = self._resize_handle
        r = QRectF(base)
        if handle == _TL:
            r.setTopLeft(QPointF(min(pos.x(), r.right()), min(pos.y(), r.bottom())))
        elif handle == _TR:
            r.setTopRight(QPointF(max(pos.x(), r.left()), min(pos.y(), r.bottom())))
        elif handle == _BR:
            r.setBottomRight(QPointF(max(pos.x(), r.left()), max(pos.y(), r.top())))
        elif handle == _BL:
            r.setBottomLeft(QPointF(min(pos.x(), r.right()), max(pos.y(), r.top())))
        if r.width() >= self._min_size and r.height() >= self._min_size:
            box.setRect(r)

    def _clamp_rect(self, rect: QRectF) -> None:
        """把移动后的矩形限制在图片范围内。"""
        min_x = self._padding
        min_y = self._padding
        max_x = self._image_w + self._padding if self._image_w else rect.right()
        max_y = self._image_h + self._padding if self._image_h else rect.bottom()
        if rect.left() < min_x:
            rect.moveLeft(min_x)
        if rect.top() < min_y:
            rect.moveTop(min_y)
        if rect.right() > max_x:
            rect.moveRight(max_x)
        if rect.bottom() > max_y:
            rect.moveBottom(max_y)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self._drawing:
                self._drawing = False
                self.setDragMode(QGraphicsView.RubberBandDrag)
                if self._draw_item is not None:
                    r = self._draw_item.rect()
                    self._scene.removeItem(self._draw_item)
                    self._draw_item = None
                    if r.width() >= self._min_size and r.height() >= self._min_size:
                        self._push_history()
                        name = self._active_category
                        self._add_box(
                            name, r.left() - self._padding, r.top() - self._padding,
                            r.width(), r.height(),
                        )
                        self.annotations_changed.emit()
                        # 保持绘制模式，便于连续标注多个同类框，无需重复选取类别
                return
            if self._resizing:
                self._resizing = False
                self._resize_box = None
                self._resize_handle = None
                self._push_history()
                self.setDragMode(QGraphicsView.RubberBandDrag)
                self.annotations_changed.emit()
                return
            if self._move_box is not None:
                moved = self._move_orig is not None \
                    and self._move_box.rect() != self._move_orig
                self._move_box = None
                self._move_start = None
                self._move_orig = None
                self.setDragMode(QGraphicsView.RubberBandDrag)
                if moved:
                    self._push_history()
                    self.annotations_changed.emit()
                return
        super().mouseReleaseEvent(event)
        self.selection_changed.emit()

    # -- 键盘 / 快捷键 ----------------------------------------------------
    def keyPressEvent(self, event):
        key = event.key()
        mods = event.modifiers()

        # Ctrl 组合
        if mods & Qt.ControlModifier:
            if key == Qt.Key_Z:
                self.undo()
                return
            if key == Qt.Key_Y:
                self.redo()
                return
            if key == Qt.Key_S:
                self.save_requested.emit()
                return
            if key == Qt.Key_E:
                self.cycle_selected_category()
                return
            super().keyPressEvent(event)
            return

        # 无修饰
        if key == Qt.Key_W:
            if self._active_category:
                self.set_mode(_MODE_CREATE)
            return
        if key == Qt.Key_Escape:
            if self._mode == _MODE_CREATE:
                self.set_mode(_MODE_EDIT)
            return
        if key == Qt.Key_Delete or key == Qt.Key_Backspace:
            self.delete_selected()
            return
        if key == Qt.Key_D:
            self.navigate_signal.emit(1)
            return
        if key == Qt.Key_A:
            self.navigate_signal.emit(-1)
            return
        if key == Qt.Key_Plus or key == Qt.Key_Equal:
            self._zoom(1.2)
            return
        if key == Qt.Key_Minus:
            self._zoom(1 / 1.2)
            return
        if key == Qt.Key_0:
            self._fit_to_view()
            return
        if key == Qt.Key_1:
            self._zoom_absolute(1.0)
            return
        super().keyPressEvent(event)

    def _zoom(self, factor: float) -> None:
        self.scale(factor, factor)
        self._emit_zoom()

    def _zoom_absolute(self, value: float) -> None:
        cur = self.current_zoom
        if cur:
            self.scale(value / cur, value / cur)
            self._emit_zoom()

    def wheelEvent(self, event):
        # labelImg 风格：滚轮缩放
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self._zoom(factor)
        event.accept()

    def fit_to_view_trigger(self) -> None:
        self._fit_to_view()

    def zoom_in(self) -> None:
        self._zoom(1.2)

    def zoom_out(self) -> None:
        self._zoom(1 / 1.2)

    def zoom_to_original(self) -> None:
        self._zoom_absolute(1.0)