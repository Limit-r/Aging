"""通用弹框 helper。

抽取自 main_window._on_stop_all 与 detail_window._on_cd_cancel_requested
两处同款 QMessageBox 构造逻辑（重复 ~20 行 × 2 处）。
"""

from typing import Optional

from PyQt5.QtWidgets import QMessageBox, QWidget


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
