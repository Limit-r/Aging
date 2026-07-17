"""Qt signal 桥接：把 logger 消息推到 UI 线程。

约束：emit_log_message() 可以从任何线程调用，内部用 QMetaObject.invokeMethod
切到 Qt 主线程 emit。QtLogHandler 在主线程接收后 emit 同名 signal。
"""

import logging
from enum import IntEnum

from PyQt5.QtCore import QObject, pyqtSignal


class LogLevel(IntEnum):
    DEBUG = 0
    INFO = 1
    WARNING = 2
    ERROR = 3
    CRITICAL = 4


class _LogSignalBus(QObject):
    """单实例 Qt signal 总线。"""
    message = pyqtSignal(int, str)  # (LogLevel, message)


_BUS = _LogSignalBus()


def log_message_emitted() -> pyqtSignal:
    """供 MainWindow / DetailWindow 连接。"""
    return _BUS.message


def emit_log_message(level: LogLevel, message: str) -> None:
    """从任意线程调用：直接 emit（PyQt cross-thread 自动 queued）。"""
    try:
        _BUS.message.emit(int(level), str(message))
    except RuntimeError:
        # 对象已删除（应用退出阶段）
        pass


class QtLogHandler(logging.Handler):
    """标准 logging.Handler 适配器：把 LogRecord 转 LogLevel + message 推到 Qt signal。"""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = getattr(LogLevel, record.levelname, LogLevel.INFO)
            msg = self.format(record)
            emit_log_message(level, msg)
        except Exception:
            self.handleError(record)
