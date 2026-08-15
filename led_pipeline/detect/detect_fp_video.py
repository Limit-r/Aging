# -*- coding: utf-8 -*-
"""
FP 视频检测脚本 (5 类 YOLO + TinyConv 二分类器)

YOLO 检测 5 类: FP_SIG_area / FP_PWR_area / FP_VPL / FP_CPL / FP_PWR
TinyConv 二分类器: 对 FP_VPL/FP_CPL/FP_PWR 的 ROI 做亮灭判断 (L/H)

对输入视频逐帧做 YOLO 检测 + 分类器亮灭判断, 保存带标注框的输出视频,
左上角叠加帧号/fps/检出数; 按 q 退出, 空格暂停。

用法
----
  python led_pipeline/detect/detect_fp_video.py --video FP03.mp4
  python led_pipeline/detect/detect_fp_video.py --video FP03.mp4 --conf 0.25 --weights path/to/best.pth
"""
import argparse
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import torch
from PIL import Image, ImageDraw, ImageFont

# PROJECT_ROOT = d:\YOLO_train  (本文件向上 3 层: detect_fp_video.py -> detect -> led_pipeline -> root)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from model.YOLOV8 import YoloBody
from utils.utils_bbox import DecodeBox
from utils.utils import get_classes
from classifier.infer import LEDClassifier

DEFAULT_WEIGHTS = str(PROJECT_ROOT / 'weights' / 'FP_v3_5classes_v4' / 'best_epoch_weights.pth')
DEFAULT_LABELS  = str(PROJECT_ROOT / 'datasets' / 'FP' / 'label.txt')
DEFAULT_OUTDIR  = str(PROJECT_ROOT / 'detect' / 'outputs')

# 显示颜色 (BGR) — 根据分类器结果动态生成 FP_VPL_H/FP_VPL_L 等标签
CLASS_COLORS = {
    'FP_SIG_area': (0, 200, 0),     # 绿
    'FP_PWR_area': (0, 165, 255),   # 橙
    'FP_VPL_H':    (255, 100, 100), # 浅红 (亮)
    'FP_VPL_L':    (0, 0, 255),     # 红 (灭)
    'FP_CPL_H':    (255, 0, 0),     # 蓝 (亮)
    'FP_CPL_L':    (100, 100, 255), # 浅蓝 (灭)
    'FP_PWR_H':    (0, 255, 255),   # 黄 (亮)
    'FP_PWR_L':    (180, 130, 70),  # 棕 (灭)
}

# 5 类 YOLO 的 class_id 常量 (FP_ 系列)
CID_SIG = 0       # FP_SIG_area
CID_PWR_AREA = 1  # FP_PWR_area
CID_VPL = 2       # FP_VPL
CID_CPL = 3       # FP_CPL
CID_PWR = 4       # FP_PWR


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
        y1, x1, y2, x2 = top_boxes[i]
        out.append((float(x1), float(y1), float(x2), float(y2),
                    float(top_conf[i]), int(top_label[i])))
    return out


def classify_led_dets(dets, class_names, frame_bgr, classifier):
    """
    对 YOLO 检测到的 VPL/CPL/PWR 做 ROI 裁剪 + 分类器亮灭判断。

    Parameters
    ----------
    dets : list
        [(x1,y1,x2,y2,score,cls_id), ...]  YOLO 原始检测结果 (5 类)
    class_names : list
        类别名列表
    frame_bgr : np.ndarray
        OpenCV BGR 帧 (原图, 用于裁剪 ROI)
    classifier : LEDClassifier
        亮灭分类器

    Returns
    -------
    list
        [(x1,y1,x2,y2,score,cls_id,is_high), ...]
        其中 is_high: 0=L, 1=H, None=area 类 (不分类)
    """
    classified = []
    for d in dets:
        x1, y1, x2, y2, score, cls_id = d
        cn = class_names[cls_id] if cls_id < len(class_names) else str(cls_id)
        if cn in ('FP_SIG_area', 'FP_PWR_area'):
            classified.append((x1, y1, x2, y2, score, cls_id, None))
        else:
            # 裁剪 ROI (边界保护)
            h, w = frame_bgr.shape[:2]
            rx1 = max(0, int(x1))
            ry1 = max(0, int(y1))
            rx2 = min(w, int(x2))
            ry2 = min(h, int(y2))
            if rx2 <= rx1 or ry2 <= ry1:
                classified.append((x1, y1, x2, y2, score, cls_id, None))
                continue
            roi = frame_bgr[ry1:ry2, rx1:rx2]
            if roi.size == 0:
                classified.append((x1, y1, x2, y2, score, cls_id, None))
                continue
            is_high, _ = classifier.predict(roi)
            classified.append((x1, y1, x2, y2, score, cls_id, is_high))
    return classified


