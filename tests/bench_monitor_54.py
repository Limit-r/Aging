# -*- coding: utf-8 -*-
"""54 路静默集中监控：批量性能验证脚本。

生成 54 路模拟设备视频（带高亮块，近似真实 NMS 负载），通过真正的 worker
（monitor 协议）批量跑一轮，统计：
  - 模型加载耗时、推到全部完成(壁钟)、总检测帧数
  - 实际总吞吐与每路帧率（相对 target fps 是否达标）
  - GPU 显存峰值、各路完成情况

用法：python tests\\bench_monitor_54.py [total_frames] [video_fps]

运行说明：
  - 生成/复用的模拟视频缓存在 %TEMP%\\vd54，脚本结束后自动清理。
  - worker 为独立进程，GUI 不需启动。
"""
import json
import os
import queue
import statistics
import subprocess
import sys
import threading
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMPDIR = os.path.join(os.environ.get("TEMP", r"C:\Users\gm38\AppData\Local\Temp"),
                      "vd54")
N_VIDEOS = 54
FRAMES = int(sys.argv[1]) if len(sys.argv) > 1 else 80
V_FPS = int(sys.argv[2]) if len(sys.argv) > 2 else 4
TARGET_FPS = 4.0

import cv2


def _blob(img, fr, i):
    """画几个移动高亮块，给 NMS 一些候选，更接近真实视频负载。"""
    h, w = img.shape[:2]
    for k in (0, 1, 2):
        x = int((fr * (11 + k * 7) + k * 53) % (w - 24))
        y = int((fr * (17 + k * 5) + k * 31) % (h - 24))
        v = int(180 + (fr * (3 + k)) % 60)
        img[y:y + 14, x:x + 14] = (v, v, v)
    return img


def make_videos():
    """生成（或复用已存在）54 路短视频，返回路径列表。"""
    os.makedirs(TMPDIR, exist_ok=True)
    paths, W, H = [], 320, 180
    for i in range(N_VIDEOS):
        p = os.path.join(TMPDIR, f"sv{i:02d}.mp4")
        if os.path.exists(p) and os.path.getsize(p) > 0:  # 复用，加速重复跑
            paths.append(p)
            continue
        w = cv2.VideoWriter(p, cv2.VideoWriter_fourcc(*"mp4v"), V_FPS, (W, H))
        base = 30 + i % 3 * 40
        for fr in range(FRAMES):
            img = np.full((H, W, 3), base + (140 if fr % 15 >= 7 else 0),
                          dtype=np.uint8)
            img = _blob(img, fr, i + 1)
            if fr % 5 == 0:  # 少量噪声模拟阴影/纹理
                patch = (img[::12, ::12].astype(np.int16)
                         + np.random.randint(0, 25, img[::12, ::12].shape))
                img[::12, ::12] = np.clip(patch, 0, 255).astype(np.uint8)
            w.write(img)
        w.release()
        paths.append(p)
    return paths


def sample_gpu_mem():
    """后台采样显存峰值（nvidia-smi 不可用则忽略）。"""
    peak = [0.0]
    def _loop():
        while True:
            try:
                out = subprocess.check_output(
                    ["nvidia-smi", "--query-gpu=memory.used",
                     "--format=csv,noheader,nounits"],
                    text=True, errors="ignore").strip()
                peak[0] = max(peak[0], float(out.splitlines()[0]))
            except Exception:
                pass
            time.sleep(0.3)
    threading.Thread(target=_loop, daemon=True).start()
    return peak


def main():
    t0 = time.time()
    paths = make_videos()
    t_gen = time.time() - t0
    jobs = [{"job": i + 1, "video": p} for i, p in enumerate(paths)]
    peak = sample_gpu_mem()

    proc = subprocess.Popen(
        [sys.executable, os.path.join(ROOT, "ml", "vision", "worker.py")],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, encoding="utf-8",
        errors="replace", cwd=ROOT)
    q = queue.Queue()

    def rd():
        for line in iter(proc.stdout.readline, ""):
            q.put(line)
    threading.Thread(target=rd, daemon=True).start()

    proc.stdin.write(json.dumps(
        {"cmd": "monitor", "jobs": jobs, "fps": TARGET_FPS}) + "\n")
    proc.stdin.flush()

    t_launch = time.time()
    start_seen = None
    finished = None
    last_snap = None
    while finished is None:
        try:
            line = q.get(timeout=0.1)
        except queue.Empty:
            proc.stdin.write(json.dumps({"cmd": "snapshot"}) + "\n")
            proc.stdin.flush()
            continue
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except Exception:
            continue
        t = ev.get("type")
        if t == "monitor_start":
            start_seen = time.time()
        elif t == "snapshot":
            last_snap = ev
            if ev.get("done") and finished is None:  # 全部 54 路处理完
                finished = time.time()
                proc.stdin.write(json.dumps({"cmd": "monitor_stop"}) + "\n")
                proc.stdin.flush()
        elif t == "monitor_finished" and finished is None:
            finished = time.time()

    wall = finished - t_launch
    loading = (start_seen - t_launch) if start_seen else None
    proc.stdin.write(json.dumps({"cmd": "quit"}) + "\n")
    proc.stdin.flush()
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()

    streams = (last_snap or {}).get("streams", [])
    total = int(sum(x.get("frame", 0) for x in streams))
    ok_count = sum(1 for x in streams if x.get("status") == "done")
    frames_full = sum(1 for x in streams if x.get("frame") >= FRAMES)
    total_fps = total / wall if wall else 0.0
    per = total_fps / N_VIDEOS
    frs = [x.get("frame", 0) for x in streams]

    print("=" * 58)
    print(f"视频生成耗时         : {t_gen:.1f}s")
    print(f"模型加载            : {loading:.2f}s" if loading is not None
          else "模型加载: N/A")
    print(f"54 路推到完成(壁钟) : {wall:.2f}s  ({FRAMES}帧@视频{V_FPS}fps => 内容{FRAMES/V_FPS:.0f}s)")
    print(f"总检测帧数          : {total}")
    print(f"实际总吞吐          : {total_fps:.1f} 帧/s")
    print(f"实际每路帧率        : {per:.2f} fps  (目标 {TARGET_FPS:.1f})")
    print(f"达标(>=3.8fps)      : {'是' if per >= 3.8 else '否'}")
    print(f"完成路数            : {ok_count}/{N_VIDEOS}  | 帧数打满 {frames_full}/{N_VIDEOS}")
    print(f"各路帧数 min/中/高   : {min(frs)}/{statistics.median(frs):.0f}/{max(frs)}")
    print(f"GPU 显存峰值        : {peak[0]:.0f} MB")
    print("=" * 58)
    print("PASS: 54路 @4fps 实时可达" if (per >= 3.8 and ok_count == N_VIDEOS)
          else "CHECK")
    for p in paths:
        try:
            os.remove(p)
        except Exception:
            pass


if __name__ == "__main__":
    main()