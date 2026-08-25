# -*- coding: utf-8 -*-
"""320×320 动态 batch ONNX：正确性(同帧批量一致) + 54 路吞吐(目标216fps)。"""
import sys, time, os
import numpy as np
from pathlib import Path
ML = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ML / "ml" / "vision"))

import cv2  # noqa: E402
from engine import DetectionEngine  # noqa: E402

ONNX320 = Path(sys.argv[1]) if len(sys.argv) > 1 else \
    ML / "ml" / "deploy" / "yolo_ptq_int8_320_dyn.onnx"
FRAMES = [f"d:\\Aging\\ml\\datasets\\A\\JPEGImages\\a01_0000{k:02d}.jpg"
          for k in (0, 6, 12, 18, 24, 30, 36, 42)]


def main():
    eng = DetectionEngine(backend="onnx", onnx_path=str(ONNX320))
    # __init__ 里 decodebox 在 _load_onnx(320) 之后按 320 构建，无需手动重建。
    print("onnx:", ONNX320.name, "decodebox input_shape:", eng.input_shape,
          "providers:", eng.ort_session.get_providers())

    frames = [cv2.imread(p) for p in FRAMES]
    sizes = [f.shape[:2] for f in frames]

    # 正确性：同帧批量(都放第0帧) 8 元素一致
    f0 = frames[0]; s0 = sizes[0]
    batch = eng.detect_batch([f0] * 8, [s0] * 8)
    sets = [sorted((d["x1"], d["y1"], d["x2"], d["y2"], d["name"])
                   for d in b) for b in batch]
    same = all(set(map(tuple, c)) == set(map(tuple, sets[0])) for c in sets)
    print(f"[320] 同帧批量 8 元素一致: {'是' if same else '否'} ({len(batch[0])}框)")

    # 吞吐：batch 到 54
    print("[320] 吞吐 (54路目标216fps):")
    for B in (1, 8, 16, 32, 54):
        use = (frames * ((B + len(frames) - 1) // len(frames)))[:B]
        usz = [f.shape[:2] for f in use]
        reps = 30
        t0 = time.perf_counter()
        for _ in range(reps):
            if B == 1:
                for f in use:
                    eng.detect(f)
            else:
                eng.detect_batch(use, usz)
        dt = time.perf_counter() - t0
        n = reps * len(use)
        print(f"  batch={B}: {n/dt:.1f} fps ({dt/n*1000:.3f} ms/帧)")
    print("== 完成 ==")


if __name__ == "__main__":
    import traceback
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise