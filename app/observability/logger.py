"""统一 logger 配置：文件轮转 + 控制台 + Qt signal。"""

import logging
import logging.handlers
from pathlib import Path
from typing import Optional

from app.core import config
from app.observability.log_signals import QtLogHandler


_LOGGER_ROOT_NAME = "app"
_INITIALIZED = False

# 日志格式（file + console 共享，仅 datefmt 不同）
DEFAULT_LOG_FMT = "%(asctime)s | %(levelname)-7s | %(name)-15s | %(message)s"
DEFAULT_FILE_DATEFMT = "%Y-%m-%d %H:%M:%S"
DEFAULT_CONSOLE_DATEFMT = "%H:%M:%S"


def configure_logging(
    log_dir: Optional[str] = None,
    level: Optional[str] = None,
) -> None:
    """初始化 logger。幂等，重复调用不会重复安装 handler。"""
    global _INITIALIZED
    if _INITIALIZED:
        return

    log_dir = log_dir or config.LOG_DIR
    level = level or config.LOG_LEVEL

    Path(log_dir).mkdir(parents=True, exist_ok=True)

    root = logging.getLogger(_LOGGER_ROOT_NAME)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.propagate = False  # 避免传到 root logger

    # ---- 1) 文件 handler：按天轮转 ----------------------------------------
    file_handler = logging.handlers.TimedRotatingFileHandler(
        filename=str(Path(log_dir) / "app.log"),
        when="midnight",
        backupCount=14,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        fmt=DEFAULT_LOG_FMT,
        datefmt=DEFAULT_FILE_DATEFMT,
    ))
    root.addHandler(file_handler)

    # ---- 2) 控制台 handler：带颜色 ---------------------------------------
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(_ColorFormatter(
        fmt=DEFAULT_LOG_FMT,
        datefmt=DEFAULT_CONSOLE_DATEFMT,
    ))
    root.addHandler(console)

    # ---- 3) Qt signal handler：推 UI 状态栏 ------------------------------
    qt_handler = QtLogHandler()
    qt_handler.setLevel(logging.WARNING)
    qt_handler.setFormatter(logging.Formatter(fmt="%(message)s"))
    root.addHandler(qt_handler)

    _INITIALIZED = True
    root.info("logger configured (level=%s, dir=%s)", level, log_dir)


def get_logger(name: str) -> logging.Logger:
    """获取子 logger。建议传 `__name__`，自动归属 app.* 命名空间。"""
    if not name.startswith(_LOGGER_ROOT_NAME):
        name = f"{_LOGGER_ROOT_NAME}.{name}"
    return logging.getLogger(name)


# ---- ANSI 颜色 formatter（控制台） -----------------------------------------
class _ColorFormatter(logging.Formatter):
    _RESET = "\x1b[0m"
    _COLORS = {
        logging.DEBUG:    "\x1b[38;5;244m",  # 灰
        logging.INFO:     "\x1b[38;5;39m",   # 蓝
        logging.WARNING:  "\x1b[38;5;214m",  # 橙
        logging.ERROR:    "\x1b[38;5;203m",  # 红
        logging.CRITICAL: "\x1b[1;38;5;201m",# 亮红
    }

    def format(self, record: logging.LogRecord) -> str:
        color = self._COLORS.get(record.levelno, "")
        message = super().format(record)
        return f"{color}{message}{self._RESET}" if color else message
