"""通用弹框 helper。

抽取自 main_window._on_stop_all 与 detail_window._on_cd_cancel_requested
两处同款 QMessageBox 构造逻辑（重复 ~20 行 × 2 处）。
"""
from typing import Callable, Optional

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.core.labels import SETTINGS_PASSWORD_PLACEHOLDER
from app.core.tokens import DEFAULT_TOKENS

_S = DEFAULT_TOKENS.sizing


def confirm_yes_cancel(
    parent: Optional[QWidget],
    title: str,
    text: str,
    yes_label: str,
    cancel_label: str,
    *,
    icon: QMessageBox.Icon = QMessageBox.Warning,
    default_yes: bool = False,
) -> bool:
    """通用 Yes/Cancel 确认弹框，返回 True = 用户点了 yes。

    Args:
        parent: 父 widget（用于 QMessageBox 居中）
        title: 窗口标题
        text: 提示文本
        yes_label: 左侧按钮文案（如 "是，停止检测"）
        cancel_label: 右侧按钮文案（如 "否，仅停倒计时"）
        icon: 图标类型（默认 Warning；详情页确认取消常用 Question）
        default_yes: True=默认焦点 yes，False=默认焦点 cancel（更安全）

    Returns:
        True 用户点击 yes；False 点击 cancel 或关闭弹框

    Examples:
        >>> if confirm_yes_cancel(self, "停止确认", "确定要停止吗？",
        ...                       "停止", "取消", default_yes=False):
        ...     do_stop()
    """
    box = QMessageBox(parent)
    box.setIcon(icon)
    box.setWindowTitle(title)
    box.setText(text)
    yes_btn = box.addButton(yes_label, QMessageBox.YesRole)
    cancel_btn = box.addButton(cancel_label, QMessageBox.RejectRole)
    box.setDefaultButton(yes_btn if default_yes else cancel_btn)
    box.exec_()
    return box.clickedButton() is yes_btn


class PasswordDialog(QDialog):
    """密码输入对话框：标题 + 提示 + 密码框 + 错误提示 + 确认/取消。

    文本一律由调用方传入（来自 labels），保持本模块无用户可见文案。
    错误重试循环在 `request()` 内完成：密码错误时停留在对话框内提示，
    直到输入正确或取消，无需调用方反复弹窗。
    """

    def __init__(
        self,
        parent: Optional[QWidget],
        title: str,
        hint: str,
        confirm_label: str,
        cancel_label: str,
        error_text: str,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("passwordDialog")
        self.setWindowTitle(title)
        self.setModal(True)
        self._verify: Optional[Callable[[str], bool]] = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(
            _S.PASSWORD_DIALOG_MARGIN_H,
            _S.PASSWORD_DIALOG_MARGIN_V,
            _S.PASSWORD_DIALOG_MARGIN_H,
            _S.PASSWORD_DIALOG_MARGIN_V,
        )
        lay.setSpacing(_S.PASSWORD_DIALOG_SPACING)

        title_lb = QLabel(title)
        title_lb.setObjectName("passwordTitle")
        lay.addWidget(title_lb)

        if hint:
            hint_lb = QLabel(hint)
            hint_lb.setObjectName("passwordHint")
            hint_lb.setWordWrap(True)
            lay.addWidget(hint_lb)

        self._edit = QLineEdit()
        self._edit.setObjectName("passwordEdit")
        self._edit.setEchoMode(QLineEdit.Password)
        self._edit.setPlaceholderText(SETTINGS_PASSWORD_PLACEHOLDER)
        self._edit.returnPressed.connect(self._on_confirm)
        lay.addWidget(self._edit)

        self._error = QLabel(error_text)
        self._error.setObjectName("passwordError")
        self._error.hide()
        lay.addWidget(self._error)

        btns = QHBoxLayout()
        btns.setSpacing(_S.PASSWORD_DIALOG_SPACING)
        btns.addStretch(1)
        cancel_btn = QPushButton(cancel_label)
        cancel_btn.setObjectName("passwordCancel")
        cancel_btn.setCursor(Qt.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)
        btns.addWidget(cancel_btn)
        confirm_btn = QPushButton(confirm_label)
        confirm_btn.setObjectName("passwordConfirm")
        confirm_btn.setCursor(Qt.PointingHandCursor)
        confirm_btn.setDefault(True)
        confirm_btn.clicked.connect(self._on_confirm)
        btns.addWidget(confirm_btn)
        lay.addLayout(btns)

    def _on_confirm(self) -> None:
        """确认：验证通过则 accept，否则显示错误并清空重试。"""
        if self._verify is not None and self._verify(self._edit.text()):
            self.accept()
            return
        self._error.show()
        self._edit.clear()
        self._edit.setFocus()

    @staticmethod
    def request(
        parent: Optional[QWidget],
        verify: Callable[[str], bool],
        title: str,
        hint: str,
        confirm_label: str,
        cancel_label: str,
        error_text: str,
    ) -> bool:
        """弹出密码框直到验证通过或取消。返回 True = 验证通过。"""
        dlg = PasswordDialog(
            parent, title, hint, confirm_label, cancel_label, error_text,
        )
        dlg._verify = verify
        return dlg.exec_() == QDialog.Accepted
