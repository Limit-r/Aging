# -*- coding: utf-8 -*-
"""诊断：批量 vs 逐帧检测框的偏移量与方向，区分良性抖动 vs 系统错位。"""
import sys, numpy as np
from pathlib import Path
ML = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ML / "ml" / "vision"))
import cv2
from engine import DetectionEngine

FRAMES = [r"d:\Aging\ml\datasets\A\JPEGImages\a01_000000.jpg"]


def main():
    eng = DetectionEngine(backend="onnx")
    frames = [cv2.imread(p) for p in FRAMES]
    sizes = [f.shape[:2] for f in frames]
    single = eng.detect(frames[0])
    batch = eng.detect_batch(frames, sizes)[0]
    # 最近邻匹配
    def center(d):
        return np.array([(d["x1"] + d["x2"]) / 2, (d["y1"] + d["y2"]) / 2])
    sc = np.array([center(d) for d in single])
    bc = np.array([center(d) for d in batch])
    shifts = []
    matched = 0
    for i, b in enumerate(bc):
        d = np.linalg.norm(sc - b, axis=1)
        j = int(np.argmin(d))
        shifts.append((single[j]["name"], d[j], single[j]["cid"] == batch[i]["cid"]))
        if d[j] < 8:
            matched += 1
    shifts.sort(key=lambda t: -t[1])
    print(f"单{len(single)} 批{len(batch)} 框, 匹配(<8px)={matched}"
          f"/{min(len(single), len(batch))}")
    print("最大偏移 (name, dist_px, cid_match):")
    for name, dd, cm in shifts:
        print(f"   {name}: {dd:.1f}px cid_match={cm}")
    # 系统偏移方向（取匹配最近邻的平均位移）
    if len(bc) and len(sc):
        vecs = []
        for b in bc:
            j = int(np.argmin(np.linalg.norm(sc - b, axis=1)))
            vecs.append(b - sc[j])
        mv = np.mean(vecs, axis=0)
        print(f"平均位移向量: ({mv[0]:.2f}, {mv[1]:.2f})px  "
              f"幅值{np.linalg.norm(mv):.2f}px" +
              (" <- 系统偏移!" if np.linalg.norm(mv) > 3 else " <- 良性抖动"))


if __name__ == "__main__":
    main()