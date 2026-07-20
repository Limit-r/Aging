"""验证 config_registry.scan_and_report() 启动期入口。

运行：
    python tests/run_config_registry_scan.py
"""
import sys
from pathlib import Path

# 把项目根加入 path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config_registry import scan_and_report


def main() -> int:
    print("=" * 70)
    print("config_registry 启动期扫描验证")
    print("=" * 70)
    hits = scan_and_report(root="app")
    n = len(hits)
    n_crit = sum(1 for h in hits if h.severity.value == "CRITICAL")
    n_warn = sum(1 for h in hits if h.severity.value == "WARNING")
    n_info = sum(1 for h in hits if h.severity.value == "INFO")
    print("=" * 70)
    print(f"TOTAL = {n} (CRITICAL={n_crit} WARNING={n_warn} INFO={n_info})")
    print("=" * 70)
    # 打印前 20 条详情（控制台镜像 logs/app.log 输出）
    for h in hits[:20]:
        print(f"  {h.path}:{h.line}  [{h.severity.value} / {h.category}]")
        print(f"    {h.snippet}")
        print(f"    {h.suggestion}")
    if n > 20:
        print(f"  ... ({n - 20} more omitted)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
