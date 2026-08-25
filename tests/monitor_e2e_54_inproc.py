# -*- coding: utf-8 -*-
"""54 路真实视频流端到端静默监控（进程内直测，复刻 worker._monitor_loop）。

规避子进程+管道 stdio 下 torch/asyncio 冲突；直接调用与 worker 相同的
DetectionEngine(320 onnx) + detect_batch_parallel + classify_batch +
FlashTracker/_assign_led_ids，输入为 6 个真实 .mp4（轮询分配到 54 路）。

输出：真实持续帧率、调度节拍是否 < 周期(250ms@4fps)、各路播放完成/误差/闪烁。
"""
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ml" / "vision"))

import cv2  # noqa: E402
from engine import DEPLOY_DIR, DetectionEngine  # noqa: E402
import worker as W  # noqa: E402  (FlashTracker / _assign_led_ids / 复用)

for s in (sys.stdout, sys.stderr):
    if hasattr(s, "reconfigure"):
        try: s.reconfigure(encoding="utf-8")
        except OSError: pass

ML = Path(__file__).resolve().parents[1]
VIDEOS = sorted((ML / "video").glob("*.mp4"))
if not VIDEOS:
    print("未找到视频"); sys.exit(1)
N_CH = 54
FPS = 4                       # 每路目标检测帧率
PERIOD = 1.0 / FPS            # 250ms
JOBS = [{"job": i + 1, "video": str(VIDEOS[i % len(VIDEOS)]),
         "w": 0, "h": 0, "total": 0, "frame": 0, "done": False,
         "error": None, "opened": False, "loops": 0,
         "flashes": {}, "tracker": None, "cap": None,
         "next_t": 0.0, "t0": 0.0}
        for i in range(N_CH)]


def main() -> int:
    print(f"== 引擎: onnx 320 (onnx_mon) ==")
    eng = DetectionEngine(input_shape=(320, 320), backend="onnx",
                          onnx_path=str(DEPLOY_DIR / "yolo_ptq_int8_320_dyn.onnx"))
    print(f"  backend={eng.backend} device={eng.device} "
          f"providers={eng.ort_session.get_providers()}")

    print(f"== 打开 {N_CH} 路真实视频 (fps={FPS}, loop=false) ==")
    t_start = time.time()
    opened = 0
    for j in JOBS:
        cap = cv2.VideoCapture(j["video"])
        if not cap.isOpened():
            j["error"] = "无法打开"; continue
        rate = cap.get(cv2.CAP_PROP_FPS) or 30.0
        j["cap"] = cap
        j["w"] = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        j["h"] = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        j["total"] = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        debounce = max(1, round(0.3 * min(rate, FPS)))
        j["tracker"] = W.FlashTracker(debounce_frames=debounce)
        j["opened"] = True
        # 相位错峰：把首帧检测时间均布到一个周期内，避免 54 路 simultaneity burst
        j["next_t"] = time.time() + opened * (PERIOD / N_CH)
        j["t0"] = time.time()
        opened += 1
    print(f"  opened={opened}/{N_CH}")

    # 统计
    iters = 0
    frames_det = 0
    max_iter_ms = 0.0
    period_ok = True
    loop_start = time.time()
    deadline = loop_start + 120
    while time.time() < deadline:
        now = time.time()
        iters += 1
        batch, shapes = [], []
        for j in JOBS:
            if j["done"] or j["error"] or not j["opened"]:
                continue
            if now < j["next_t"]:
                continue
            ret, frame = j["cap"].read()
            if not ret:
                j["done"] = True
                j["elapsed"] = time.time() - j["t0"]
                continue
            j["frame"] += 1
            j["next_t"] = now + PERIOD
            batch.append((j, frame))
            shapes.append([frame.shape[0], frame.shape[1]])

        it0 = time.perf_counter()
        if batch:
            dets_batch = eng.detect_batch_parallel(
                [f for _s, f in batch], shapes, max_workers=W.MONITOR_WORKERS)
            hl_list = eng.classify_batch(
                [(f, d) for (_s, f), d in zip(batch, dets_batch)])
            for (j, frame), dets, hl in zip(batch, dets_batch, hl_list):
                samples = W._assign_led_ids(dets, hl)
                j["tracker"].update(samples)
            frames_det += len(batch)
        it_ms = (time.perf_counter() - it0) * 1000
        if it_ms > max_iter_ms:
            max_iter_ms = it_ms
        if batch and it_ms > PERIOD * 1000:
            period_ok = False

        all_done = all(j["done"] or j["error"] or not j["opened"]
                       for j in JOBS) or iters > 20000
        if all_done:
            break
        time.sleep(0.002)

    elapsed = time.time() - loop_start

    print("\n================ 54路端到端汇总 ================")
    print(f"运转时长: {elapsed:.1f}s | 调度迭代: {iters} | 累计检测帧: {frames_det}")
    print(f"真实持续吞吐: {frames_det/elapsed:.1f} fps(跨越全部路) = "
          f"{N_CH}fps单路折算 {frames_det/elapsed/N_CH*FPS:.2f}/目标FPS")
    print(f"单次迭代峰值耗时: {max_iter_ms:.1f} ms "
          f"(周期={PERIOD*1000:.0f}ms) → "
          f"节拍O{'K' if period_ok else 'VER'}({ '超时' if not period_ok else '未超时'})")

    done = sum(1 for j in JOBS if j["done"])
    err = [j for j in JOBS if j["error"]]
    n_flash = sum(1 for j in JOBS if j["opened"] and j.get("flashes"))
    total_flash = sum(sum(j.get("flashes", {}).values()) for j in JOBS)
    n_loop = sum(1 for j in JOBS if j.get("loops", 0) > 0)
    print(f"播放完成(EOF): {done}/{N_CH} | 打开失败: {len(err)} | "
          f"检测到闪烁的路: {n_flash} | 累计闪烁次数: {total_flash}")
    for j in JOBS:
        if j["error"]:
            print(f"  CH{j['job']:02d} error: {j['error']}")
    print("示例路详情 (前6):")
    for j in JOBS[:6]:
        fl = dict(j.get("flashes", {}))
        print(f"  CH{j['job']:02d} {j['video'].split(chr(92))[-1]} "
              f"frame={j['frame']}/{j['total']} status="
              f"{'done' if j['done'] else ('error' if j['error'] else 'EOF未达')} "
              f"flashes={fl}")
    print("================ 完成 ================")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)