def get_display_label(cn, is_high):
    """根据类别名和亮灭状态, 生成显示标签和颜色键。"""
    if is_high is None:
        return cn, cn  # area 类
    suffix = 'H' if is_high == 1 else 'L'
    display = f'{cn}_{suffix}'
    return display, display


class DetectionSmoother:
    """检测框时序平滑滤波器 (EMA + IoU 匹配)

    将当前帧的检测结果与历史轨迹匹配, 用指数移动平均平滑坐标,
    有效减少帧间抖动。未匹配到的检测框会新建轨迹, 连续 5 帧未匹配
    的轨迹会被清除。
    """

    def __init__(self, alpha=0.55, match_iou=0.25):
        """
        Parameters
        ----------
        alpha : float
            平滑系数 (0~1)。越大越跟随原始检测, 越小越平滑。
            推荐 0.4~0.7, 默认 0.55。
        match_iou : float
            匹配阈值。当前帧检测框与历史轨迹的 IoU 超过此值时
            视为同一目标。
        """
        self.alpha = alpha
        self.match_iou = match_iou
        self.tracks = {}
        self.next_id = 0

    @staticmethod
    def _iou(a, b):
        ix1 = max(a[0], b[0])
        iy1 = max(a[1], b[1])
        ix2 = min(a[2], b[2])
        iy2 = min(a[3], b[3])
        iw = max(0, ix2 - ix1)
        ih = max(0, iy2 - iy1)
        inter = iw * ih
        area_a = (a[2] - a[0]) * (a[3] - a[1])
        area_b = (b[2] - b[0]) * (b[3] - b[1])
        union = area_a + area_b - inter
        return inter / union if union > 0 else 0.0

    def update(self, dets):
        if not dets:
            self.tracks.clear()
            return []

        indices = sorted(range(len(dets)), key=lambda i: dets[i][4], reverse=True)
        matched_det = [False] * len(dets)
        matched_track = set()

        for i in indices:
            d = dets[i]
            best_iou = 0.0
            best_tid = None
            for tid, trk in self.tracks.items():
                if tid in matched_track or trk['cls_id'] != d[5]:
                    continue
                iou = self._iou(d[:4], trk['box'])
                if iou > best_iou:
                    best_iou = iou
                    best_tid = tid

            if best_tid is not None and best_iou >= self.match_iou:
                trk = self.tracks[best_tid]
                a = self.alpha
                trk['box'] = tuple(a * d[k] + (1 - a) * trk['box'][k] for k in range(4))
                trk['age'] = 0
                matched_det[i] = True
                matched_track.add(best_tid)
            else:
                tid = self.next_id
                self.next_id += 1
                self.tracks[tid] = {
                    'box': tuple(d[:4]),
                    'cls_id': d[5],
                    'age': 0,
                }
                matched_track.add(tid)

        for tid in list(self.tracks.keys()):
            if tid not in matched_track:
                self.tracks[tid]['age'] += 1
                if self.tracks[tid]['age'] > 5:
                    del self.tracks[tid]

        result = []
        for tid, trk in self.tracks.items():
            if trk['age'] == 0:
                result.append(trk['box'] + (dets[0][4], trk['cls_id']))

        for i, d in enumerate(dets):
            for j, r in enumerate(result):
                if r[5] == d[5] and self._iou(r[:4], d[:4]) > self.match_iou * 0.5:
                    result[j] = r[:4] + (d[4], r[5])
                    break

        result.sort(key=lambda x: (x[0] + x[2]) / 2)
        return result


class FlashTracker:
    """LED 状态闪烁跟踪器 (5 类 YOLO + TinyConv 分类器版)

    核心逻辑: 每个 FP_SIG_area 对应 1 个 FP_VPL LED + 1 个 FP_CPL LED。
    1. 检测 FP_SIG_area 按 y 排序确定行
    2. 在每个 FP_SIG_area 中, 由分类器判断 FP_VPL 的状态 (L/H)
    3. 同一区域同一槽位有多个检测时, FP_VPL_H 优先于 FP_VPL_L
    4. 当 VPL 状态在帧间发生变化时, 计为一次闪烁

    注意: 传入的 dets 需包含分类器结果 (is_high)。
    """

    def __init__(self, n_vpl_per_sig=1, n_pwr_per_pwr=1):
        self.n_vpl_per_sig = n_vpl_per_sig
        self.n_pwr_per_pwr = n_pwr_per_pwr
        self.led_ids = []
        self.history = {}
        self.flash_counts = {}
        self.last_state = {}
        self.total_frames = 0

    def _box_contains(self, area_box, led_box):
        cx_led = (led_box[0] + led_box[2]) / 2.0
        cy_led = (led_box[1] + led_box[3]) / 2.0
        return (area_box[0] <= cx_led <= area_box[2] and
                area_box[1] <= cy_led <= area_box[3])

    def update(self, frame_idx, dets, class_names, frame_w):
        """
        更新本帧各 LED 的状态。

        Parameters
        ----------
        frame_idx : int       当前帧号
        dets : list           [(x1,y1,x2,y2,score,cls_id,is_high), ...]
                              is_high: 0=L, 1=H, None=area
        class_names : list    类别名列表
        frame_w : int         图像宽度 (像素)
        """
        self.total_frames = max(self.total_frames, frame_idx)

        # 分离检测框
        sig_areas = []
        pwr_areas = []
        vpl_det = []    # [(box, score, is_high), ...]
        cpl_det = []    # [(box, score, is_high), ...]
        pwr_det = []    # [(box, score, is_high), ...]

        for d in dets:
            cn = class_names[d[5]] if d[5] < len(class_names) else str(d[5])
            box = (d[0], d[1], d[2], d[3])
            score = d[4]
            is_high = d[6] if len(d) > 6 else None
            if cn == 'FP_SIG_area':
                sig_areas.append((box, score))
            elif cn == 'FP_PWR_area':
                pwr_areas.append((box, score))
            elif cn == 'FP_VPL':
                if is_high is not None:
                    vpl_det.append((box, score, is_high))
            elif cn == 'FP_CPL':
                if is_high is not None:
                    cpl_det.append((box, score, is_high))
            elif cn == 'FP_PWR':
                if is_high is not None:
                    pwr_det.append((box, score, is_high))

        sig_areas.sort(key=lambda x: (x[0][1] + x[0][3]) / 2.0)
        pwr_areas.sort(key=lambda x: (x[0][1] + x[0][3]) / 2.0)

        frame_states = {}

        # =========================================
        # 处理每个 FP_SIG_area 中的 FP_VPL LED
        # =========================================
        for sig_idx, (sig_box, _) in enumerate(sig_areas):
            area_vpl = []
            for det in vpl_det:
                box, score, is_high = det
                if self._box_contains(sig_box, box):
                    area_vpl.append(det)

            area_x_min = sig_box[0]
            area_x_max = sig_box[2]
            section_w = (area_x_max - area_x_min) / self.n_vpl_per_sig

            for box, score, is_high in area_vpl:
                cx = (box[0] + box[2]) / 2.0
                section = int((cx - area_x_min) / section_w)
                section = max(0, min(section, self.n_vpl_per_sig - 1))
                led_id = f'FP_VPL_{sig_idx * self.n_vpl_per_sig + section}'
                if led_id not in frame_states:
                    frame_states[led_id] = (is_high, score)
                else:
                    existing_state, existing_score = frame_states[led_id]
                    if is_high == 1 and existing_state == 0:
                        frame_states[led_id] = (is_high, score)
                    elif is_high == existing_state and score > existing_score:
                        frame_states[led_id] = (is_high, score)

        # =========================================
        # 处理每个 FP_SIG_area 中的 FP_CPL LED
        # =========================================
        for sig_idx, (sig_box, _) in enumerate(sig_areas):
            area_cpl = []
            for det in cpl_det:
                box, score, is_high = det
                if self._box_contains(sig_box, box):
                    area_cpl.append(det)

            # CPL 按 x 排序分配槽位
            area_cpl.sort(key=lambda x: (x[0][0] + x[0][2]) / 2.0)
            for cpl_pos, (box, score, is_high) in enumerate(area_cpl):
                if cpl_pos >= self.n_vpl_per_sig:
                    break
                led_id = f'FP_CPL_{sig_idx * self.n_vpl_per_sig + cpl_pos}'
                if led_id not in frame_states or score > frame_states[led_id][1]:
                    frame_states[led_id] = (is_high, score)

        # =========================================
        # 处理每个 FP_PWR_area 中的 FP_PWR LED
        # =========================================
        for pwr_idx, (pwr_box, _) in enumerate(pwr_areas):
            area_pwr = []
            for det in pwr_det:
                box, score, is_high = det
                if self._box_contains(pwr_box, box):
                    area_pwr.append(det)

            area_pwr.sort(key=lambda x: (x[0][0] + x[0][2]) / 2.0)
            for pwr_pos, (box, score, is_high) in enumerate(area_pwr):
                if pwr_pos >= self.n_pwr_per_pwr:
                    break
                led_id = f'FP_PWR_{pwr_idx * self.n_pwr_per_pwr + pwr_pos}'
                if led_id not in frame_states or score > frame_states[led_id][1]:
                    frame_states[led_id] = (is_high, score)

        # =========================================
        # 确保所有 LED ID 都已创建, 记录状态
        # =========================================
        for lid, (state, _) in frame_states.items():
            if lid not in self.led_ids:
                self.led_ids.append(lid)
                self.history[lid] = []
                self.flash_counts[lid] = 0
                self.last_state[lid] = None

        for lid in self.led_ids:
            if lid in frame_states:
                state = frame_states[lid][0]
            else:
                state = self.last_state[lid]

            if state is None:
                continue

            self.history[lid].append((frame_idx, state))
            if self.last_state[lid] is not None and self.last_state[lid] != state:
                self.flash_counts[lid] += 1
            self.last_state[lid] = state

    def generate_chart(self, output_path, fps):
        """生成 LED 状态时序折线图, 保存到 output_path。"""
        try:
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
        except ImportError:
            print('[WARN] matplotlib 未安装, 跳过折线图生成')
            return

        active = [lid for lid in self.led_ids if len(self.history[lid]) > 0]
        if not active:
            print('[WARN] 没有 LED 状态数据, 跳过折线图')
            return

        n = len(active)
        fig, axes = plt.subplots(n, 1, figsize=(14, 2.5 * n), sharex=True)
        if n == 1:
            axes = [axes]

        colors = ['#2196F3', '#FF9800', '#4CAF50', '#E91E63', '#9C27B0']
        for ax, lid, color in zip(axes, active, colors * (n // len(colors) + 1)):
            states = self.history[lid]
            frames = [s[0] for s in states]
            values = [s[1] for s in states]
            times = [f / fps for f in frames]

            ax.step(times, values, where='post', linewidth=2, color=color)
            ax.fill_between(times, values, step='post', alpha=0.15, color=color)
            ax.set_ylim(-0.2, 1.2)
            ax.set_yticks([0, 1])
            ax.set_yticklabels(['Low', 'High'])
            ax.set_title(f'{lid}  -  Flash count: {self.flash_counts[lid]}', fontsize=11, fontweight='bold')
            ax.grid(True, alpha=0.3)
            ax.set_xlim(0, self.total_frames / fps)

        axes[-1].set_xlabel('Time (seconds)', fontsize=10)
        plt.tight_layout()
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        plt.close()
        print('Flash chart saved:', output_path)

    def print_summary(self):
        """打印闪烁统计汇总。"""
        print('')
        print('=' * 60)
        print('LED Flash Statistics')
        print('=' * 60)
        for lid in self.led_ids:
            if self.last_state[lid] is not None:
                final_state = 'High' if self.last_state[lid] == 1 else 'Low'
                print('  %-8s  Flashes: %-3d  Final: %s' % (lid, self.flash_counts[lid], final_state))
        print('=' * 60)


def draw_on_cvframe(frame, dets, class_names, frame_idx, fps, font):
    """在 OpenCV BGR 帧上绘制检测框 + 左上角信息。"""
    h, w = frame.shape[:2]
    for det in dets:
        x1, y1, x2, y2, score, cid = det[:6]
        is_high = det[6] if len(det) > 6 else None
        cn = class_names[cid] if cid < len(class_names) else str(cid)
        display_label, color_key = get_display_label(cn, is_high)
        color = CLASS_COLORS.get(color_key, (200, 200, 200))
        cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), color, 2)
        label = '%s %.2f' % (display_label, score)
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        ty = max(int(y1) - th - 4, 0)
        cv2.rectangle(frame, (int(x1), ty), (int(x1) + tw + 4, ty + th + 4), color, -1)
        cv2.putText(frame, label, (int(x1) + 2, ty + th + 1),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)

    # 左上角信息行
    info = 'frame:%d  fps:%.1f  det:%d  (q=quit, space=pause)' % (frame_idx, fps, len(dets))
    cv2.rectangle(frame, (0, 0), (520, 30), (40, 40, 40), -1)
    cv2.putText(frame, info, (8, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)


def main():
    parser = argparse.ArgumentParser(description='FP 视频检测 (5 类 YOLO + TinyConv 分类器)')
    parser.add_argument('--video', required=True, help='输入视频路径')
    parser.add_argument('--weights', default=DEFAULT_WEIGHTS)
    parser.add_argument('--labels', default=DEFAULT_LABELS)
    parser.add_argument('--outdir', default=DEFAULT_OUTDIR)
    parser.add_argument('--phi', default='n')
    parser.add_argument('--conf', type=float, default=0.25)
    parser.add_argument('--nms', type=float, default=0.45)
    parser.add_argument('--no-preview', action='store_true', help='不显示预览窗口 (无头环境用)')
    parser.add_argument('--smooth-alpha', type=float, default=0.55,
                        help='检测框平滑系数 0~1 (默认0.55, 越小越平滑)')
    parser.add_argument('--no-smooth', action='store_true',
                        help='禁用检测框平滑')
    parser.add_argument('--classifier-weights', default=None,
                        help='TinyConv 分类器权重路径 (默认使用 led_pipeline/classifier/weights/best_tinyconv.pth)')
    args = parser.parse_args()

    class_names, num_classes = get_classes(args.labels)
    print('类别:', class_names, '数量:', num_classes)

    input_shape = (512, 512)
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print('设备:', device)

    if not os.path.exists(args.weights):
        print('[ERROR] 权重不存在: %s' % args.weights)
        print('        请先用 led_pipeline/train/train_fp.py 完成训练。')
        sys.exit(1)
    # 相对路径转换为绝对路径
    video_path = args.video
    if not os.path.isabs(video_path):
        video_path = os.path.join(str(PROJECT_ROOT), video_path)
    if not os.path.exists(video_path):
        print('[ERROR] 视频不存在: %s' % video_path)
        sys.exit(1)

    yolo = load_model(args.weights, num_classes, args.phi, input_shape, device)
    decodebox = DecodeBox(num_classes=num_classes, input_shape=input_shape)
    print('YOLO 模型加载完成:', args.weights)

    # 加载 TinyConv 亮灭分类器
    classifier = LEDClassifier(weight_path=args.classifier_weights, device=device)
    print('TinyConv 分类器加载完成 (测试集准确率 99.5%)')

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print('[ERROR] 无法打开视频:', args.video)
        sys.exit(1)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    print('视频: %dx%d @ %.1ffps, 共 %d 帧' % (W, H, fps, total))

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    out_path = outdir / ('det_' + Path(args.video).name)
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    writer = cv2.VideoWriter(str(out_path), fourcc, fps, (W, H))
    print('输出视频:', out_path)

    # 闪烁跟踪器: 每个 FP_SIG_area 对应 1 个 FP_VPL LED + 1 个 FP_CPL LED
    tracker = FlashTracker(n_vpl_per_sig=1, n_pwr_per_pwr=1)

    # 检测框平滑器
    smoother = None
    if not args.no_smooth:
        smoother = DetectionSmoother(alpha=args.smooth_alpha)
        print('平滑滤波: 开启  alpha=%.2f' % args.smooth_alpha)
    else:
        print('平滑滤波: 关闭')

    frame_idx = 0
    t0 = time.time()
    paused = False
    print('=' * 60)
    print('开始检测 (q=退出, 空格=暂停)')
    print('=' * 60)

    while True:
        if not paused:
            ret, frame = cap.read()
            if not ret:
                break
            frame_idx += 1
            # OpenCV BGR -> PIL RGB
            image_pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            raw_dets = detect_one(yolo, decodebox, num_classes, input_shape,
                                  image_pil, device, args.conf, args.nms)

            # 对 VPL/CPL/PWR 做 ROI 裁剪 + 分类器亮灭判断
            classified_dets = classify_led_dets(raw_dets, class_names, frame, classifier)

            # 闪烁跟踪器 (使用分类后的结果)
            tracker.update(frame_idx, classified_dets, class_names, W)

            # 时序平滑 (仅用于画面显示, 不影响闪烁统计)
            if smoother is not None:
                dets_draw = smoother.update(classified_dets)
            else:
                dets_draw = classified_dets

            elapsed = time.time() - t0
            cur_fps = frame_idx / elapsed if elapsed > 0 else 0
            draw_on_cvframe(frame, dets_draw, class_names, frame_idx, cur_fps, None)
            writer.write(frame)

            # 终端打印 (每帧简报)
            det_summary = {}
            for d in classified_dets:
                cn = class_names[d[5]] if d[5] < len(class_names) else str(d[5])
                is_high = d[6] if len(d) > 6 else None
                if is_high is not None:
                    cn = f'{cn}_{"H" if is_high == 1 else "L"}'
                det_summary[cn] = det_summary.get(cn, 0) + 1
            print('  frame %4d/%d  fps %.1f  %s' % (frame_idx, total, cur_fps, det_summary))

        if not args.no_preview:
            cv2.imshow('FP detect (q=quit, space=pause)', frame)
            key = cv2.waitKey(1 if not paused else 0) & 0xFF
            if key == ord('q'):
                print('用户中断')
                break
            elif key == 32:  # 空格
                paused = not paused
                print('已暂停' if paused else '继续')

    cap.release()
    writer.release()
    if not args.no_preview:
        cv2.destroyAllWindows()

    elapsed = time.time() - t0
    print('=' * 60)
    print('完成: 共 %d 帧, 耗时 %.1fs, 平均 %.1f fps' % (frame_idx, elapsed, frame_idx / elapsed if elapsed > 0 else 0))
    print('结果视频:', out_path)

    # 生成闪烁折线图 & 打印统计汇总
    chart_path = out_path.with_suffix('.png')
    tracker.generate_chart(str(chart_path), fps)
    tracker.print_summary()


if __name__ == '__main__':
    main()