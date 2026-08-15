# -*- coding: utf-8 -*-
"""
PC 端 ESP32-CAM LED 检测脚本

功能:
  1. 从 ESP32-CAM 的 MJPEG 流拉取视频帧
  2. 用当前训练好的 YOLOv8 模型做 7 类 LED 检测 (SIG_area / PWR_area / VPL_L / VPL_H / CPL_L / PWR_H / PWR_L)
  3. 实时显示带检测框的画面, 并叠加每类 LED 亮灭状态统计
  4. 支持 'q' 退出, 's' 保存当前帧, 空格暂停

架构说明:
  ESP32-CAM (采集+WiFi图传) ──HTTP MJPEG流──> PC (本脚本, YOLO推理+显示)
  "离线" 指: 不依赖云端/外网, YOLO 推理在 PC 本地完成。
  ESP32-CAM 硬件无法直接跑 YOLOv8 (SRAM 520KB, 推理需数 MB)。

用法:
  # 1. 先烧录 firmware/esp32cam_stream/esp32cam_stream.ino 到 ESP32-CAM, 串口会打印 IP
  # 2. PC 连同一手机热点 (QH), 运行:
  python detect/pc_yolo_detect.py --url http://192.168.43.123/stream

  # 指定权重/阈值
  python detect/pc_yolo_detect.py --url http://192.168.43.123/stream \
      --weights ml/weights/FP_v2/best_epoch_weights.pth --conf 0.25 --nms 0.45
"""
import argparse
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import requests
import torch
from PIL import Image, ImageDraw, ImageFont

# 模型/训练代码根 = ml/  (pc_yolo_detect.py -> detect -> 项目根, ml/ 下含 model/utils)
PROJECT_ROOT = Path(__file__).resolve().parents[1]          # d:\Aging
ML_ROOT = PROJECT_ROOT / 'ml'                               # 模型/训练代码根
sys.path.insert(0, str(ML_ROOT))

from model.YOLOV8 import YoloBody
from utils.utils_bbox import DecodeBox
from utils.utils import get_classes

DEFAULT_WEIGHTS = str(ML_ROOT / 'weights' / 'FP_v2' / 'best_epoch_weights.pth')
DEFAULT_LABELS  = str(ML_ROOT / 'datasets' / 'FP' / 'label.txt')
DEFAULT_OUTDIR  = str(PROJECT_ROOT / 'detect' / 'outputs')

# 每类一种颜色 (BGR), 与 detect_fp_video.py 保持一致
CLASS_COLORS = {
    'SIG_area': (0, 200, 0),     # 绿
    'PWR_area': (0, 165, 255),   # 橙
    'VPL_L':    (0, 0, 255),     # 红
    'VPL_H':    (255, 100, 100), # 浅红
    'CPL_L':    (255, 0, 0),     # 蓝
    'PWR_H':    (0, 255, 255),   # 黄
    'PWR_L':    (180, 130, 70),  # 棕
}

# 亮/灭态映射 (用于状态统计): _H 后缀=亮, _L 后缀=灭, _area=区域 (不计入亮灭)
def led_state(cname):
    if cname.endswith('_H'):
        return 'ON'
    if cname.endswith('_L'):
        return 'OFF'
    return None  # area 类不计入亮灭


class MJpegStreamer:
    """从 HTTP MJPEG 流逐帧读取 JPEG 图片。

    MJPEG 流格式: multipart/x-mixed-replace, 每帧用 --boundary 分隔,
    每段含 Content-Length 头 + 二进制 JPEG 数据。
    """

    def __init__(self, url, timeout=10):
        self.url = url
        self.timeout = timeout
        self.session = requests.Session()
        self.resp = None
        self.buf = b''

    def connect(self):
        """发起连接, 返回是否成功。"""
        try:
            self.resp = self.session.get(self.url, stream=True, timeout=self.timeout)
            if self.resp.status_code != 200:
                print('[ERR] 流服务器返回状态码: %d' % self.resp.status_code)
                return False
            print('[OK] 已连接 MJPEG 流: %s' % self.url)
            return True
        except requests.exceptions.RequestException as e:
            print('[ERR] 连接失败: %s' % e)
            print('       请确认:')
            print('       1. ESP32-CAM 已上电并连接到热点 QH')
            print('       2. PC 与 ESP32-CAM 在同一热点下')
            print('       3. URL 正确 (串口打印的 IP)')
            return False

    def read_frame(self):
        """读取下一帧 JPEG, 返回 numpy BGR 数组或 None (失败/结束)。"""
        if self.resp is None:
            return None
        # 在 buf 中找下一帧 JPEG (FFD8...FFD9)
        while True:
            # 找 JPEG 起始标记
            start = self.buf.find(b'\xff\xd8')
            if start >= 0:
                end = self.buf.find(b'\xff\xd9', start + 2)
                if end >= 0:
                    jpg = self.buf[start:end + 2]
                    self.buf = self.buf[end + 2:]
                    arr = np.frombuffer(jpg, dtype=np.uint8)
                    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                    return img
            # buf 中没有完整 JPEG, 继续读流
            try:
                chunk = next(self.resp.iter_content(chunk_size=4096))
                if not chunk:
                    return None
                self.buf += chunk
            except StopIteration:
                return None
            except requests.exceptions.RequestException:
                return None

    def close(self):
        if self.resp is not None:
            self.resp.close()
            self.resp = None


