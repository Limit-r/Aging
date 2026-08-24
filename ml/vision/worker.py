# -*- coding: utf-8 -*-
"""常驻视觉检测服务（独立进程）。

设计目的：**模型预加载、常驻复用**。进程启动时一次性加载 `ml/deploy/`
中的 YOLO + TinyConv 模型，之后通过 stdin 接收逐路检测 job，避免每次
开始检测都重新加载模型（GUI 不会因此卡顿，也不向 GUI 进程引入 torch）。

stdin 命令（每行一个 JSON）::
    {"cmd": "detect", "job": 1, "video": "a.mp4", "outdir": "tmp",
     "conf": 0.25, "nms": 0.45}
    {"cmd": "stop", "job": 1}
    {"cmd": "quit"}

stdout 事件（每行一个 JSON，均含 "job"）::
    {"type": "ready", "model": "yolo+tinyconv", "device": "cuda"}
    {"type": "job_start", "job", "w", "h", "fps", "total"}   # 开流
    {"type": "sample", "job", "frame", "time", "det", "counts", "hl", "flashes"}
    {"type": "done", "job", "frames", "elapsed"}
    {"type": "error", "job", "message"}

说明：
- **逐帧**检测不抽帧：目标（LED 闪烁）只在逐帧连续观测下才可捕获。
- 每个 job 独立线程运行；共享的预加载引擎用锁串行化推理，保证 torch 线程安全。
- Windows 下强制 UTF-8 输出，避免 GBK 编码中文/符号崩溃。
"""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8")
        except (ValueError, OSError):
            pass

# ml/ 入 path（engine 内部也会补，这里确保 worker 自身目录已含 ml/vision）
sys.path.insert(0, str(Path(__file__).resolve().parent))

import cv2  # noqa: E402

from engine import DetectionEngine  # noqa: E402

THUMB_WIDTH = 420
PALETTE = [
    (0, 191, 255), (16, 255, 161), (255, 174, 66),
    (167, 139, 250), (255, 59, 92), (0, 229, 255), (255, 255, 255),
]

_emit_lock = threading.Lock()
_infer_lock = threading.Lock()
_jobs: dict[int, dict] = {}          # job -> {"stop": Event, "thread": Thread}


def emit(payload: dict) -> None:
    with _emit_lock:
        sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
        sys.stdout.flush()


class FlashTracker:
    """按「基础类 + 槽位」分配 LED ID，统计 off→on 翻转次数与亮/灭时长。

    除闪烁次数外，还记录每个 LED 的：
    - ``first_on``：检测开始后第几秒首次亮灯（`None` 表示整个过程从未亮过）
    - ``on_sec`` / ``off_sec``：累计亮/灭时长（秒）
    """

    def __init__(self):
        self.ids: list[str] = []
        self.last: dict[str, str] = {}
        self.flashes: dict[str, int] = {}
        self.first_on: dict[str, float | None] = {}
        self.on_sec: dict[str, float] = {}
        self.off_sec: dict[str, float] = {}
        self._prev_t: float = 0.0

    def update(self, samples: dict[str, str], t: float) -> dict[str, int]:
        for led_id in samples:
            if led_id not in self.ids:
                self.ids.append(led_id)
                self.last[led_id] = None
                self.flashes[led_id] = 0
                self.first_on[led_id] = None
                self.on_sec[led_id] = 0.0
                self.off_sec[led_id] = 0.0
        dt = max(t - self._prev_t, 0.0)
        self._prev_t = t
        for led_id, st in samples.items():
            prev = self.last[led_id]
            if prev == "L" and st == "H":
                self.flashes[led_id] += 1
            if (prev is None or prev == "L") and st == "H" \
                    and self.first_on[led_id] is None:
                self.first_on[led_id] = round(t, 1)
            if st == "H":
                self.on_sec[led_id] += dt
            else:
                self.off_sec[led_id] += dt
            self.last[led_id] = st
        return dict(self.flashes)

    def timing(self) -> dict[str, dict]:
        """导出每个 LED 的亮灭时刻统计（供 GUI 折线图 / 时刻表展示）。"""
        out = {}
        for led in self.ids:
            out[led] = {
                "state": self.last.get(led),
                "on": self.first_on.get(led),        # 检测后首亮秒（无则 None）
                "on_s": round(self.on_sec.get(led, 0.0), 1),
                "off_s": round(self.off_sec.get(led, 0.0), 1),
                "flashes": self.flashes.get(led, 0),
            }
        return out


def _assign_led_ids(dets, hl) -> dict[str, str]:
    from collections import defaultdict
    groups: dict[str, list] = defaultdict(list)
    for i, d in enumerate(dets):
        name = d["name"]
        if name.endswith("_area") or name.lower().endswith("area"):
            continue
        hlv = hl.get(i)
        if hlv is None:
            continue
        cx = (d["x1"] + d["x2"]) / 2.0
        groups[name].append((cx, hlv[0]))
    samples: dict[str, str] = {}
    for base, items in groups.items():
        items.sort(key=lambda t: t[0])
        for slot, (_cx, st) in enumerate(items):
            samples[f"{base}_{slot}"] = st
    return samples


def _draw(frame, dets, hl):
    for i, d in enumerate(dets):
        color = PALETTE[d["cid"] % len(PALETTE)]
        x1, y1, x2, y2 = int(d["x1"]), int(d["y1"]), int(d["x2"]), int(d["y2"])
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 1)
        hlv = hl.get(i)
        label = d["name"] if hlv is None else f"{d['name']}_{hlv[0]}"
        label = f"{label} {d['score']:.2f}"
        (tw, thh), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.35, 1)
        ty = max(int(y1) - thh - 3, 0)
        cv2.rectangle(frame, (x1, ty), (x1 + tw + 3, ty + thh + 3), color, -1)
        cv2.putText(frame, label, (x1 + 1, ty + thh), cv2.FONT_HERSHEY_SIMPLEX,
                    0.35, (0, 0, 0), 1, cv2.LINE_AA)
    return frame


def run_job(engine: DetectionEngine, job: int, video: str, outdir: str,
            conf: float, nms: float) -> None:
    """单个检测 job 线程体。"""
    video = str(Path(video).resolve())
    stop = _jobs.get(job, {}).get("stop")
    if stop is None:
        return
    if not Path(video).exists():
        emit({"type": "error", "job": job, "message": f"视频不存在: {video}"})
        return

    cap = cv2.VideoCapture(video)
    if not cap.isOpened():
        emit({"type": "error", "job": job, "message": "无法打开视频: " + video})
        return
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    emit({"type": "job_start", "job": job, "w": W, "h": H, "fps": fps,
          "total": total})

    out_dir = Path(outdir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tracker = FlashTracker()
    scale = THUMB_WIDTH / W if W else 1.0
    frame_idx = 0
    t0 = time.time()
    try:
        while not stop.is_set():
            ret, frame = cap.read()
            if not ret:
                break
            frame_idx += 1
            with _infer_lock:
                dets = engine.detect(frame)
                hl = engine.classify(frame, dets)
            samples = _assign_led_ids(dets, hl)
            elapsed = time.time() - t0
            flashes = tracker.update(samples, elapsed)

            from collections import Counter
            counts = Counter(d["name"] for d in dets)
            hl_counts: dict[str, dict[str, int]] = {}
            for i, d in enumerate(dets):
                h = hl.get(i)
                if h is None:
                    continue
                hl_counts.setdefault(d["name"], {"H": 0, "L": 0})[h[0]] += 1

            emit({
                "type": "sample", "job": job, "frame": frame_idx,
                "time": round(frame_idx / fps, 2), "det": len(dets),
                "counts": dict(counts), "hl": hl_counts,
                "flashes": flashes, "elapsed": round(elapsed, 1),
                "sw": tracker.timing(),
            })
            _draw(frame, dets, hl)
            thumb_h = int(H * scale)
            if thumb_h > 0 and frame_idx % 2 == 0:
                thumb = cv2.resize(frame, (THUMB_WIDTH, thumb_h),
                                   interpolation=cv2.INTER_AREA)
                cv2.imwrite(str(out_dir / f"cell_{job}.jpg"), thumb,
                            [cv2.IMWRITE_JPEG_QUALITY, 80])
    finally:
        cap.release()
    emit({"type": "done", "job": job, "frames": frame_idx,
          "elapsed": round(time.time() - t0, 1)})


def handle_detect(engine: DetectionEngine, cmd: dict) -> None:
    job = int(cmd["job"])
    if job in _jobs:
        return  # 该 job 已在运行
    stop = threading.Event()
    thread = threading.Thread(
        target=run_job, args=(engine, job, cmd["video"], cmd["outdir"],
                              float(cmd.get("conf", 0.25)),
                              float(cmd.get("nms", 0.45))),
        daemon=True,
        name=f"vision-job-{job}")
    _jobs[job] = {"stop": stop, "thread": thread}
    thread.start()


def handle_stop(cmd: dict) -> None:
    job = int(cmd["job"])
    entry = _jobs.pop(job, None)
    if entry is not None:
        entry["stop"].set()


def main() -> int:
    # 预加载模型（阻塞在进入命令循环之前，模型加载完成后再处理 job 命令）
    emit({"type": "status", "message": "预加载检测模型…"})
    try:
        engine = DetectionEngine()
    except FileNotFoundError as e:
        emit({"type": "fatal", "message": str(e)})
        return 1
    emit({"type": "ready", "model": "yolo+tinyconv", "device": str(engine.device),
          "n_classes": engine.num_classes})

    try:
        for raw in sys.stdin:
            raw = raw.strip()
            if not raw:
                continue
            try:
                cmd = json.loads(raw)
            except (ValueError, json.JSONDecodeError):
                continue
            if not isinstance(cmd, dict):
                continue
            if "cmd" in cmd:
                kind = cmd["cmd"]
            elif "video" in cmd or "job" in cmd:
                kind = "detect"
            else:
                continue
            if kind == "detect":
                handle_detect(engine, cmd)
            elif kind == "stop":
                handle_stop(cmd)
            elif kind == "quit":
                break
    except KeyboardInterrupt:
        pass

    for entry in list(_jobs.values()):
        entry["stop"].set()
    time.sleep(0.1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())