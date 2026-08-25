# -*- coding: utf-8 -*-
"""动态 batch reshape 正确性诊断：batch 内全放同一帧，若动态注入正确则
8 个元素结果彼此一致、且与 batch=1 单帧结果一致。

结论解读：
- 若 8 元素全等且 = 单帧 -> reshape 注入正确，DIFF 是 INT8 跨 batch 抖动。
- 若 8 元素不一致 -> 动态 reshape 误改了非 batch 维，需修 dynamicize。
"""
import sys
import numpy as np
from pathlib import Path
ML = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ML / "ml" / "vision"))

import cv2  # noqa: E402
from engine import DetectionEngine  # noqa: E402

FRAME = r"d:\Aging\ml\datasets\A\JPEGImages\a01_000000.jpg"


def centers(dets):
    return np.array([((d["x1"] + d["x2"]) / 2, (d["y1"] + d["y2"]) / 2)
                     for d in dets]) if dets else np.zeros((0, 2))


def match(a, b, tol=1.0):
    if len(a) != len(b):
        return False, len(a), len(b), None
    ca, cb = centers(a), centers(b)
    dists = np.linalg.norm(ca[:, None, :] - cb[None, :, :], axis=2).min(axis=1)
    return (dists.max() <= tol), len(a), len(b), float(dists.max())


def main():
    print("== 同帧批量诊断 (backend=onnx) ==")
    eng = DetectionEngine(backend="onnx")
    frame = cv2.imread(FRAME)
    size = frame.shape[:2]

    single = eng.detect(frame)
    print(f"单帧 batch=1: {len(single)} 框")

    # 批量：8 个相同元素
    batch = eng.detect_batch([frame] * 8, [size] * 8)
    for i, b in enumerate(batch):
        ok, na, nb, d = match(single, b)
        print(f"  elem{i}: {len(b)}框 {'OK' if ok else 'DIFF'} vs单帧"
              f" (max中心距={d if d is not None else '--'})")

    # 彼此一致（去掉结果可能相同的起点，看最大分化）
    centers_list = [sorted((d["x1"], d["y1"], d["x2"], d["y2"]) for d in b)
                    for b in batch]
    all_same = all(set(map(tuple, c)) == set(map(tuple, centers_list[0]))
                   for c in centers_list)
    print("\n8 元素彼此一致:", "是" if all_same else "否")
    print("== 完成 ==")


if __name__ == "__main__":
    import traceback
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise