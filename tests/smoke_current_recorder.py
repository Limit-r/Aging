"""电流记录器冒烟验证：状态边界 + 落盘 + 回读 round-trip。

运行（Aging 环境）：
  & E:\MiniConda\envs\Aging\python.exe -X utf8 d:\Aging\tests\smoke_current_recorder.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # 仓库根
from pathlib import Path

from PyQt5.QtWidgets import QApplication

from app.data.protocol import ChannelReading
from app.services.current_recorder import CurrentRecorder, read_device_log


def main() -> int:
    app = QApplication.instance() or QApplication([])
    # 临时归档根，避免污染真实 ml/detection_logs
    tmp = tempfile.mkdtemp(prefix="aging_rec_")
    os.environ["AGING_TEST_LOG_DIR"] = tmp
    import app.core.config as cfg
    cfg.DETECTION_LOG_DIR = tmp

    rec = CurrentRecorder(session_id=0x1234, parent=app)

    # 1) stopped→running 开档
    rec.start_session(1)   # CH-01
    rec.start_session(2)   # CH-02

    # 2) 写入若干采样（CH-01 有载 valid=1；CH-02 空载 valid=0）
    base = 1_700_000_000_000
    for i in range(5):
        rec.handle_reading(ChannelReading(1, base + i * 2000, (1.0, 2.0, 3.0, 4.0)))
    for i in range(3):
        rec.handle_reading(ChannelReading(2, base + i * 2000, (0.0, 0.0, 0.0, 0.0)))

    # 3) 暂停 CH-01：不应再写入
    rec.pause_session(1)
    rec.handle_reading(ChannelReading(1, base + 10_000, (9.9, 9.9, 9.9, 9.9)))
    rec.resume_session(1)
    rec.handle_reading(ChannelReading(1, base + 12_000, (8.0, 8.0, 8.0, 8.0)))

    # 4) 关闭归档
    rec.close()  # 归档 CH-01 / CH-02

    # 5) 回读 round-trip
    files = sorted(Path(tmp).rglob("*.bin"))
    if len(files) != 2:
        print(f"FAIL: 期望 2 个归档, 实际 {len(files)}")
        return 1
    by_cid = {}
    for f in files:
        header, rows = read_device_log(f)
        by_cid[header[1]] = (f, header, rows)

    h1, ch1_rows = by_cid[1][1:]
    h2, ch2_rows = by_cid[2][1:]
    ver1, cid1, sid1, start_ms1, magic1 = h1
    assert cid1 == 1 and sid1 == 0x1234 and magic1 == "VDRC", h1
    # CH-01：暂停段不写入 → 5(有载) + 1(resume) = 6 行，且无 9.9
    if len(ch1_rows) != 6:
        print(f"FAIL: CH-01 期望 6 行, 实际 {len(ch1_rows)} rows={ch1_rows}")
        return 1
    vals = [c[2] for (_ts, _v, c) in ch1_rows]
    if 9.9 in vals:
        print("FAIL: 暂停段被写入")
        return 1
    if 8.0 not in vals:
        print("FAIL: resume 段缺失")
        return 1
    if not all(v == 1 for (_ts, v, _c) in ch1_rows):
        print("FAIL: CH-01 应为全 valid=1")
        return 1
    # CH-02：空载 → valid=0，3 行
    if len(ch2_rows) != 3 or not all(v == 0 for (_ts, v, _c) in ch2_rows):
        print(f"FAIL: CH-02 期望 3 行全 valid=0, 实际 {ch2_rows}")
        return 1
    # 时间轴单调（2s 采样）
    ts = [r2[0] for r2 in ch1_rows]
    if any(b <= a for a, b in zip(ts, ts[1:])):
        print(f"FAIL: CH-01 时间轴应严格递增 {ts}")
        return 1

    print(f"OK: 电流记录 round-trip 通过 (2 文件, CH-01={len(ch1_rows)}行, CH-02={len(ch2_rows)}行)")
    print(f"    归档目录: {tmp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())