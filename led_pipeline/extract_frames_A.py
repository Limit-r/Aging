# -*- coding: utf-8 -*-
"""
从 Video 目录下 4 个视频中每隔 3 帧抽取一帧，保存到 datasets/A/JPEGImages
"""
import cv2
import os

VIDEO_DIR = os.path.join(os.path.dirname(__file__), '..', 'Video')
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), 'datasets', 'A', 'JPEGImages')
SAMPLE_INTERVAL = 2  # 每 2 帧取一张

os.makedirs(OUTPUT_DIR, exist_ok=True)

video_files = [f for f in os.listdir(VIDEO_DIR) if f.lower().endswith(('.mp4', '.avi', '.mov'))]
video_files.sort()
print(f"找到 {len(video_files)} 个视频: {video_files}")

for vi, vname in enumerate(video_files, start=1):
    vpath = os.path.join(VIDEO_DIR, vname)
    cap = cv2.VideoCapture(vpath)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    prefix = f"a{vi:02d}"
    frame_idx = 0
    saved = 0

    print(f"\n[{vname}] 总帧数={total_frames}, FPS={fps:.1f}, 间隔={SAMPLE_INTERVAL}")
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if frame_idx % SAMPLE_INTERVAL == 0:
            out_name = f"{prefix}_{frame_idx:06d}.jpg"
            out_path = os.path.join(OUTPUT_DIR, out_name)
            cv2.imwrite(out_path, frame)
            saved += 1
        frame_idx += 1

    cap.release()
    print(f"  -> 已保存 {saved} 张图片")

print(f"\n所有视频抽帧完成！共保存到: {OUTPUT_DIR}")