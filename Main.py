"""应用入口（v3.0）。

启动顺序：
1. configure_logging()  初始化 logger
2. config_registry.scan_and_report()  启动期硬编码扫描（不阻断）
3. install_exception_hooks(app)  全局异常钩子
4. QApplication 启动
5. build_stylesheet() 应用 QSS
6. HomePage 显示（3D 主页 + 二级页面）
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt5.QtWidgets import QApplication

from app.core.config_registry import scan_and_report
from app.core.tokens import DEFAULT_TOKENS
from app.observability import configure_logging, install_exception_hooks
from app.observability.logger import get_logger
from app.styles import build_stylesheet
from app.ui.home_page import HomePage


def main() -> int:
    configure_logging()
    _log = get_logger("app.system")
    _log.info("aging system v3.0 starting...")

    # 启动期硬编码扫描（Phase 4-D）
    # 设计：扫描全工程，检查颜色/数字/用户可见文本是否违反三件套边界
    # 不阻断启动（仅记录到 logs/app.log）；扫描结果用于回归守护
    scan_and_report(root="app")

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
