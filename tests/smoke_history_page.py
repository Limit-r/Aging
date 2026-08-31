"""数据中心历史页冒烟验证：会话扫描 + I-t 曲线回看 + 空态分区。

运行（Aging 环境，需 offscreen 平台）：
  $env:QT_QPA_PLATFORM="offscreen"
  & E:\MiniConda\envs\Aging\python.exe -X utf8 d:\Aging\tests\smoke_history_page.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pathlib import Path

from PyQt5.QtWidgets import QApplication

import app.core.config as cfg
from app.data.protocol import ChannelReading
from app.services.current_recorder import CurrentRecorder


def main() -> int:
    app = QApplication.instance() or QApplication([])
    root = Path(tempfile.mkdtemp(prefix="aging_hist_"))
    cfg.DETECTION_LOG_DIR = str(root)   # 重定向落盘根到临时目录

    # 造 2 个设备各 1 次会话：CH-01 含一段空(valid=0)，CH-02 全部有载
    rec = CurrentRecorder(session_id=7, parent=app)
    rec.start_session(1)
    rec.start_session(2)
    base = 1_700_000_000_000
    # CH-01: 3 有效 → 2 空 → 2 有效
    for i in range(0, 7):
        valid = i in (0, 1, 2, 4, 5)
        cur = (1.0 + i, 2.0, 3.0, 4.0) if valid else (0.0, 0.0, 0.0, 0.0)
        rec.handle_reading(ChannelReading(1, base + i * 2000, cur))
    # CH-02: 4 有效
    for i in range(4):
        rec.handle_reading(ChannelReading(2, base + i * 2000, (5.0, 5.0, 5.0, 5.0)))
    rec.close()

    # 构造历史页
    from app.ui.pages.history_page import DetectionHistoryPage
    page = DetectionHistoryPage()

    if page._list.count() == 0:
        print("FAIL: 会话列表为空")
        return 1
    # 列表结构: CH-01(标题) + 1 会话 + CH-02(标题) + 1 会话 = 4 行
    if page._list.count() != 4:
        print(f"FAIL: 期望 4 行, 实际 {page._list.count()}")
        return 1

    # 选中 CH-01 会话，验证曲线分段 (valid 段 = 2 段: [0,1,2] 与 [4,5])
    ch01_item = None
    for i in range(page._list.count()):
        it = page._list.item(i)
        if it.data(0x0100):  # Qt.UserRole
            ch01_item = it
            break
    if ch01_item is None:
        print("FAIL: 找不到 CH-01 会话项")
        return 1
    page._list.setCurrentItem(ch01_item)
    page._on_current_changed(page._list.currentItem())
    rows_mock = [
        (base + i * 2000, 1 if i in (0, 1, 2, 4, 5) else 0, (1.0, 2.0, 3.0, 4.0))
        for i in range(7)
    ]
    segs = DetectionHistoryPage._split_valid(rows_mock)
    if segs != [[0, 1, 2], [4, 5]]:
        print(f"FAIL: 空态分段异常 {segs}")
        return 1

    # 曲线存在当前数据（最后一个有效段被 setData）
    curve = page._curves[0].getData()[0]
    if curve is None or len(curve) == 0:
        print("FAIL: I-t 曲线无数据")
        return 1

    print(f"OK: 历史页会话回看通过 (列表 {page._list.count()} 行, 分段 {segs}, 曲线点 {len(curve)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())