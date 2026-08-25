# -*- coding: utf-8 -*-
"""54帧全量大burst成本分解：detect_batch_parallel vs classify_batch。

复制监控循环的满载瞬间（54路同时到期）：同一批54帧，分别计时
1) detect_batch_parallel(GPU YOLO + 并行NMS) 2) classify_batch(TinyConv)
找出 641ms 峰值主要花在哪，决定下一步优化方向。
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


def jaccard_main():
    eng = DetectionEngine(input_shape=(320, 320), backend="onnx",
                          onnx_path=str(DEPLOY_DIR / "yolo_ptq_int8_320_dyn.onnx"))
    # 取 54 帧（每真实视频 9 帧，覆盖多种画面）
    frames, shapes = [], []
    for j in range(54):
        v = str(VIDEOS[j % len(VIDEOS)])
        cap = cv2.VideoCapture(v)
        cap.set(cv2.CAP_PROP_POS_FRAMES, j * 3 % max(1, int(cap.get(cv2.CAP_PROP_FRAME_COUNT))))
        ok, f = cap.read()
        cap.release()
        if not ok:
            continue
        frames.append(f); shapes.append(f.shape[:2])
    print(f"burst 帧数: {len(frames)}")

    # warm
    eng.detect_batch_parallel(frames, shapes, max_workers=W.MONITOR_WORKERS)

    reps = 5
    t0 = time.perf_counter(); d0 = []
    for _ in range(reps):
        eng.detect_batch_parallel(frames, shapes, max_workers=W.MONITOR_WORKERS)
    t1 = time.perf_counter()
    det_ms = (t1 - t0) / reps * 1000

    # 用最后一次检测的 dets 跑 classify
    dets = eng.detect_batch_parallel(frames, shapes, max_workers=W.MONITOR_WORKERS)
    t2 = time.perf_counter()
    for _ in range(reps):
        eng.classify_batch([(f, d) for f, d in zip(frames, dets)])
    t3 = time.perf_counter()
    cls_ms = (t3 - t2) / reps * 1000
    n_roi = sum(len(d) for d in dets)

    print(f"detect_batch_parallel(54帧): {det_ms:.1f} ms | "
          f"classify_batch(54帧 ROIs={n_roi}): {cls_ms:.1f} ms")
    print(f"合计: {det_ms+cls_ms:.1f} ms (周期250ms) → "
          f"{'超时' if det_ms+cls_ms>250 else 'OK'}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(jaccard_main())
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)