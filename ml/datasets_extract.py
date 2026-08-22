# -*- coding: utf-8 -*-
"""数据标注 · 视频抽帧导入（懒加载，数据中心「数据标注」页专用）。

把一段视频按间隔抽帧，自动写入对应系列（A / FP）的 JPEGImages 目录，
并延续现有命名规则（与 tools/extract_frames.py 保持一致）：

- A  系列：批次前缀 aNN（自动取下一个批次号），编号 aNN_XXXXXX.jpg（偶数风格）
- FP 系列：前缀 frame，编号 frame_XXXXXX.jpg（连续编号）

约束：
- 本模块只承载纯逻辑 + 文件 IO，不依赖 Qt；cv2 仅在函数内部导入，
  保证 data_page 懒加载时启动轻量（不碰 torch / opencv）。
- 只新增图片，不修改已有任何数据。

对外主入口：
    probe_video(path)                          -> dict（分辨率 / fps / 总帧数）
    extract_to_series(path, series, step, ...) -> dict（saved / target_dir / prefix）
"""

import os

# ml/ = 本文件所在目录
ML_ROOT = os.path.dirname(os.path.abspath(__file__))

A_JPEG_DIR = os.path.join(ML_ROOT, "datasets", "A", "JPEGImages")
FP_JPEG_DIR = os.path.join(ML_ROOT, "datasets", "FP", "JPEGImages")

# 各系列默认抽帧间隔（每 N 帧提取一张）
DEFAULT_STEP = {"A": 3, "FP": 5}

# 支持的系列（键即 GUI 下拉项）
SUPPORTED_SERIES = ("A", "FP")


def resolve_target_dir(series: str) -> str:
    """返回某系列 JPEGImages 目录的绝对路径（不存在时仍返回，不创建）。"""
    series = (series or "FP").upper()
    if series == "A":
        return A_JPEG_DIR
    return FP_JPEG_DIR


def _next_a_batch(jpeg_dir: str) -> int:
    """A 系列：返回下一个批次号（aNN，延续 a01~aNN）。"""
    batches = []
    try:
        names = os.listdir(jpeg_dir)
    except OSError:
        names = []
    for name in names:
        if not name.lower().endswith(".jpg"):
            continue
        head = name.split("_", 1)[0]  # a01_000000.jpg -> a01
        if len(head) == 3 and head[0] == "a" and head[1:].isdigit():
            batches.append(int(head[1:]))
    return (max(batches) + 1) if batches else 1


def next_start_index(jpeg_dir: str, prefix: str) -> int:
    """返回某前缀下一个可用编号（A 偶数风格 / FP 连续编号）。"""
    existing = []
    try:
        names = os.listdir(jpeg_dir)
    except OSError:
        names = []
    for name in names:
        if not name.lower().endswith(".jpg"):
            continue
        stem = os.path.splitext(name)[0]
        head, _, tail = stem.rpartition("_")
        if head == prefix and tail.isdigit():
            existing.append(int(tail))
    if not existing:
        return 0
    return (max(existing) + 2) if prefix.startswith("a") else (max(existing) + 1)


def probe_video(path: str) -> dict:
    """探测视频基本信息（用于 GUI 预览），打开失败抛 ValueError。"""
    import cv2

    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise ValueError("无法打开视频文件: %s" % path)
    try:
        return {
            "name": os.path.basename(path),
            "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            "fps": round(float(cap.get(cv2.CAP_PROP_FPS)), 1),
            "frames": int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
        }
    finally:
        cap.release()


def extract_to_series(video_path: str, series: str, step: int = None,
                      on_progress=None) -> dict:
    """把视频按间隔抽帧写入对应系列 JPEGImages。

    参数：
        video_path  : 视频文件绝对路径
        series      : "A" / "FP"
        step        : 每 N 帧提取一张；None 时用 DEFAULT_STEP[series]
        on_progress : 可选回调 on_progress(done, total)，供 UI 进度回显

    返回：
        {"saved": int, "target_dir": str, "prefix": str, "series": str}
    打开失败 / 系列非法时抛 ValueError。
    """
    import cv2

    series = (series or "FP").upper()
    if series not in SUPPORTED_SERIES:
        raise ValueError("未知系列: %s" % series)
    if step is None:
        step = DEFAULT_STEP.get(series, 5)
    step = max(1, int(step))

    jpeg_dir = resolve_target_dir(series)
    os.makedirs(jpeg_dir, exist_ok=True)
    prefix = ("a%02d" % _next_a_batch(jpeg_dir)) if series == "A" else "frame"
    start_idx = next_start_index(jpeg_dir, prefix)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError("无法打开视频文件: %s" % video_path)
    try:
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        saved = 0
        frame_idx = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            if frame_idx % step == 0:
                name = "%s_%06d.jpg" % (prefix, start_idx)
                cv2.imwrite(os.path.join(jpeg_dir, name), frame)
                start_idx += 2 if prefix.startswith("a") else 1
                saved += 1
            frame_idx += 1
            if on_progress is not None and frame_idx % 20 == 0:
                on_progress(frame_idx, total)
    finally:
        cap.release()

    if on_progress is not None:
        on_progress(total, total)
    return {
        "saved": saved,
        "target_dir": jpeg_dir,
        "prefix": prefix,
        "series": series,
    }
