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

from engine import DetectionEngine, is_background_class  # noqa: E402

THUMB_WIDTH = 420
# 闪烁去抖：off→on 计为一次「完整亮暗」所需的最短连续 OFF 帧数。
# 用于合并单帧检测抖动/微闪，让计数匹配物理闪烁；数值偏大易把快速闪烁
# 合并掉，偏小则无法抑制抖动，需按视频帧率权衡（默认约 0.2s）。
FLASH_DEBOUNCE_FRAMES = 8
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
    """统计「完整亮暗事件」的闪烁次数（累计，off→on，带帧级去抖）。

    逐帧收到每个 LED 的 H/L 状态。为避免单帧检测抖动/微闪把一次物理闪烁
    数成多次，要求 LED 必须先连续 OFF 达到 `FLASH_DEBOUNCE_FRAMES` 帧，
    随后的 off→on 才累计一次闪烁。这样一次「完整亮暗」只计一次。
    """

    def __init__(self):
        self.ids: list[str] = []
        self.last: dict[str, str] = {}
        self.off_buf: dict[str, int] = {}
        self.flashes: dict[str, int] = {}

    def update(self, samples: dict[str, str]) -> dict[str, int]:
        for led_id in samples:
            if led_id not in self.ids:
                self.ids.append(led_id)
                self.last[led_id] = None
                self.off_buf[led_id] = 0
                self.flashes[led_id] = 0
        for led_id, st in samples.items():
            prev = self.last[led_id]
            if prev is None:
                self.last[led_id] = st
                continue
            if st == "H":
                # 由 off 变 on：需已连续 off 足够帧数才视为一次完整闪烁
                if prev == "L" and self.off_buf[led_id] >= FLASH_DEBOUNCE_FRAMES:
                    self.flashes[led_id] += 1
                # 处于 on（含短暂 off 抖动后的回落）都会重置 off 计数
                self.off_buf[led_id] = 0
            else:  # st == "L"
                self.off_buf[led_id] += 1
            self.last[led_id] = st
        return dict(self.flashes)


def _assign_led_ids(dets, hl) -> dict[str, str]:
    from collections import defaultdict
    groups: dict[str, list] = defaultdict(list)
    for i, d in enumerate(dets):
        name = d["name"]
        if is_background_class(name):
            continue
        hlv = hl.get(i)
        if hlv is None:
            continue
        cx = (d["x1"] + d["x2"]) / 2.0
        # 到达此处的 area 类均为功率灯(*_PWR_area)，剥掉 _area 后缀，
        # 统一以 pwr 信号灯类别进入统计，避免显示成 pwr_area
        base = name[:-len("_area")] if name.endswith("_area") else name
        groups[base].append((cx, hlv[0]))
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
    """单个检测 job 线程体。

    - **逐帧**检测不抽帧；按视频帧率匀速推进（真实速度检测），
      使一段 16s 的视频以约 16s 的时长处理，实时画面与统计随视频时间推进。
    - 兼容前节流：推理比实时慢时以实际推理速度运行（只快不慢）。
    - 结束/异常/停止时保证把 job 从 `_jobs` 移除，避免同 job 无法再次被调度。
    """
    video_path = str(Path(video).resolve())
    entry = _jobs.get(job)
    if entry is None:
        return
    stop = entry["stop"]
    cap = None
    try:
        if not Path(video_path).exists():
            emit({"type": "error", "job": job,
                  "message": f"视频不存在: {video_path}"})
            return
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            emit({"type": "error", "job": job,
                  "message": "无法打开视频: " + video_path})
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
        t_next = t0                       # 节流目标时间（对齐视频帧率）
        period = 1.0 / fps if fps > 0 else 1.0 / 30.0
        last_states: dict[str, str] = {}
        last_sec = -1
        while not stop.is_set():
            ret, frame = cap.read()
            if not ret:
                break
            frame_idx += 1
            with _infer_lock:
                dets = engine.detect(frame)
                hl = engine.classify(frame, dets)
            samples = _assign_led_ids(dets, hl)
            # 记录每个 LED 最近一次的 H/L 状态（项缺失则沿用旧值，抗单帧漏检）
            last_states.update(samples)
            flashes = tracker.update(samples)

            elapsed = time.time() - t0
            this_sec = int(frame_idx / fps)
            # 图表/统计按 1Hz 采样上报；实时画面仍逐帧写缩略图，互不阻塞
            if this_sec != last_sec:
                last_sec = this_sec
                emit({
                    "type": "sample", "job": job, "frame": frame_idx,
                    "elapsed": round(elapsed, 1),
                    "flashes": dict(flashes),
                    "states": dict(last_states),
                })

            _draw(frame, dets, hl)
            thumb_h = int(H * scale)
            if thumb_h > 0 and frame_idx % 2 == 0:
                thumb = cv2.resize(frame, (THUMB_WIDTH, thumb_h),
                                   interpolation=cv2.INTER_AREA)
                cv2.imwrite(str(out_dir / f"cell_{job}.jpg"), thumb,
                            [cv2.IMWRITE_JPEG_QUALITY, 80])

            # 真实速度：按视频帧率节流推进，16s 视频 ≈16s 处理完
            t_next += period
            delay = t_next - time.time()
            while delay > 0 and not stop.is_set():
                time.sleep(min(delay, 0.05))
                delay = t_next - time.time()
        emit({"type": "done", "job": job, "frames": frame_idx,
              "elapsed": round(time.time() - t0, 1)})
    finally:
        if cap is not None:
            cap.release()
        # 只移除「自己这条 entry」，避免误删 stop→detect 竞态中新建的同 job
        if _jobs.get(job) is entry:
            _jobs.pop(job, None)


def handle_detect(engine: DetectionEngine, cmd: dict) -> None:
    job = int(cmd["job"])
    entry = _jobs.get(job)
    if entry is not None and entry["thread"].is_alive():
        return  # 该 job 仍在运行
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