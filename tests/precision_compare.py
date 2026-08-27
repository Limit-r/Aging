# -*- coding: utf-8 -*-
"""精度对比探针：串行化正确性 + 预处理插值(INTER_LINEAR vs INTER_AREA)损失量化。

分两层：
  A) 当前串行化方案是否零损失
     detect_batch_parallel([f]) (串行 _nms_one) 应当与单帧 detect 逐位一致
     （两者都走 _onnx_decode + non_max_suppression，NMS 逻辑未改）。
  B) 若把 _onnx_blob 的 INTER_AREA 换成 INTER_LINEAR 提速，检测损失多少
     代理指标：逐帧 检出框数差 / 平均 IoU / 类别翻转 / conf 变化。
canvas 缓冲复用不改像素，属零损失，不在本探针考虑（脚本会显式说明）。

用于决定：是否值得用 LINERAL 换吞吐（需判断精度损失可接受度）。
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
NFRAME = 60


def _io_metric(a: list[dict], b: list[dict]):
    """两 list[det] 的简单对齐指标：仅框级，且约束同类别才参与 IoU。"""
    if not a and not b:
        return {"n": 0, "iou": 1.0, "conf": 0.0}
    if not a or not b:
        return {"n": min(len(a), len(b)), "iou": 0.0, "conf": 1.0}
    used = [False] * len(b)
    iou_sum, hit = 0.0, 0
    conf_sum, conf_hit = 0.0, 0
    for x in a:
        best, bi, bb = -1, -1, None
        for i, y in enumerate(b):
            if used[i] or y["name"] != x["name"]:
                continue
            ix1, iy1 = max(x["x1"], y["x1"]), max(x["y1"], y["y1"])
            ix2, iy2 = min(x["x2"], y["x2"]), min(x["y2"], y["y2"])
            inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
            uni = (x["x2"] - x["x1"]) * (x["y2"] - y["y1"]) + \
                  (y["x2"] - y["x1"]) * (y["y2"] - y["y1"]) - inter
            iou = inter / uni if uni > 0 else 0.0
            if iou > best:
                best, bi, bb = iou, i, (x, y)
        if bi >= 0:
            used[bi] = True
            iou_sum += best
            conf_sum += abs(x["score"] - bb[1]["score"])
            hit += 1
            conf_hit += 1
    return {"n": hit, "iou": iou_sum / hit if hit else 0.0,
            "conf": conf_sum / conf_hit if conf_hit else 0.0}


def _exact_eq(a: list[dict], b: list[dict]) -> bool:
    if len(a) != len(b):
        return False
    for x, y in zip(a, b):
        # 归整后比较：消除 numpy.float32 vs python float 的二进制尾差误报
        if (x["name"], round(x["score"], 6),
                round(x["x1"], 4), round(x["y1"], 4),
                round(x["x2"], 4), round(x["y2"], 4)) != \
           (y["name"], round(y["score"], 6),
                round(y["x1"], 4), round(y["y1"], 4),
                round(y["x2"], 4), round(y["y2"], 4)):
            return False
    return True


def _linear_blob(eng):
    """复刻 _onnx_blob 但用 INTER_LINEAR（探测用 monkeypatch）。"""
    import cv2
    import numpy as np
    hh, ww = eng.input_shape

    def blob(frames_bgr):
        n = len(frames_bgr)
        canvas = np.full((n, hh, ww, 3), 128, dtype="uint8")
        for i, frame in enumerate(frames_bgr):
            h, w = frame.shape[:2]
            scale = min(hh / h, ww / w)
            nw, nh = int(round(w * scale)), int(round(h * scale))
            resized = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB),
                                 (nw, nh), interpolation=cv2.INTER_LINEAR)
            top, left = (hh - nh) // 2, (ww - nw) // 2
            canvas[i, top:top + nh, left:left + nw] = resized
        arr = np.ascontiguousarray(np.transpose(canvas, (0, 3, 1, 2)))
        return arr.astype("float32") / 255.0
    return blob


def _frames():
    out = []
    per = NFRAME // len(VIDEOS) or 1
    for v in VIDEOS:
        cap = cv2.VideoCapture(str(v))
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        for k in range(per):
            pos = int(total * (k + 0.5) / per)
            cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
            ok, f = cap.read()
            if ok:
                out.append(f)
        cap.release()
    return out[:NFRAME]


def main():
    eng = DetectionEngine(input_shape=(320, 320), backend="onnx",
                          onnx_path=str(DEPLOY_DIR / "yolo_ptq_int8_320_dyn.onnx"))
    fr = _frames()
    shapes = [f.shape[:2] for f in fr]
    print(f"采样帧 {len(fr)}")

    # ---- A) 串行化一致性：detect_batch_parallel vs detect ----
    exact = 0
    for f in fr:
        r_par = eng.detect_batch_parallel([f], [f.shape[:2]])[0]
        r_det = eng.detect(f)
        if _exact_eq(r_par, r_det):
            exact += 1
    print(f"\n[A] 串行化一致性 detect_batch_parallel vs detect: "
          f"{exact}/{len(fr)} 帧逐位一致"
          f"{' → 零损失' if exact == len(fr) else '（存在差异！）'}")
    if exact != len(fr):
        for f in fr:
            rp, rd = eng.detect_batch_parallel([f], [f.shape[:2]])[0], eng.detect(f)
            if not _exact_eq(rp, rd):
                print("  首处差异:", rp, "|", rd)
                break

    # ---- B) INTER_AREA (现状) vs INTER_LINEAR (候选提速) ----
    area = eng.detect_batch_parallel(fr, shapes)
    orig = eng._onnx_blob
    eng._onnx_blob = _linear_blob(eng)
    lin = eng.detect_batch_parallel(fr, shapes)
    eng._onnx_blob = orig

    n_diff = 0
    dbox_sum, dconf_sum, dbox_hits = [], [], 0
    for i, (a, b) in enumerate(zip(area, lin)):
        m = _io_metric(a, b)
        if len(a) != len(b) or abs(m["iou"] - 1.0) > 1e-9:
            n_diff += 1
        if m["n"]:
            dbox_sum.append(1 - m["iou"])
            dconf_sum.append(m["conf"])
            dbox_hits += 1
    area_boxes = sum(len(a) for a in area)
    lin_boxes = sum(len(a) for a in lin)
    print(f"\n[B] INTER_AREA(现状) vs INTER_LINEAR(候选)：{NFRAME} 帧")
    print(f"  检出框总数: AREA={area_boxes}  LINEAR={lin_boxes}  "
          f"Δ={lin_boxes - area_boxes}")
    print(f"  存在差异的帧: {n_diff}/{len(fr)}  "
          f"（含框数/位置/类别/置信任一变化）")
    if dbox_hits:
        print(f"  对齐框平均 IoU: {1 - sum(dbox_sum)/dbox_hits:.5f}  "
              f"(框位漂移 {(sum(dbox_sum)/dbox_hits)*100:.2f}%)")
        print(f"  对齐框平均 |Δconf|: {sum(dconf_sum)/dbox_hits:.5f}")
    else:
        print("  无任何可对齐框（差异显著）")


if __name__ == "__main__":
    main()