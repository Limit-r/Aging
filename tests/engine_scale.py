# -*- coding: utf-8 -*-
"""测量 320 INT8 引擎随 batch 规模的耗时曲线，决定监控分批策略。

检测+分类（detect_batch_parallel + classify_batch）对小 batch 存在固定开销，
需要量化 cost(n) 随 n 是否线性，以验证"分块打包"是否真能在保吞吐的同时
压低单次迭代峰值到周期内。
"""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ml" / "vision"))

import cv2  # noqa: E402
from engine import DEPLOY_DIR, DetectionEngine  # noqa: E402
import worker as W  # noqa: E402

for s in (sys.stdout, sys.stderr):
    if hasattr(s, "reconfigure"):
        try: s.reconfigure(encoding="utf-8")
        except OSError: pass

ML = Path(__file__).resolve().parents[1]
VIDEOS = sorted((ML / "video").glob("*.mp4"))

def load_frames(n: int) -> list:
    frames = []
    for j in range(n):
        v = str(VIDEOS[j % len(VIDEOS)])
        cap = cv2.VideoCapture(v)
        cap.set(cv2.CAP_PROP_POS_FRAMES, j * 4 % max(1, int(cap.get(cv2.CAP_PROP_FRAME_COUNT))))
        ok, f = cap.read(); cap.release()
        if ok: frames.append(f)
    return frames

def main() -> int:
    eng = DetectionEngine(input_shape=(320, 320), backend="onnx",
                          onnx_path=str(DEPLOY_DIR / "yolo_ptq_int8_320_dyn.onnx"))
    reps = 3
    print(f"{'batch':>5} | {'detect+cls(ms)':>16} | {'fps':>8}")
    for n in (7, 14, 27, 54):
        frames = load_frames(n)
        shapes = [f.shape[:2] for f in frames]
        eng.detect_batch_parallel(frames, shapes, max_workers=W.MONITOR_WORKERS)  # warm
        dets = eng.detect_batch_parallel(frames, shapes, max_workers=W.MONITOR_WORKERS)
        best = 1e9
        for _ in range(reps):
            t0 = time.perf_counter()
            dd = eng.detect_batch_parallel(frames, shapes, max_workers=W.MONITOR_WORKERS)
            eng.classify_batch([(f, d) for f, d in zip(frames, dd)])
            best = min(best, (time.perf_counter() - t0) * 1000)
        print(f"{n:>5} | {best:>14.1f}ms | {n/(best/1000):>8.0f}")
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        import traceback; traceback.print_exc(); sys.exit(1)