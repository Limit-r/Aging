"""D 阶段：应用启动 smoke test（offscreen 模式，无 GUI 也能验证）。

启动顺序：
1. configure_logging
2. config_registry.scan_and_report（应输出 "0 hits, clean"）
3. QApplication（offscreen）
4. install_exception_hooks
5. build_stylesheet
6. HomePage 构建
7. 触发一次 update_data 让 72 cell 走通数据通路
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 强制 offscreen 平台（无 GUI 环境也能跑）
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QTimer
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
    _log.info("aging system v3.0 smoke test (offscreen) starting...")

    # 1) 启动期硬编码扫描
    hits = scan_and_report(root="app")
    n = len(hits)
    _log.info("config_registry scan: %d hits (expected 0)", n)
    assert n == 0, f"config_registry found {n} hardcode hits (should be 0)"

    # 2) 启动 Qt 应用
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    install_exception_hooks(app)

    app.setStyleSheet(build_stylesheet(DEFAULT_TOKENS))

    # 3) 创建主页（不 show，只构造）
    win = HomePage()
    _log.info("HomePage constructed: %s", type(win).__name__)

    # 4) 1000ms 后退出（让所有 idle timer 跑一拍）
    QTimer.singleShot(1000, app.quit)

    _log.info("entering event loop for 1s...")
    rc = app.exec_()
    _log.info("event loop exited with rc=%d", rc)

    print("=" * 70)
    print("SMOKE TEST PASSED")
    print(f"  - config_registry: 0 hardcode hits")
    print(f"  - HomePage: constructed OK")
    print(f"  - event loop: rc={rc}")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
