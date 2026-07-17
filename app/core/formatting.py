"""格式化工具集中点。

包含:
- format_cid: 统一 "CH-NN" 格式（13 处硬编码已统一）
- divmod3600: 时间 divmod 内核（narrative / countdown_widget 共用）
- format_hms: H:MM:SS / MM:SS 双格式
"""

from typing import Tuple


def format_cid(cid: int) -> str:
    """通道 ID → "CH-NN" 字符串。

    全工程统一入口，修改格式只需改这一处。
    之前 f"CH-{cid:02d}" 散落 13 处，现已集中。

    Args:
        cid: 通道 ID（1-based，72 cell 系统）

    Returns:
        "CH-01" / "CH-23" / "CH-72" 等固定宽度字符串

    Examples:
        >>> format_cid(1)
        'CH-01'
        >>> format_cid(72)
        'CH-72'
    """
    return f"CH-{int(cid):02d}"


def divmod3600(seconds: int) -> Tuple[int, int, int]:
    """把秒数分解为 (时, 分, 秒)。

    抽出来作为公共内核，避免 divmod 散落各处。

    Args:
        seconds: 总秒数（负数会被取 0）

    Returns:
        (h, m, s) 三元组

    Examples:
        >>> divmod3600(3661)
        (1, 1, 1)
        >>> divmod3600(45)
        (0, 0, 45)
    """
    s = max(int(seconds), 0)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return h, m, sec


def format_hms(remain_s: int, total_s: int = 0) -> str:
    """格式化为 H:MM:SS 或 MM:SS。

    - total_s >= 3600 或 h > 0：用 H:MM:SS
    - 其他：用 MM:SS

    Args:
        remain_s: 剩余秒数（负数取 0）
        total_s: 总秒数（仅用于判断格式位数）

    Returns:
        "30:45" / "1:23:45" / "00:00"

    Examples:
        >>> format_hms(1845, 3600)
        '30:45'
        >>> format_hms(5025, 7200)
        '1:23:45'
    """
    h, m, s = divmod3600(remain_s)
    if total_s >= 3600 or h > 0:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"
