# -*- coding: utf-8 -*-
"""循环(loop=true)读帧重启路径冒烟：验证 EOF→重绕→重启读线程不挂死/不崩溃。

直接驱动 worker._reader_loop/_pop_frame（不做检测）：从视频后半程起读以尽快触发
EOF，命中重启分支后重绕首帧续读，确认能读到第 2 遍、两路并发无死锁且可正常退出。
"""
import sys, threading, time
from collections import deque
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ml" / "vision"))
import cv2  # noqa: E402
import worker as W  # noqa: E402
for s in (sys.stdout, sys.stderr):
    if hasattr(s, "reconfigure"):
        try: s.reconfigure(encoding="utf-8")
        except OSError: pass

ML = Path(__file__).resolve().parents[1]
VIDEOS = sorted((ML / "video").glob("*.mp4"))

def run(job):
    v = str(VIDEOS[job % len(VIDEOS)])
    cap = cv2.VideoCapture(v)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, total - 10))   # 从末 10 帧起步，尽快 EOF
    j = {"job": job + 1, "cap": cap, "stop": threading.Event(),
         "readq": deque(), "cv": threading.Condition(), "loops": 0,
         "last_loops": 0, "passes": 0, "passed2nd": False}
    j["reader"] = threading.Thread(target=W._reader_loop, args=(j,), daemon=True)
    j["reader"].start()
    deadline = time.time() + 6
    while time.time() < deadline and not j["passed2nd"]:
        item = W._pop_frame(j)
        if item is None:
            time.sleep(0.002); continue
        if item[0] == "eof":
            j["loops"] += 1
            if j["loops"] >= 2:
                j["passed2nd"] = True          # 成功赴 2 遍
                break
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)        # 重绕首帧
            j["readq"] = deque()                       # 重启读线程
            j["cv"] = threading.Condition()
            j["reader"] = threading.Thread(target=W._reader_loop, args=(j,), daemon=True)
            j["reader"].start()
        else:
            pass
    return j

def main() -> int:
    jobs = [run(i) for i in range(2)]
    ok = all(j["passed2nd"] for j in jobs)
    for j in jobs:
        print(f"  channel{j['job']}: loops={j['loops']} 第2遍={'OK' if j['passed2nd'] else '超时'}")
    print("结果:", "通过 ✓" if ok else "失败/超时 ✗")
    # 清理：停读线程
    for j in jobs:
        j["stop"].set()
        with j["cv"]:
            j["cv"].notify_all()
    time.sleep(0.3)
    return 0 if ok else 1

if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        import traceback; traceback.print_exc(); sys.exit(1)