def load_model(weights, num_classes, phi, input_shape, device):
    yolo = YoloBody(input_shape, num_classes, phi, pretrained=False)
    state = torch.load(weights, map_location=device, weights_only=False)
    if isinstance(state, dict) and 'model' in state:
        yolo.load_state_dict(state['model'])
    else:
        yolo.load_state_dict(state)
    yolo = yolo.to(device).eval()
    return yolo


def detect_one(yolo, decodebox, num_classes, input_shape, image_pil, device, conf_thres, nms_thres):
    """单张 PIL 图像推理, 返回 [(x1,y1,x2,y2,score,cls_id), ...] (原图坐标)。"""
    iw, ih = image_pil.size
    image_shape = np.array([ih, iw])

    scale = min(input_shape[0] / ih, input_shape[1] / iw)
    nw, nh = int(iw * scale), int(ih * scale)
    resized = image_pil.resize((nw, nh), Image.BICUBIC)
    canvas = Image.new('RGB', input_shape, (128, 128, 128))
    canvas.paste(resized, ((input_shape[1] - nw) // 2, (input_shape[0] - nh) // 2))
    arr = np.array(canvas, dtype='float32') / 255.0
    arr = np.transpose(arr, (2, 0, 1))[None]
    images = torch.from_numpy(arr).to(device)

    with torch.no_grad():
        outputs = yolo.forward(images)
        results = decodebox.decode_box(outputs)
        results = decodebox.non_max_suppression(
            results, num_classes, input_shape=input_shape,
            image_shape=image_shape, letterbox_image=True,
            conf_thres=conf_thres, nms_thres=nms_thres)

    if results[0] is None:
        return []
    out = []
    top_label = np.array(results[0][:, 5], dtype='int32')
    top_conf = results[0][:, 4]
    top_boxes = results[0][:, :4]
    for i in range(len(top_label)):
        # 关键: yolo_correct_boxes 末尾拼接顺序是 (y1, x1, y2, x2), 按此顺序解包
        y1, x1, y2, x2 = top_boxes[i]
        out.append((float(x1), float(y1), float(x2), float(y2),
                    float(top_conf[i]), int(top_label[i])))
    return out


def draw_on_cvframe(frame, dets, class_names, frame_idx, fps):
    """在 OpenCV BGR 帧上绘制检测框 + 左上角信息 + 右上角亮灭统计。"""
    h, w = frame.shape[:2]

    # 亮灭状态统计
    on_count = 0
    off_count = 0
    for (x1, y1, x2, y2, score, cid) in dets:
        cname = class_names[cid] if cid < len(class_names) else str(cid)
        st = led_state(cname)
        if st == 'ON':
            on_count += 1
        elif st == 'OFF':
            off_count += 1

    # 画检测框
    for (x1, y1, x2, y2, score, cid) in dets:
        cname = class_names[cid] if cid < len(class_names) else str(cid)
        color = CLASS_COLORS.get(cname, (200, 200, 200))
        cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), color, 2)
        label = '%s %.2f' % (cname, score)
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        ty = max(int(y1) - th - 4, 0)
        cv2.rectangle(frame, (int(x1), ty), (int(x1) + tw + 4, ty + th + 4), color, -1)
        cv2.putText(frame, label, (int(x1) + 2, ty + th + 1),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)

    # 左上角: 帧号/fps/检出数
    info = 'frame:%d  fps:%.1f  det:%d  (q=quit, s=save, space=pause)' % (frame_idx, fps, len(dets))
    cv2.rectangle(frame, (0, 0), (520, 30), (40, 40, 40), -1)
    cv2.putText(frame, info, (8, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)

    # 右上角: LED 亮灭统计
    stat = 'LED ON: %d  OFF: %d' % (on_count, off_count)
    (sw, _), _ = cv2.getTextSize(stat, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
    cv2.rectangle(frame, (w - sw - 20, 0), (w, 36), (20, 20, 80), -1)
    cv2.putText(frame, stat, (w - sw - 10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2, cv2.LINE_AA)


def main():
    parser = argparse.ArgumentParser(description='ESP32-CAM LED 检测 (PC 端 YOLO 推理)')
    parser.add_argument('--url', required=True, help='ESP32-CAM MJPEG 流地址 (如 http://192.168.43.123/stream)')
    parser.add_argument('--weights', default=DEFAULT_WEIGHTS)
    parser.add_argument('--labels', default=DEFAULT_LABELS)
    parser.add_argument('--outdir', default=DEFAULT_OUTDIR)
    parser.add_argument('--phi', default='n')
    parser.add_argument('--conf', type=float, default=0.25)
    parser.add_argument('--nms', type=float, default=0.45)
    parser.add_argument('--no-preview', action='store_true', help='不显示预览 (无头环境)')
    parser.add_argument('--save-video', action='store_true', help='保存检测结果为视频')
    args = parser.parse_args()

    class_names, num_classes = get_classes(args.labels)
    print('类别:', class_names, '数量:', num_classes)

    input_shape = (640, 640)
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print('设备:', device)

    if not os.path.exists(args.weights):
        print('[ERROR] 权重不存在: %s' % args.weights)
        print('        请先用 ml/train/train_fp.py 完成训练。')
        sys.exit(1)

    yolo = load_model(args.weights, num_classes, args.phi, input_shape, device)
    decodebox = DecodeBox(num_classes=num_classes, input_shape=input_shape)
    print('模型加载完成:', args.weights)

    # 连接 ESP32-CAM 流
    streamer = MJpegStreamer(args.url)
    if not streamer.connect():
        sys.exit(1)

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    writer = None
    if args.save_video:
        # 视频写入器在第一帧拿到尺寸后初始化
        pass

    frame_idx = 0
    t0 = time.time()
    paused = False
    print('=' * 60)
    print('开始拉流检测 (q=退出, s=保存当前帧, 空格=暂停)')
    print('=' * 60)

    while True:
        if not paused:
            frame = streamer.read_frame()
            if frame is None:
                print('[WARN] 流结束或读取失败, 尝试重连...')
                streamer.close()
                time.sleep(2)
                if not streamer.connect():
                    print('[ERR] 重连失败, 退出')
                    break
                continue

            frame_idx += 1
            # OpenCV BGR -> PIL RGB
            image_pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            dets = detect_one(yolo, decodebox, num_classes, input_shape,
                              image_pil, device, args.conf, args.nms)

            elapsed = time.time() - t0
            cur_fps = frame_idx / elapsed if elapsed > 0 else 0
            draw_on_cvframe(frame, dets, class_names, frame_idx, cur_fps)

            # 终端打印 (每帧简报)
            det_summary = {}
            for d in dets:
                cn = class_names[d[5]] if d[5] < len(class_names) else str(d[5])
                det_summary[cn] = det_summary.get(cn, 0) + 1
            print('  frame %4d  fps %.1f  %s' % (frame_idx, cur_fps, det_summary))

            # 保存视频
            if args.save_video:
                if writer is None:
                    h, w = frame.shape[:2]
                    out_path = str(outdir / ('esp32cam_det_%d.mp4' % int(time.time())))
                    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                    writer = cv2.VideoWriter(out_path, fourcc, 15, (w, h))
                    print('[INFO] 视频保存到:', out_path)
                writer.write(frame)

        if not args.no_preview:
            cv2.imshow('ESP32-CAM LED detect (q=quit, s=save, space=pause)', frame)
            key = cv2.waitKey(1 if not paused else 0) & 0xFF
            if key == ord('q'):
                print('用户中断')
                break
            elif key == 32:  # 空格
                paused = not paused
                print('已暂停' if paused else '继续')
            elif key == ord('s'):
                save_path = str(outdir / ('frame_%d.jpg' % frame_idx))
                cv2.imwrite(save_path, frame)
                print('[INFO] 已保存:', save_path)

    streamer.close()
    if writer is not None:
        writer.release()
    if not args.no_preview:
        cv2.destroyAllWindows()

    elapsed = time.time() - t0
    print('=' * 60)
    print('完成: 共 %d 帧, 耗时 %.1fs, 平均 %.1f fps' %
          (frame_idx, elapsed, frame_idx / elapsed if elapsed > 0 else 0))


if __name__ == '__main__':
    main()
