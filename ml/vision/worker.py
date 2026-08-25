# -*- coding: utf-8 -*-
"""常驻视觉检测服务（独立进程）—— 帧批处理调度版。

设计目的：**模型预加载、常驻复用、多视频流一次检测**。
- 进程启动时一次性加载 `ml/deploy/` 的 YOLO + TinyConv 模型。
- 通过 stdin 接收多路检测 job，**单一调度线程按帧批处理**：每轮把各流的
  "到点帧" 打包成 batch 一次前向 YOLO，再逐流解码/H-L 分类/闪烁统计。
  相比"每 job 一个线程+全局锁串行推理"，batch 摊销固定开销，并发吞吐更高。
- 显存受限（如 RTX 5060 Ti 8G）用 `MAX_CONCURRENT_STREAMS` 限制并发路数。

stdin 命令（每行一个 JSON）::
    {"cmd": "detect", "job": 1, "video": "a.mp4", "outdir": "tmp"}
    {"cmd": "stop",   "job": 1}
    {"cmd": "quit"}

stdout 事件（每行一个 JSON，均含 "job"）::
    {"type": "ready",     "model": "yolo+tinyconv", "device": "cuda"}
    {"type": "job_start", "job", "w", "h", "fps", "total"}   # 开流
    {"type": "sample",    "job", "frame", "time", "flashes", "states"}
    {"type": "done",      "job", "frames", "elapsed"}
    {"type": "error",     "job", "message"}                    # 含并发上限拒绝

说明：
- **逐帧**检测不抽帧：LED 闪烁只在逐帧连续观测下才可捕获。
- 每流按**自身帧率**独立节流（`next_t`），互不拖慢；推理慢于实时时以实际速度运行。
- Windows 下强制 UTF-8 输出，避免 GBK 编码中文/符号崩溃。
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import traceback
from collections import deque
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

from engine import DEPLOY_DIR, DetectionEngine, is_background_class  # noqa: E402


def _vision_backend() -> str:
    """推理后端：优先环境变量 VISION_BACKEND；否则 auto（onnx 在即用 onnx）。"""
    return os.environ.get("VISION_BACKEND", "auto")


THUMB_WIDTH = 420
# 缩略图目标帧率：GUI 以 VIDEO_REFRESH_MS 刷新即可，无需逐帧写盘；默认 ~4fps
THUMB_FPS = 4
# 每流预读缓冲区容量（帧数）。读帧放在独立线程后台预取，调度线程不因
# cap.read() 阻塞（对本地文件足够；为将来 RTSP/网络流准备）。调大可更早预取、
# 把视频解码延迟并行隐藏到 GPU 推理之后，代价是内存占用略升。
READ_BUF_SIZE = 3
# 闪烁去抖：off→on 计为一次「完整亮暗」所需的最短连续 OFF 帧数。
# 用于合并单帧检测抖动/微闪，让计数匹配物理闪烁；数值偏大易把快速闪烁
# 合并掉，偏小则无法抑制抖动，需按视频帧率权衡（默认约 0.2s）。
FLASH_DEBOUNCE_FRAMES = 8
# 多视频流并发检测上限（决定单次 YOLO batch 的最大规模）。
# 8GB 显存建议 2，谨慎可 3；超过后新的 detect 会被拒绝并返回 error 事件。
MAX_CONCURRENT_STREAMS = 2
# ---- 54 路静默集中监控（monitor） ----
MONITOR_MAX_STREAMS = 54           # 一次最多同时监控的设备视频路数
MONITOR_WORKERS = 12               # 后处理并行线程数（≈ CPU 逻辑核）
MONITOR_DEFAULT_FPS = 4.0          # 每路默认目标检测帧率（静默监控 2~5fps）
MONITOR_INPUT_SHAPE = (320, 320)   # 静默监控用更低输入换取吞吐
# 单次迭代 batch 上限（帧数）：54 路全同步到期时若一次塞满 54 帧大 batch，
# 检测+分类约 258ms 会略超 250ms 周期。封顶为 27 帧子批次（约 130ms<周期），
# 到点但未入本批的路推迟到下一迭代，既不丢吞吐（仍满批次产能）又平滑节拍。
MONITOR_CHUNK = 27
PALETTE = [
    (0, 191, 255), (16, 255, 161), (255, 174, 66),
    (167, 139, 250), (255, 59, 92), (0, 229, 255), (255, 255, 255),
]

_emit_lock = threading.Lock()
_streams_lock = threading.Lock()
_infer_lock = threading.Lock()     # 串行化 engine 前向（interactive + monitor 并存时）
_streams: dict[int, dict] = {}     # job -> stream 状态
_sched_stop = threading.Event()    # 退出信号
# ---- 静默集中监控（monitor）全局状态 ----
_mon_lock = threading.Lock()
_mon: dict | None = None           # 见 _monitor_init/run


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

    def __init__(self, debounce_frames: int = FLASH_DEBOUNCE_FRAMES):
        self.debounce = debounce_frames
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
                if prev == "L" and self.off_buf[led_id] >= self.debounce:
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


def _reader_loop(s: dict) -> None:
    """后台读帧线程：把 cap.read() 出的帧放入有界 prebuf，EOF 放 None 哨兵。"""
    cap = s["cap"]
    cv = s["cv"]
    q = s["readq"]
    while not s["stop"].is_set():
        ret, frame = cap.read()
        with cv:
            if not ret:
                q.append(None)          # EOF 哨兵（排在既有帧之后）
                cv.notify_all()
                return
            # 缓冲满则等待调度线程消费（有界，避免不读了也不占内存）
            while len(q) >= READ_BUF_SIZE and not s["stop"].is_set():
                cv.wait()
            if s["stop"].is_set():
                return
            q.append(frame)
            cv.notify_all()


def _pop_frame(s: dict):
    """从预读缓冲取一帧（非阻塞）。返回:
    - None         缓冲空
    - ("frame", f)  取到一帧
    - ("eof",)      取到 EOF 哨兵
    """
    cv = s["cv"]
    q = s["readq"]
    with cv:
        if not q:
            return None
        item = q.popleft()
        cv.notify_all()
        if item is None:
            return ("eof",)
        return ("frame", item)


# ------------------------------------------------------------------ 流状态
def _new_stream(job: int, cmd: dict) -> dict:
    return {
        "job": job, "video": cmd["video"], "outdir": cmd.get("outdir", ""),
        # 独立读帧线程 + 有界预读缓冲（cap.read 与调度解耦）
        "readq": None, "cv": None, "reader": None,
        "opened": False, "done": False, "stop": threading.Event(),
        "cap": None, "fps": 0.0, "w": 0, "h": 0, "total": 0,
        "tracker": FlashTracker(), "last_states": {},
        "frame_idx": 0, "t0": 0.0, "next_t": 0.0, "period": 0.0,
        "thumb_step": 1, "thumb_scale": 1.0, "last_sec": -1, "last_thumb": 0,
    }


def _open_stream(s: dict) -> None:
    video = str(Path(s["video"]).resolve())
    if not Path(video).exists():
        emit({"type": "error", "job": s["job"],
              "message": f"视频不存在: {video}"})
        s["done"] = True
        return
    cap = cv2.VideoCapture(video)
    if not cap.isOpened():
        emit({"type": "error", "job": s["job"],
              "message": "无法打开视频: " + video})
        s["done"] = True
        return
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    s["cap"] = cap
    s["fps"] = fps
    s["w"] = W
    s["h"] = H
    s["total"] = total
    s["period"] = 1.0 / fps if fps > 0 else 1.0 / 30.0
    s["t0"] = time.time()
    s["next_t"] = time.time()
    s["thumb_step"] = max(1, int(round(fps / THUMB_FPS)))
    s["thumb_scale"] = THUMB_WIDTH / W if W else 1.0
    # 启动独立读帧线程（cap 冲刷到有界 prebuf，与调度解耦）
    s["readq"] = deque()
    s["cv"] = threading.Condition()
    s["reader"] = threading.Thread(
        target=_reader_loop, args=(s,), daemon=True)
    s["reader"].start()
    s["opened"] = True
    emit({"type": "job_start", "job": s["job"], "w": W, "h": H,
          "fps": fps, "total": total})


def _finish_stream(s: dict) -> None:
    """发出 done 事件并标记该流结束（VideoCapture 由清理阶段统一 release）。"""
    if s["done"]:
        return
    s["done"] = True
    emit({"type": "done", "job": s["job"], "frames": s["frame_idx"],
          "elapsed": round(time.time() - s["t0"], 1)})


def _close_cap(s: dict) -> None:
    # 先终止读帧线程，避免释放 cap 后线程仍尝试 read 触发异常
    reader = s.get("reader")
    if reader is not None and not s["stop"].is_set():
        s["stop"].set()
        with s["cv"]:
            s["cv"].notify_all()
        reader.join(timeout=0.5)
        s["reader"] = None
    if s["cap"] is not None:
        s["cap"].release()
        s["cap"] = None


def _process_frame(s: dict, frame, dets, hl) -> None:
    """逐流处理单帧：H/L 分配 → 闪烁去抖 → 1Hz 采样上报 → 画框 → 缩略图。"""
    samples = _assign_led_ids(dets, hl)
    s["last_states"].update(samples)          # 抗单帧漏检：缺失沿用旧值
    flashes = s["tracker"].update(samples)
    elapsed = time.time() - s["t0"]
    this_sec = int(s["frame_idx"] / s["fps"]) if s["fps"] > 0 else 0
    if this_sec != s["last_sec"]:
        s["last_sec"] = this_sec
        emit({"type": "sample", "job": s["job"], "frame": s["frame_idx"],
              "elapsed": round(elapsed, 1), "flashes": dict(flashes),
              "states": dict(s["last_states"])})
    _draw(frame, dets, hl)
    thumb_h = int(s["h"] * s["thumb_scale"])
    if thumb_h > 0 and (s["frame_idx"] - s["last_thumb"]) >= s["thumb_step"]:
        s["last_thumb"] = s["frame_idx"]
        if s["outdir"]:
            out_dir = Path(s["outdir"])
            out_dir.mkdir(parents=True, exist_ok=True)
            thumb = cv2.resize(frame, (THUMB_WIDTH, thumb_h),
                               interpolation=cv2.INTER_AREA)
            cv2.imwrite(str(out_dir / f"cell_{s['job']}.jpg"), thumb,
                        [cv2.IMWRITE_JPEG_QUALITY, 80])


# ------------------------------------------------------------------ 调度
def _tick(engine: DetectionEngine) -> bool:
    """一轮调度：开新流 → 收尾已停/完成的流 → 打包到点帧 batch → 逐流后处理。"""
    now = time.time()
    with _streams_lock:
        entries = list(_streams.values())

    # 1) 打开新到流的视频（含校验）；已 stop 的直接结束，免开流
    for s in entries:
        if s["opened"] or s["done"]:
            continue
        if s["stop"].is_set():
            s["done"] = True
            continue
        _open_stream(s)

    # 2) 已 stop / 视频已读完(EOF) 的流 → 发 done
    for s in entries:
        if not s["opened"] or s["done"]:
            continue
        if s["stop"].is_set() or not s["cap"].isOpened():
            _finish_stream(s)

    # 3) 聚合「到点」的帧（从预读缓冲取，非阻塞）→ 一次 YOLO batch
    batch = []      # list[(stream, frame)]
    shapes = []
    for s in entries:
        if (s["opened"] and not s["done"] and not s["stop"].is_set()
                and now >= s["next_t"]):
            item = _pop_frame(s)
            if item is None:
                continue                        # 缓冲空：等读帧线程
            if item[0] == "eof":
                _finish_stream(s)
                continue
            frame = item[1]
            s["frame_idx"] += 1
            s["next_t"] = now + s["period"]     # 按自身帧率独立节流
            batch.append((s, frame))
            shapes.append([frame.shape[0], frame.shape[1]])

    worked = bool(batch)
    if batch:
        dets_batch = engine.detect_batch([f for _s, f in batch], shapes)
        # H/L 分类跨流聚合一次前向
        hl_list = engine.classify_batch(
            [(f, dets) for (_s, f), dets in zip(batch, dets_batch)])
        for (s, frame), dets, hl in zip(batch, dets_batch, hl_list):
            if s["stop"].is_set() or s["done"]:
                continue
            _process_frame(s, frame, dets, hl)

    # 4) 清理已结束的流
    with _streams_lock:
        for job in list(_streams.keys()):
            s = _streams[job]
            if s["done"]:
                _close_cap(s)
                del _streams[job]
    return worked


def scheduler_loop(engine: DetectionEngine) -> None:
    while not _sched_stop.is_set():
        try:
            worked = _tick(engine)
        except Exception:
            traceback.print_exc()
            worked = False
        # 有活时快轮询以满足节流分辨率；空闲时降频省 CPU
        _sched_stop.wait(0.002 if worked else 0.015)


# ------------------------------------------------------------------ 静默集中监控
# monitor：一次跑最多 54 路"设备视频流"，每路按目标帧率(默认4fps)后台检测，
# 不做预览/缩略图，只在内存聚合各 LED 亮灭与闪烁统计；GUI 通过 `snapshot`
# 命令轮询聚合结果。GPU 一次 batch 前向 + NMS 跨图并行，支撑高路数低帧率。
#
# 数据流：video -> cap.read(按目标帧率节流) -> _decode_batch(GPU batch) ->
#          detect_batch_parallel(NMS 并行) -> classify_batch -> FlashTracker -> 聚合
def _monitor_open(cmd: dict):
    """创建 monitor 状态并预校验视频存在。返回 (mon, errmsg|None)。"""
    jobs_raw = cmd.get("jobs") or []
    fps = float(cmd.get("fps", MONITOR_DEFAULT_FPS))
    conf = float(cmd.get("conf", 0.25))
    nms = float(cmd.get("nms", 0.45))
    if len(jobs_raw) > MONITOR_MAX_STREAMS:
        return None, f"静默监控一次最多 {MONITOR_MAX_STREAMS} 路，当前 {len(jobs_raw)}"
    if len(jobs_raw) < 1:
        return None, "未提供任何视频"

    jobs = {}
    for it in jobs_raw:
        job = int(it["job"])
        path = str(Path(it["video"]).resolve())
        if not Path(path).exists():
            return None, f"视频不存在: {path}"
        if job in jobs:
            continue
        jobs[job] = {
            "job": job, "path": path,
            "cap": None, "fps": fps, "period": 1.0 / fps if fps > 0 else 0.25,
            "w": 0, "h": 0, "total": 0, "rate": 0.0,
            "frame": 0, "t0": 0.0, "next_t": 0.0, "conf": conf, "nms": nms,
            "done": False, "opened": False, "error": None,
            "loop": bool(cmd.get("loop", False)),
            "loops": 0,
            "tracker": None, "last": {}, "flashes": {}, "elapsed": 0.0,
        }
    return {"stop": threading.Event(), "conf": conf, "nms": nms,
            "jobs": jobs, "fps": fps}, None


def _monitor_as_snapshot(mon: dict) -> dict:
    """把 mon 状态转成可下发的聚合快照（jobs 本身是简单 dict，可浅拷贝）。"""
    streams = []
    all_done = True
    for j in mon["jobs"].values():
        streams.append({
            "job": j["job"], "w": j["w"], "h": j["h"],
            "fps": round(j["rate"], 1), "frame": j["frame"], "total": j["total"],
            "elapsed": round(j["elapsed"], 1),
            "loops": j.get("loops", 0),
            "flashes": dict(j["flashes"]), "states": dict(j["last"]),
            "status": "done" if j["done"] else ("error" if j["error"]
                                                else ("opened" if j["opened"]
                                                      else "opening")),
            "error": j["error"],
        })
        if not j["done"] and not j["error"]:
            all_done = False
    return {"type": "snapshot", "count": len(streams), "done": all_done,
            "streams": streams}


def _monitor_loop(engine) -> None:
    global _mon
    mon = None
    try:
        with _mon_lock:
            mon = _mon
        stop = mon["stop"]
        jobs = mon["jobs"]
        target_fps = mon["fps"]

        # 打开所有路视频
        for j in jobs.values():
            cap = cv2.VideoCapture(j["path"])
            if not cap.isOpened():
                j["error"] = "无法打开视频: " + j["path"]
                continue
            vfps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            W, H = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), \
                   int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            j["cap"] = cap
            j["w"], j["h"], j["total"] = W, H, total
            rate = min(vfps, target_fps) if vfps > 0 else target_fps
            j["rate"] = rate
            j["t0"] = time.time()
            # 全同步首帧：让 54 路同相位到期，靠 MONITOR_CHUNK 封顶拆分批次。
            # 相比细相位错峰（每路微小相位差会把 batch 拆散，吞吐从 209fps 掉到
            # 135fps），同步 + 分批在保住满批次产能的同时，单次迭代 ≤~130ms。
            j["next_t"] = time.time()
            # 去抖帧数按真实检测帧率折算（大约 0.3s 的 OFF 才判为一次完整亮暗）
            debounce = max(1, round(0.3 * rate))
            j["tracker"] = FlashTracker(debounce_frames=debounce)
            j["opened"] = True
            # 预读管线：独立读帧线程把解码藏在 GPU 推理背后（与监控主循环解耦）
            j["readq"] = deque()
            j["cv"] = threading.Condition()
            j["stop"] = stop          # 与 monitor 共享退出信号
            j["reader"] = threading.Thread(
                target=_reader_loop, args=(j,), daemon=True)
            j["reader"].start()
        emit({"type": "monitor_start",
              "count": sum(1 for j in jobs.values() if j["opened"]),
              "fps": target_fps, "input": list(MONITOR_INPUT_SHAPE)})

        last_agg = 0.0
        while not stop.is_set():
            now = time.time()
            batch, shapes = [], []
            for j in jobs.values():
                if j["done"] or j["error"] or not j["opened"] or stop.is_set():
                    continue
                if now < j["next_t"]:
                    continue
                if len(batch) >= MONITOR_CHUNK:
                    break   # 本迭代批次已满，其余到点路下一迭代再处理（不掉吞吐）
                item = _pop_frame(j)
                if item is None:
                    continue            # 读帧线程尚未供帧，稍后再取（未到点/未读）
                if item[0] == "eof":
                    if j["loop"]:
                        # 循环检测：短视频 EOF 后回到首帧并重启读帧线程续跑
                        j["cap"].set(cv2.CAP_PROP_POS_FRAMES, 0)
                        j["readq"] = deque()
                        j["cv"] = threading.Condition()
                        j["reader"] = threading.Thread(
                            target=_reader_loop, args=(j,), daemon=True)
                        j["reader"].start()
                        j["loops"] += 1
                    else:
                        j["done"] = True
                        j["elapsed"] = time.time() - j["t0"]
                    continue
                frame = item[1]
                j["frame"] += 1
                # 锚定到 t0 的固定节奏（而非处理完成时刻），否则子批次在不同
                # 墙钟时刻处理会让 54 路相位漂移、到期时间散开、batch 变小掉吞吐。
                j["next_t"] = j["t0"] + j["frame"] * j["period"]
                batch.append((j, frame))
                shapes.append([frame.shape[0], frame.shape[1]])

            worked = bool(batch)
            if batch:
                with _infer_lock:
                    dets_batch = engine.detect_batch_parallel(
                        [f for _s, f in batch], shapes, max_workers=MONITOR_WORKERS)
                    hl_list = engine.classify_batch(
                        [(f, d) for (_s, f), d in zip(batch, dets_batch)])
                for (j, frame), dets, hl in zip(batch, dets_batch, hl_list):
                    if stop.is_set():
                        break
                    samples = _assign_led_ids(dets, hl)
                    j["last"].update(samples)           # 抗漏检沿用旧值
                    j["tracker"].update(samples)
                # 快照聚合不每轮做（遍历54路+dict拷贝有开销），按 ~0.25s 节流
                if now - last_agg >= 0.25:
                    with _mon_lock:
                        for j in jobs.values():
                            j["elapsed"] = time.time() - j["t0"]
                            j["flashes"] = dict(j["tracker"].flashes) \
                                if j["tracker"] else {}
                    last_agg = now
            stop.wait(0.001 if worked else 0.015)
    except Exception:
        traceback.print_exc()
    finally:
        # 先停读帧线程再释放 cap，避免边读边释放导致崩溃
        if mon is not None:
            mon["stop"].set()
            for j in mon["jobs"].values():
                cvx = j.get("cv")
                if cvx is not None and j.get("reader") is not None:
                    with cvx:
                        cvx.notify_all()    # 唤醒阻塞在 wait 的读线程退出
            for j in mon["jobs"].values():
                rd = j.get("reader")
                if rd is not None:
                    rd.join(timeout=0.5)
            for j in mon["jobs"].values():
                if j["cap"] is not None:
                    j["cap"].release()
                    j["cap"] = None
            with _mon_lock:
                _mon = None
        emit({"type": "monitor_finished"})


def handle_monitor(cmd: dict) -> None:
    global _mon
    with _mon_lock:
        if _mon is not None:
            emit({"type": "error", "message": "已有一轮静默监控在运行"})
            return
        mon, err = _monitor_open(cmd)
        if err:
            emit({"type": "error", "message": err})
            return
        _mon = mon
    engine = DetectionEngine(input_shape=MONITOR_INPUT_SHAPE,
                             backend=_vision_backend(),
                             onnx_path=str(
                                 DEPLOY_DIR / "yolo_ptq_int8_320_dyn.onnx"))
    threading.Thread(target=_monitor_loop, args=(engine,), daemon=True,
                     name="vision-monitor").start()


def handle_monitor_stop() -> None:
    with _mon_lock:
        mon = _mon
    if mon is not None:
        mon["stop"].set()


def handle_snapshot() -> None:
    with _mon_lock:
        mon = _mon
    if mon is None:
        emit({"type": "snapshot", "count": 0, "done": True, "streams": []})
        return
    emit(_monitor_as_snapshot(mon))


# ------------------------------------------------------------------ 命令
def handle_detect(cmd: dict) -> None:
    job = int(cmd["job"])
    with _streams_lock:
        existing = _streams.get(job)
        if existing is not None and not existing["done"]:
            return  # 同 job 已在运行，忽略重复
        active = sum(1 for s in _streams.values() if not s["done"])
        if active >= MAX_CONCURRENT_STREAMS:
            emit({"type": "error", "job": job,
                  "message": f"并发检测已达上限({MAX_CONCURRENT_STREAMS})"
                          "，请先停止一路再开始"})
            return
        _streams[job] = _new_stream(job, cmd)


def handle_stop(cmd: dict) -> None:
    job = int(cmd["job"])
    with _streams_lock:
        s = _streams.get(job)
    if s is not None:
        s["stop"].set()


def main() -> int:
    # 预加载模型（阻塞在进入命令循环之前，模型加载完成后再处理 job 命令）
    emit({"type": "status", "message": "预加载检测模型…"})
    try:
        engine = DetectionEngine(backend=_vision_backend())
    except FileNotFoundError as e:
        emit({"type": "fatal", "message": str(e)})
        return 1
    emit({"type": "ready", "model": f"yolo[{engine.backend}]+tinyconv",
          "device": str(engine.device),
          "n_classes": engine.num_classes})

    # 启动帧批处理调度线程；命令由主线程读取
    threading.Thread(target=scheduler_loop, args=(engine,), daemon=True,
                     name="vision-scheduler").start()

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
                handle_detect(cmd)
            elif kind == "stop":
                handle_stop(cmd)
            elif kind == "monitor":
                handle_monitor(cmd)
            elif kind == "monitor_stop":
                handle_monitor_stop()
            elif kind == "snapshot":
                handle_snapshot()
            elif kind == "quit":
                break
    except KeyboardInterrupt:
        pass

    # 停止调度线程并收尾所有流
    _sched_stop.set()
    with _streams_lock:
        for s in _streams.values():
            s["stop"].set()
    with _mon_lock:
        if _mon is not None:
            _mon["stop"].set()
    time.sleep(0.1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())