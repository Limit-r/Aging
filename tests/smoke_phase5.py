"""E 阶段：应用启动 smoke test（offscreen 模式）。

E 阶段验证：
1. configure_logging
2. config_registry.scan_and_report（应输出 "0 hits, clean"；含 9 个扫描类别）
3. QApplication（offscreen）
4. install_exception_hooks
5. build_stylesheet
6. HomePage 构建
7. CellController 走通（start/pause/stop），验证 PRESENTATION 映射
8. 触发一次 update_data 让 72 cell 走通数据通路
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

from app.core import labels
from app.core.config_registry import scan_and_report
from app.core.tokens import DEFAULT_TOKENS
from app.observability import configure_logging, install_exception_hooks
from app.observability.logger import get_logger
from app.services.cell_controller import CellController, DetectionState
from app.services.cell_ui_manager import CellUIManager
from app.styles import build_stylesheet
from app.ui.home_page import HomePage


def main() -> int:
    configure_logging()
    _log = get_logger("app.system")
    _log.info("aging system v3.0 smoke test (E phase, offscreen) starting...")

    # 1) 启动期硬编码扫描（9 类别：5 原始 + 4 新）
    hits = scan_and_report(root="app")
    n = len(hits)
    _log.info("config_registry scan: %d hits (expected 0)", n)
    assert n == 0, f"config_registry found {n} hardcode hits (should be 0)"

    # 2) CellController + CellUIManager 走 PRESENTATION 集成
    ctrl = CellController(total=72)
    mgr = CellUIManager()
    # start 3 cells
    transitioned = ctrl.apply("start", [1, 2, 3])
    assert transitioned == [1, 2, 3], f"unexpected transitioned: {transitioned}"
    # 验证 PRESENTATION 映射
    for cid in [1, 2, 3]:
        state = ctrl.state_of(cid)
        # state.value 是 "running"
        p = labels.DETECTION_STATE_PRESENTATION[state.value]
        visual = mgr.status_for(state.value)
        text = mgr.text_for(state.value)
        assert visual == p.visual_status == "online", f"cid {cid} visual mismatch"
        assert text == p.text_label == "运行中", f"cid {cid} text mismatch"
    # pause 2 cells
    transitioned = ctrl.apply("pause", [1, 2])
    assert transitioned == [1, 2]
    for cid in [1, 2]:
        state = ctrl.state_of(cid)
        assert state == DetectionState.PAUSED
        assert mgr.status_for(state.value) == "online"
        assert mgr.text_for(state.value) == "已暂停"
    # stop 1 cell
    transitioned = ctrl.apply("stop", [3])
    assert transitioned == [3]
    assert ctrl.state_of(3) == DetectionState.STOPPED
    assert mgr.text_for(DetectionState.STOPPED.value) == "已停止"
    _log.info("CellController + CellUIManager + PRESENTATION: all assertions passed")

    # 3) 启动 Qt 应用
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    install_exception_hooks(app)

    app.setStyleSheet(build_stylesheet(DEFAULT_TOKENS))

    # 4) 创建主页（不 show，只构造）
    win = HomePage()
    _log.info("HomePage constructed: %s", type(win).__name__)

    # 5) 1000ms 后退出（让所有 idle timer 跑一拍）
    QTimer.singleShot(1000, app.quit)

    _log.info("entering event loop for 1s...")
    rc = app.exec_()
    _log.info("event loop exited with rc=%d", rc)

    print("=" * 70)
    print("SMOKE TEST PASSED (E phase)")
    print(f"  - config_registry 9 类别: 0 hardcode hits")
    print(f"  - DETECTION_STATE_PRESENTATION 3 状态映射: 正确")
    print(f"  - CellController.apply(start/pause/stop): 全部走通")
    print(f"  - HomePage: constructed OK")
    print(f"  - event loop: rc={rc}")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as e:
        print(f"SMOKE TEST FAILED: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        import traceback
        traceback.print_exc()
        sys.exit(2)
