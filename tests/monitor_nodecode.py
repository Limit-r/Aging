# -*- coding: utf-8 -*-
"""实验：若解码完全免费（帧预载内存、零读帧线程），54路编排能达到多高 fps？

目的：判断 GIL/读帧线程是否是当前 154fps 的真实瓶颈。
- 若达到 ~210fps（≈引擎裸吞吐）→ 读帧线程/GIL 确是瓶颈 → 多进程/共享内存值得做
- 若仍 ~155fps → 瓶颈在引擎或编排本身上，多进程读帧无法改善
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

N_CH = 54
FPS = 4
PERIOD = 1.0 / FPS
# 预载足够多样化的帧池（每视频采样 ~20 帧，共 ~120 帧，供 54 路轮询）
POOL = []
for v in VIDEOS:
    cap = cv2.VideoCapture(str(v))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    step = max(1, n // 20)
    for k in range(0, n, step):
        cap.set(cv2.CAP_PROP_POS_FRAMES, k)
        ok, f = cap.read()
        if ok: POOL.append(f)
    cap.release()
print(f"帧池: {len(POOL)} 帧 / {sum(f.nbytes for f in POOL)/1e6:.0f}MB")

def main() -> int:
    eng = DetectionEngine(input_shape=(320, 320), backend="onnx",
                          onnx_path=str(DEPLOY_DIR / "yolo_ptq_int8_320_dyn.onnx"))
    t0 = time.time()
    jobs = [{"job": i + 1, "idx": 0, "next_t": 0.0, "done": False,
             "tracker": W.FlashTracker(debounce_frames=1),
             "frame_pool": [POOL[(i + k) % len(POOL)] for k in range(3)]}
            for i in range(N_CH)]

    frames_det = 0
    iters = 0
    stop_at = time.time() + 30
    last_agg = 0.0
    while time.time() < stop_at:
        now = time.time()
        iters += 1
        batch, shapes = [], []
        for j in jobs:
            if now < j["next_t"]:
                continue
            if len(batch) >= W.MONITOR_CHUNK:
                break
            # 零解码：直接从内存池取帧（模拟读帧线程已就绪）
            frame = j["frame_pool"][j["idx"] % len(j["frame_pool"])]
            j["idx"] += 1
            j["next_t"] = now + PERIOD
            batch.append((j, frame))
            shapes.append([frame.shape[0], frame.shape[1]])
        worked = bool(batch)
        if batch:
            dets_batch = eng.detect_batch_parallel(
                [f for _s, f in batch], shapes, max_workers=W.MONITOR_WORKERS)
            hl_list = eng.classify_batch(
                [(f, d) for (_s, f), d in zip(batch, dets_batch)])
            for (j, frame), dets, hl in zip(batch, dets_batch, hl_list):
                W._assign_led_ids(dets, hl)
                j["tracker"].update(W._assign_led_ids(dets, hl))
            frames_det += len(batch)
        time.sleep(0.001 if worked else 0.015)
    elapsed = time.time() - stop_at + 30
    print(f"零解码 54路编排: {frames_det/30:.1f} fps | 迭代{iters} | "
          f"目标216fps → {'达标' if frames_det/30>216 else '未达标'}")
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        import traceback; traceback.print_exc(); sys.exit(1)