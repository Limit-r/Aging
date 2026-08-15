# -*- coding: utf-8 -*-
"""
从视频中每3帧提取一张图片，扩充到对应系列的数据集。

用法:
    python led_pipeline/extract_video_frames.py
"""
import cv2
import os
from pathlib import Path

# ===== 配置 =====
VIDEO_DIR = Path(r'D:\Aging\Video')
A_JPEG_DIR = Path(r'D:\Aging\led_pipeline\datasets\A\JPEGImages')
FP_JPEG_DIR = Path(r'D:\Aging\led_pipeline\datasets\FP\JPEGImages')

# 视频 -> 目标系列映射
VIDEO_MAP = {
    '006.mp4': 'A',
    '007.mp4': 'FP',
    '008.mp4': 'FP',
    '005.mp4': 'FP',
    '009.mp4': 'FP',
    '010.mp4': 'FP',
}

FRAME_STEP = 5  # 每5帧提取一张


def get_next_a_index():
    """获取 A 系列下一个可用编号（a05_000000 起）"""
    existing = []
    for f in A_JPEG_DIR.glob('a05_*.jpg'):
        try:
            num = int(f.stem.split('_')[1])
            existing.append(num)
        except (IndexError, ValueError):
            pass
    if existing:
        return max(existing) + 2  # 步长2，保持偶数编号风格
    return 0


def get_next_fp_index():
    """获取 FP 系列下一个可用帧号"""
    max_num = -1
    for f in FP_JPEG_DIR.glob('frame_*.jpg'):
        try:
            num = int(f.stem.split('_')[1])
            if num > max_num:
                max_num = num
        except (IndexError, ValueError):
            pass
    return max_num + 1


def extract_frames(video_path, output_dir, prefix, start_idx, step=3):
    """从视频中每 step 帧提取一张图片"""
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        print(f'[ERROR] 无法打开视频: {video_path}')
        return 0

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f'  视频: {video_path.name}  {w}x{h} @ {fps:.1f}fps, 共 {total_frames} 帧')
    print(f'  提取间隔: 每 {step} 帧, 起始编号: {start_idx}')

    count = 0
    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % step == 0:
            if prefix == 'a05':
                # A 系列偶数编号风格
                out_name = f'{prefix}_{start_idx:06d}.jpg'
                start_idx += 2
            else:
                out_name = f'{prefix}_{start_idx:06d}.jpg'
                start_idx += 1
            out_path = output_dir / out_name
            cv2.imwrite(str(out_path), frame)
            count += 1

        frame_idx += 1

    cap.release()
    print(f'  提取完成: {count} 张图片 -> {output_dir}')
    return count


def main():
    print('=' * 60)
    print('视频帧提取工具 (每3帧一张)')
    print('=' * 60)

    total = 0

    for video_name, series in VIDEO_MAP.items():
        video_path = VIDEO_DIR / video_name
        if not video_path.exists():
            print(f'[WARN] 视频不存在, 跳过: {video_path}')
            continue

        print(f'\n处理 {video_name} -> {series} 系列')

        if series == 'A':
            start_idx = get_next_a_index()
            n = extract_frames(video_path, A_JPEG_DIR, 'a05', start_idx, FRAME_STEP)
        else:
            start_idx = get_next_fp_index()
            n = extract_frames(video_path, FP_JPEG_DIR, 'frame', start_idx, FRAME_STEP)

        total += n

    print()
    print('=' * 60)
    print(f'全部完成! 共提取 {total} 张图片')
    print('=' * 60)


if __name__ == '__main__':
    main()