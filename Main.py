"""应用入口（v3.0）。

启动顺序：
1. configure_logging()  初始化 logger
2. install_exception_hooks(app)  全局异常钩子
3. QApplication 启动
4. build_stylesheet() 应用 QSS
5. HomePage 显示（3D 主页 + 二级页面）
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt5.QtWidgets import QApplication

from app.core.tokens import DEFAULT_TOKENS
from app.observability import configure_logging, install_exception_hooks
from app.observability.logger import get_logger
from app.styles import build_stylesheet
from app.ui.home_page import HomePage


def main() -> int:
    configure_logging()
    _log = get_logger("app.system")
    _log.info("aging system v3.0 starting...")

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    install_exception_hooks(app)

    app.setStyleSheet(build_stylesheet(DEFAULT_TOKENS))

    win = HomePage()
    win.show()

    _log.info("ui ready, entering event loop")
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
