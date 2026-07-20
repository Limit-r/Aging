"""D 阶段收尾验证：py_compile + 5 个核心模块 import smoke test。"""
import py_compile
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FILES_TO_COMPILE = [
    "app/core/tokens.py",
    "app/core/config.py",
    "app/core/labels.py",
    "app/core/config_registry.py",
    "app/ui/nav_bar.py",
    "app/ui/floaters.py",
    "app/ui/home_page.py",
    "app/ui/pages/current_page.py",
    "app/ui/pages/detail_page.py",
    "app/ui/pages/video_page.py",
    "app/widgets/data_cell.py",
]

MODULES_TO_IMPORT = [
    "app.core.tokens",
    "app.core.config",
    "app.core.labels",
    "app.core.config_registry",
    "app.ui.nav_bar",
    "app.ui.floaters",
    "app.ui.pages.current_page",
    "app.ui.pages.detail_page",
    "app.ui.pages.video_page",
    "app.widgets.data_cell",
]


def main() -> int:
    print("=" * 70)
    print("D 阶段收尾验证：py_compile + import smoke test")
    print("=" * 70)

    # Step 1: py_compile
    print("\n[1/2] py_compile 检查")
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
    print("\n[2/2] import smoke test（Qt 之前能 import 的）")
    print("-" * 70)
    n_ok, n_fail = 0, 0
    for mod in MODULES_TO_IMPORT:
        try:
            __import__(mod)
            print(f"  [OK]   {mod}")
            n_ok += 1
        except Exception as e:
            print(f"  [FAIL] {mod}: {e}")
            traceback.print_exc()
            n_fail += 1
    print(f"\n  import 汇总: OK={n_ok} FAIL={n_fail}")

    print("\n" + "=" * 70)
    if n_fail == 0:
        print("ALL PASS — D 阶段代码可正常编译和导入")
    else:
        print(f"FAIL {n_fail} files — 需修复后重试")
    print("=" * 70)
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
