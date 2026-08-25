# -*- coding: utf-8 -*-
"""GPU 端到端：动态 batch ONNX 引擎真图检测 + 吞吐对比。

1) 加载 DetectionEngine(backend="onnx") 并确认 CUDA EP 生效；
2) 逐帧 detect() 与 detect_batch() 检测结果对比（名字/置信度/数量）；
3) 批量与逐帧的吞吐(fps)对比。
"""
import sys, time
import numpy as np
from pathlib import Path
ML = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ML / "ml" / "vision"))

import cv2  # noqa: E402

from engine import DetectionEngine  # noqa: E402

FRAMES = [
    r"d:\Aging\ml\datasets\A\JPEGImages\a01_000000.jpg",
    r"d:\Aging\ml\datasets\A\JPEGImages\a01_000006.jpg",
    r"d:\Aging\ml\datasets\A\JPEGImages\a01_000012.jpg",
    r"d:\Aging\ml\datasets\A\JPEGImages\a01_000018.jpg",
    r"d:\Aging\ml\datasets\A\JPEGImages\a01_000024.jpg",
    r"d:\Aging\ml\datasets\A\JPEGImages\a01_000030.jpg",
    r"d:\Aging\ml\datasets\A\JPEGImages\a01_000036.jpg",
    r"d:\Aging\ml\datasets\A\JPEGImages\a01_000042.jpg",
]


def main():
    print("== 1) 加载引擎(onnx) ==")
    eng = DetectionEngine(backend="onnx")
    print("backend:", eng.backend, "device:", eng.device,
          "providers:", eng.ort_session.get_providers())
    print("onnx input_shape:", eng.input_shape)

    frames = [cv2.imread(p) for p in FRAMES]
    sizes = [f.shape[:2] for f in frames]

    print("\n== 2) 检测正确性：逐帧 vs 批量 ==")
    single = [eng.detect(f) for f in frames]
    batch = eng.detect_batch(frames, sizes)
    ok = True
    for i, (si, bi) in enumerate(zip(single, batch)):
        # 最近邻匹配（避免同名同坐标框被 set 折叠）：批量 vs 逐帧逐框最近距离
        bad = 0
        sc = np.array([((d["x1"] + d["x2"]) / 2, (d["y1"] + d["y2"]) / 2)
                       for d in si])
        for d in bi:
            c = np.array([(d["x1"] + d["x2"]) / 2, (d["y1"] + d["y2"]) / 2])
            if sc.size:
                dist = np.linalg.norm(sc - c, axis=1).min()
            else:
                dist = float("inf")
            if dist > 1.0:
                bad += 1
        st = "OK" if (bad == 0 and len(si) == len(bi)) else "DIFF"
        if st != "OK":
            ok = False
        print(f"  frame{i}: 单{len(si)} 批{len(bi)} {st} 不匹配框={bad}")
    print("  正确性(1px容差):", "通过" if ok else "存在差异")

    print("\n== 3) 吞吐对比 (54路目标 216fps) ==")
    # 54 路静默监控按 4fps：整批 54 帧一次前向最为紧凑，这里把 8 帧列表 pad 到目标 batch
    for B in (1, 8, 16, 32, 54):
        use = frames * ((B + len(frames) - 1) // len(frames))
        use = use[:B]
        usz = [f.shape[:2] for f in use]
        reps = 25
        t0 = time.perf_counter()
        for _ in range(reps):
            if B == 1:
                for f in use:
                    eng.detect(f)
            else:
                eng.detect_batch(use, usz)
        dt = time.perf_counter() - t0
        total_frames = reps * len(use)
        print(f"  batch={B}: {total_frames/dt:.1f} fps "
              f"({dt/total_frames*1000:.2f} ms/帧)")

    print("\n-- 并行 NMS 后处理 (detect_batch_parallel) --")
    use = frames * 7
    use = use[:54]
    usz = [f.shape[:2] for f in use]
    reps = 25
    for workers in (8, 16):
        t0 = time.perf_counter()
        for _ in range(reps):
            eng.detect_batch_parallel(use, usz, max_workers=workers)
        dt = time.perf_counter() - t0
        total_frames = reps * len(use)
        print(f"  54帧 workers={workers}: {total_frames/dt:.1f} fps "
              f"({dt/total_frames*1000:.2f} ms/帧)")

    print("\n== 完成 ==")


if __name__ == "__main__":
    import traceback
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise