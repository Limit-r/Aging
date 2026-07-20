"""config_registry pre-commit 钩子示例（Phase 5 E-3）。

将本文件内容复制到 `.git/hooks/pre-commit` 并 `chmod +x` 即可启用。
或者用 `pre-commit` 框架：在项目根 `.pre-commit-config.yaml` 中配置。

钩子行为：
- 暂存区发现 CRITICAL 级硬编码 → 拒绝 commit
- 仅 WARNING/INFO → 警告但允许（开发阶段）
- 全部干净 → 静默通过

退出码：
- 0 - 通过
- 1 - 拒绝（CRITICAL 命中）
- 2 - 调用错误
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCAN_SCRIPT = ROOT / "tests" / "run_config_registry_scan.py"


def main() -> int:
    if not SCAN_SCRIPT.exists():
        print(f"[pre-commit] 找不到扫描脚本: {SCAN_SCRIPT}", file=sys.stderr)
        return 2

    # 优先用 --strict-critical：只阻挡 CRITICAL，WARNING/INFO 允许
    # 如果要更严格可换 --strict
    result = subprocess.run(
        ["python", str(SCAN_SCRIPT), "--strict-critical"],
        cwd=str(ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    # 把扫描器输出透传给用户
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)

    if result.returncode == 0:
        return 0
    elif result.returncode == 1:
        print(
            "\n[pre-commit] CRITICAL 硬编码命中，commit 已被拒绝。\n"
            "  修复建议：\n"
            "    - 颜色 → app.core.tokens.Colors\n"
            "    - 字体名 → app.core.tokens.Fonts.FAMILY_XXX\n"
            "    - 数字 → app.core.tokens.Sizing 或 app.core.config\n"
            "    - 中文 → app.core.labels\n"
            "    - QSS 字符串 → app.styles.templates\n"
            "  跳过本钩子：git commit --no-verify",
            file=sys.stderr,
        )
        return 1
    else:
        print(f"[pre-commit] 扫描器异常 (rc={result.returncode})", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
