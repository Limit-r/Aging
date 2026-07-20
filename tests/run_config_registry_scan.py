"""验证 config_registry.scan_and_report() 启动期入口。

Phase 5 E-3 升级：支持 pre-commit / CI 模式（--strict 选项，
发现任何命中时退出码 1），默认仅报告不退出。

运行：
    python tests/run_config_registry_scan.py                  # 仅报告
    python tests/run_config_registry_scan.py --strict         # 命中即退出 1
    python tests/run_config_registry_scan.py --strict-critical # 仅 CRITICAL 退出 1
    python tests/run_config_registry_scan.py --root tests     # 扫描其它目录

退出码：
    0 - 干净（或 --report-only 模式）
    1 - 命中硬编码（仅 --strict / --strict-critical 时）
    2 - 调用错误（路径不存在等）
"""
import argparse
import sys
from pathlib import Path

# 把项目根加入 path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config_registry import scan_and_report, Severity


def main() -> int:
    parser = argparse.ArgumentParser(
        description="config_registry 启动期扫描验证（Phase 5 E-3 升级）",
    )
    parser.add_argument(
        "--root", default="app",
        help="扫描根目录（默认 app/）",
    )
    parser.add_argument(
        "--strict", action="store_true",
        help="发现任何命中即退出 1（pre-commit / CI 模式）",
    )
    parser.add_argument(
        "--strict-critical", action="store_true",
        help="仅 CRITICAL 级别才退出 1（WARNING/INFO 仅报告）",
    )
    args = parser.parse_args()

    print("=" * 70)
    print(f"config_registry 启动期扫描验证 (root={args.root})")
    print("=" * 70)
    hits = scan_and_report(root=args.root)
    n = len(hits)
    by_sev: dict = {"CRITICAL": [], "WARNING": [], "INFO": []}
    for h in hits:
        by_sev[h.severity.value].append(h)
    n_crit = len(by_sev[Severity.CRITICAL.value])
    n_warn = len(by_sev[Severity.WARNING.value])
    n_info = len(by_sev[Severity.INFO.value])
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

    # 退出码判断
    if args.strict and n > 0:
        print(f"\n[STRICT] 检测到 {n} 条硬编码，退出 1")
        return 1
    if args.strict_critical and n_crit > 0:
        print(f"\n[STRICT-CRITICAL] 检测到 {n_crit} 条 CRITICAL 硬编码，退出 1")
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"fatal error: {e!r}", file=sys.stderr)
        sys.exit(2)
