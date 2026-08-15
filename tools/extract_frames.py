# -*- coding: utf-8 -*-
"""
视频抽帧工具：从 video/ 目录的视频中按间隔抽帧，扩充到对应系列的数据集。

由 led_pipeline/extract_video_frames.py 与 extract_frames_A.py 整合而来，
统一支持 A / FP 两个系列，视频源统一为项目根 video/ 目录。

用法:
    conda activate Aging
    python tools/extract_frames.py

系列命名规则:
    - A:  前缀 aNN, 输出到 led_pipeline/datasets/A/JPEGImages, 编号 aNN_XXXXXX.jpg (偶数风格)
    - FP: 前缀 frame, 输出到 led_pipeline/datasets/FP/JPEGImages, 编号 frame_XXXXXX.jpg (连续编号)
"""
import cv2
from pathlib import Path

# ============================================================
# 配置
# ============================================================
PROJECT_ROOT = Path(__file__).resolve().parents[1]
VIDEO_DIR = PROJECT_ROOT / 'video'
A_JPEG_DIR = PROJECT_ROOT / 'led_pipeline' / 'datasets' / 'A' / 'JPEGImages'
FP_JPEG_DIR = PROJECT_ROOT / 'led_pipeline' / 'datasets' / 'FP' / 'JPEGImages'

# 视频 -> 目标前缀映射（键为 video/ 下的文件名，值决定系列与命名）
#   - 'frame'  -> FP 系列
#   - 'aNN'    -> A 系列（NN 为批次号，延续现有 a01~a05 命名）
# 注：FP00~FP04 为原始源视频（已抽帧入 datasets/FP），此处默认保留扩充批次映射。
VIDEO_MAP = {
    '005.mp4': 'frame',
    '006.mp4': 'a06',
    '007.mp4': 'frame',
    '008.mp4': 'frame',
    '009.mp4': 'frame',
    '010.mp4': 'frame',
}

FRAME_STEP = 5  # 每 N 帧提取一张


def get_next_index(jpeg_dir, prefix):
    """获取某系列下一个可用编号（A 偶数风格 / FP 连续编号）"""
    existing = []
    for f in jpeg_dir.glob(f'{prefix}_*.jpg'):
        try:
            existing.append(int(f.stem.rsplit('_', 1)[1]))
        except (IndexError, ValueError):
            pass
    if not existing:
        return 0
    return (max(existing) + 2) if prefix.startswith('a') else (max(existing) + 1)


def extract_frames(video_path, output_dir, prefix, start_idx, step):
    """从单个视频中每 step 帧提取一张图片"""
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
            out_name = f'{prefix}_{start_idx:06d}.jpg'
            cv2.imwrite(str(output_dir / out_name), frame)
            # A 系列保持偶数编号风格，FP 系列连续编号
            start_idx += 2 if prefix.startswith('a') else 1
            count += 1
        frame_idx += 1

    cap.release()
    print(f'  提取完成: {count} 张图片 -> {output_dir}')
    return count


def main():
    print('=' * 60)
    print(f'视频帧提取工具 (每 {FRAME_STEP} 帧一张)')
    print(f'视频源目录: {VIDEO_DIR}')
    print('=' * 60)

    if not VIDEO_DIR.exists():
        print(f'[WARN] 视频目录不存在: {VIDEO_DIR}')
        return

    total = 0
    for video_name, prefix in VIDEO_MAP.items():
        video_path = VIDEO_DIR / video_name
        if not video_path.exists():
            print(f'[WARN] 视频不存在, 跳过: {video_path}')
            continue

        series = 'A' if prefix.startswith('a') else 'FP'
        output_dir = A_JPEG_DIR if series == 'A' else FP_JPEG_DIR
        output_dir.mkdir(parents=True, exist_ok=True)
        start_idx = get_next_index(output_dir, prefix)

        print(f'\n处理 {video_name} -> {series} 系列 (prefix={prefix})')
        total += extract_frames(video_path, output_dir, prefix, start_idx, FRAME_STEP)

    print()
    print('=' * 60)
    print(f'全部完成! 共提取 {total} 张图片')
    print('=' * 60)


if __name__ == '__main__':
    main()