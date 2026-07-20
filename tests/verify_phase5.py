"""E 阶段收尾验证：py_compile + import smoke + config_registry 集成测试。"""
import py_compile
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FILES_TO_COMPILE = [
    # Phase 5 涉及修改的文件
    "app/core/config_registry.py",     # E-1 扩展 4 个新扫描类别
    "app/core/labels.py",              # E-2a DETECTION_STATE_PRESENTATION
    "app/services/cell_controller.py", # E-2c 移除 _pending_countdown
    "app/services/cell_ui_manager.py", # E-2a 走 labels.PRESENTATION
    "app/ui/pages/detail_page.py",     # E-2a + E-2d 状态映射 + try/except 清理
    # 之前阶段已收尾的核心文件
    "app/core/tokens.py",
    "app/core/config.py",
    "app/core/formatting.py",
    "app/ui/nav_bar.py",
    "app/ui/floaters.py",
    "app/ui/home_page.py",
    "app/ui/pages/current_page.py",
    "app/ui/pages/video_page.py",
    "app/widgets/data_cell.py",
    "app/services/countdown.py",
]

MODULES_TO_IMPORT = [
    "app.core.tokens",
    "app.core.config",
    "app.core.labels",
    "app.core.config_registry",
    "app.core.formatting",
    "app.services.cell_controller",
    "app.services.cell_ui_manager",
    "app.services.countdown",
    "app.ui.nav_bar",
    "app.ui.floaters",
    "app.ui.home_page",
    "app.ui.pages.current_page",
    "app.ui.pages.detail_page",
    "app.ui.pages.video_page",
    "app.widgets.data_cell",
]


def main() -> int:
    print("=" * 70)
    print("E 阶段收尾验证：py_compile + import smoke + 集成")
    print("=" * 70)

    # Step 1: py_compile
    print("\n[1/3] py_compile 检查")
    print("-" * 70)
    n_ok, n_fail = 0, 0
    for rel in FILES_TO_COMPILE:
        path = ROOT / rel
        try:
            py_compile.compile(str(path), doraise=True)
            print(f"  [OK]   {rel}")
            n_ok += 1
        except py_compile.PyCompileError as e:
            print(f"  [FAIL] {rel}: {e}")
            n_fail += 1
    print(f"\n  py_compile 汇总: OK={n_ok} FAIL={n_fail}")

    # Step 2: import smoke test
    print("\n[2/3] import smoke test")
    print("-" * 70)
    n_ok, n_fail2 = 0, 0
    for mod in MODULES_TO_IMPORT:
        try:
            __import__(mod)
            print(f"  [OK]   {mod}")
            n_ok += 1
        except Exception as e:
            print(f"  [FAIL] {mod}: {e}")
            traceback.print_exc()
            n_fail2 += 1
    print(f"\n  import 汇总: OK={n_ok} FAIL={n_fail2}")

    # Step 3: 集成测试 — 新数据结构 + scan
    print("\n[3/3] 集成测试 (DETECTION_STATE_PRESENTATION + scan)")
    print("-" * 70)
    n_ok, n_fail3 = 0, 0

    # 3a) DETECTION_STATE_PRESENTATION 表存在且完整
    try:
        from app.core import labels
        p = labels.DETECTION_STATE_PRESENTATION
        assert "stopped" in p and "running" in p and "paused" in p, "缺少关键状态"
        assert p["stopped"].visual_status == "no_data"
        assert p["running"].visual_status == "online"
        assert p["paused"].visual_status == "online"
        assert p["running"].text_label == labels.DETECTION_STATE_RUNNING
        print(f"  [OK]   DETECTION_STATE_PRESENTATION 3 个状态映射正确")
        n_ok += 1
    except Exception as e:
        print(f"  [FAIL] DETECTION_STATE_PRESENTATION: {e}")
        n_fail3 += 1

    # 3b) CellUIManager 走 PRESENTATION
    try:
        from app.services.cell_ui_manager import CellUIManager
        mgr = CellUIManager()
        assert mgr.status_for("running") == "online"
        assert mgr.text_for("running") == "运行中"
        assert mgr.status_for("stopped") == "no_data"
        assert mgr.text_for("paused") == "已暂停"
        print(f"  [OK]   CellUIManager.status_for / text_for 走 PRESENTATION")
        n_ok += 1
    except Exception as e:
        print(f"  [FAIL] CellUIManager: {e}")
        n_fail3 += 1

    # 3c) CellController 不再有 _pending_countdown
    try:
        from app.services.cell_controller import CellController
        ctrl = CellController(total=72)
        assert not hasattr(ctrl, "_pending_countdown"), "字段仍存在"
        assert not hasattr(ctrl, "take_pending_countdown"), "方法仍存在"
        # apply() 旧参数应不存在
        import inspect
        sig = inspect.signature(ctrl.apply)
        assert "countdown_seconds" not in sig.parameters, "参数仍存在"
        # 但 apply(action, cids) 还能用
        r = ctrl.apply("start", [1, 2, 3])
        assert r == [1, 2, 3]
        print(f"  [OK]   CellController 清理 _pending_countdown + countdown_seconds")
        n_ok += 1
    except Exception as e:
        print(f"  [FAIL] CellController: {e}")
        n_fail3 += 1

    # 3d) config_registry 9 个扫描类别 + 0 hits
    try:
        from app.core.config_registry import scan
        hits = scan(root="app")
        n_crit = sum(1 for h in hits if h.severity.value == "CRITICAL")
        n_warn = sum(1 for h in hits if h.severity.value == "WARNING")
        n_info = sum(1 for h in hits if h.severity.value == "INFO")
        assert n_crit == 0 and n_warn == 0 and n_info == 0, \
            f"hits 非零: {n_crit}/{n_warn}/{n_info}"
        print(f"  [OK]   config_registry 9 类别扫描 0 hits (CRIT=0 WARN=0 INFO=0)")
        n_ok += 1
    except Exception as e:
        print(f"  [FAIL] config_registry scan: {e}")
        n_fail3 += 1

    print(f"\n  集成测试汇总: OK={n_ok} FAIL={n_fail3}")

    total_fail = n_fail + n_fail2 + n_fail3
    print("\n" + "=" * 70)
    if total_fail == 0:
        print("ALL PASS — E 阶段代码可正常编译、导入、集成")
    else:
        print(f"FAIL {total_fail} items — 需修复后重试")
    print("=" * 70)
    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
