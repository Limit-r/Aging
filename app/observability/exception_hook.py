"""全局异常钩子：Python 顶层 + Qt 事件循环 + 后台线程。"""

import logging
import sys
import threading
import traceback
from typing import Callable, Optional

from app.observability.logger import get_logger
from app.observability.log_signals import emit_log_message, LogLevel


_log = get_logger("app.system")
_exception_handler: Optional[Callable[[str, str], None]] = None


def set_exception_handler(handler: Callable[[str, str], None]) -> None:
    """由 MainWindow 注册，用于把异常显示到状态栏/UI。"""
    global _exception_handler
    _exception_handler = handler


def install_exception_hooks(app=None) -> None:
    """3 个钩子：sys.excepthook / threading.excepthook / QApplication.notify。

    参数 app：QApplication 实例，用于 wrap notify。
    """
    # ---- 1) Python 顶层 ------------------------------------------------
    def sys_hook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        _log.critical("uncaught exception:\n%s", msg)
        _notify_ui("CRITICAL", str(exc_value) or exc_type.__name__)
        if _exception_handler:
            try:
                _exception_handler("CRITICAL", str(exc_value))
            except Exception:
                pass

    sys.excepthook = sys_hook

    # ---- 2) 后台线程 ---------------------------------------------------
    def thread_hook(args):
        msg = (
            f"thread {args.thread.name!r} crashed: "
            f"{args.exc_value!r}"
        )
        _log.critical(msg)
        _notify_ui("CRITICAL", str(args.exc_value))

    threading.excepthook = thread_hook

    # ---- 3) Qt 事件循环 ------------------------------------------------
    if app is not None:
        _wrap_qapplication_notify(app)


def _wrap_qapplication_notify(app) -> None:
    """重写 QApplication.notify 截获 Qt 内部事件处理异常。"""
    original_notify = app.notify

    def safe_notify(receiver, event):
        try:
            return original_notify(receiver, event)
        except Exception as e:
            _log.error(
                "qt event handler error: receiver=%r event=%r error=%r",
                receiver.__class__.__name__,
                event.type().__name__ if hasattr(event, "type") else "?",
                e,
            )
            _notify_ui("ERROR", f"{receiver.__class__.__name__}: {e}")
            return False  # 标记事件未处理，但不崩

    app.notify = safe_notify


def _notify_ui(level: str, message: str) -> None:
    """统一入口：把异常/告警推送到 UI（信号）。"""
    level_map = {
        "CRITICAL": LogLevel.CRITICAL,
        "ERROR":    LogLevel.ERROR,
        "WARNING":  LogLevel.WARNING,
    }
    emit_log_message(level_map.get(level, LogLevel.ERROR), message)
