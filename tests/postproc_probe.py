# -*- coding: utf-8 -*-
"""主进程后处理 GIL 探针：分解 detect_batch_parallel 中 GPU 前向 vs NMS 后处理。

零解码实验已证明编排上限 ~208fps，多进程把读帧移出后 ~195fps，剩余瓶颈在
主进程 GPU 推理 + 后处理。本探针在纯主进程下测量：
  A) _decode_batch（GPU 前向，应释放 GIL）
  B) 单图 NMS（串行，纯 Python，吃 GIL）
  C) detect_batch_parallel 不同 max_workers（线程池是否有效）
判断 NMS 后处理是否 GIL bound、线程池是该加还是该减。
"""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ml" / "vision"))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from engine import DEPLOY_DIR, DetectionEngine  # noqa: E402

for s in (sys.stdout, sys.stderr):
    if hasattr(s, "reconfigure"):
        try: s.reconfigure(encoding="utf-8")
        except OSError: pass

ML = Path(__file__).resolve().parents[1]
VIDEOS = sorted((ML / "video").glob("*.mp4"))
N = 54


def _frames():
    out = []
    for j in range(N):
        v = str(VIDEOS[j % len(VIDEOS)])
        cap = cv2.VideoCapture(v)
        cap.set(cv2.CAP_PROP_POS_FRAMES, j % max(1, int(cap.get(cv2.CAP_PROP_FRAME_COUNT))))
        ok, f = cap.read()
        cap.release()
        if ok:
            out.append(f)
    return out


def main():
    eng = DetectionEngine(input_shape=(320, 320), backend="onnx",
                          onnx_path=str(DEPLOY_DIR / "yolo_ptq_int8_320_dyn.onnx"))
    fr = _frames()
    shapes = [f.shape[:2] for f in fr]
    print(f"帧数 {len(fr)}")

    # A) 纯 GPU 前向 _decode_batch
    for _ in range(3):
        eng._decode_batch(fr)
    t0 = time.perf_counter()
    reps = 30
    for _ in range(reps):
        pred = eng._decode_batch(fr)
    tA = (time.perf_counter() - t0) / reps * 1000
    print(f"A) _decode_batch(GPU前向)    : {tA:7.1f} ms  ({reps*N/tA*1000:6.0f} fps)")

    # B) 单图 NMS 串行（_nms_one）
    n = len(shapes)
    preds = [pred[i:i + 1] for i in range(n)] if n else []
    for _ in range(3):
        [eng._nms_one(p, s) for p, s in zip(preds, shapes)]
    t0 = time.perf_counter()
    for _ in range(reps):
        [eng._nms_one(p, s) for p, s in zip(preds, shapes)]
    tB = (time.perf_counter() - t0) / reps * 1000
    print(f"B) NMS 串行(_nms_one x{n})   : {tB:7.1f} ms  ({reps*N/tB*1000:6.0f} fps)")

    # C) detect_batch_parallel 线程池规模扫描
    for mw in (1, 4, 12):
        for _ in range(3):
            eng.detect_batch_parallel(fr, shapes, max_workers=mw)
        t0 = time.perf_counter()
        for _ in range(reps):
            eng.detect_batch_parallel(fr, shapes, max_workers=mw)
        tC = (time.perf_counter() - t0) / reps * 1000
        print(f"C) detect_batch_parallel(mw={mw:2d}): {tC:7.1f} ms  ({reps*N/tC*1000:6.0f} fps)")

    # D) 拆分 _onnx_blob(CPU预处理) vs ort.run(GPU) vs NMS
    for _ in range(3):
        eng._onnx_blob(fr)
    t0 = time.perf_counter()
    for _ in range(reps):
        eng._onnx_blob(fr)
    t_blob = (time.perf_counter() - t0) / reps * 1000
    blob = eng._onnx_blob(fr)
    for _ in range(3):
        eng.ort_session.run(eng.ort_out, {eng.ort_in: blob})
    t0 = time.perf_counter()
    for _ in range(reps):
        eng.ort_session.run(eng.ort_out, {eng.ort_in: blob})
    t_ort = (time.perf_counter() - t0) / reps * 1000
    print(f"D) _onnx_blob(CPU预处理)  : {t_blob:7.1f} ms")
    print(f"    ort_session.run(GPU)  : {t_ort:7.1f} ms  (一次batch{N})")
    pred2 = eng._onnx_decode(fr)
    p2 = [pred2[i:i + 1] for i in range(n)]
    for _ in range(3):
        [eng._nms_one(p, s) for p, s in zip(p2, shapes)]
    t0 = time.perf_counter()
    for _ in range(reps):
        [eng._nms_one(p, s) for p, s in zip(p2, shapes)]
    t_nms = (time.perf_counter() - t0) / reps * 1000
    print(f"    NMS 串行(_nms_one)     : {t_nms:7.1f} ms")


if __name__ == "__main__":
    main()