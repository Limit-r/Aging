# -*- coding: utf-8 -*-
"""
A 系列视频检测脚本 (4 类 YOLO + TinyConv 二分类)

对输入视频逐帧做 YOLO 检测, 对非 area 的 ROI 使用 TinyConv 做 H/L 分类,
保存带标注框的输出视频, 左上角叠加帧号/fps/检出数; 按 q 退出, 空格暂停。

新增功能:
  - LED 闪烁统计 (FlashTracker)
  - 亮灭时序折线图 (保存为 PNG)

用法:
  python detect/detect_a_video.py --video D:\\Aging\\Video\\001.mp4
  python detect/detect_a_video.py --video D:\\Aging\\Video\\001.mp4 --conf 0.25
"""
import argparse
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import torch
from PIL import Image

# 模型/训练代码根 = ml/  (detect_a_video.py -> detect -> 项目根, ml/ 下含 model/utils/classifier)
ML_ROOT = Path(__file__).resolve().parents[1] / 'ml'
if str(ML_ROOT) not in sys.path:
    sys.path.insert(0, str(ML_ROOT))

from model.YOLOV8 import YoloBody
from utils.utils_bbox import DecodeBox
from utils.utils import get_classes

from classifier.model import TinyConv

# ===== 默认路径（统一从 ml/deploy/ 加载）=====
A_WEIGHTS = str(ML_ROOT / 'deploy' / 'yolo_best_deploy.pt')
A_LABELS  = str(ML_ROOT / 'deploy' / 'label_merged.txt')
A_CLF_WEIGHTS = str(ML_ROOT / 'deploy' / 'tinyconv_best.pth')
A_OUTDIR  = str(Path(__file__).resolve().parents[1] / 'detect' / 'outputs')

# 显示颜色 (BGR) — 按基础类别
BASE_COLORS = {
    'A_CLIP': (255, 100, 100),   # 浅红
    'A_PROT': (255, 0, 0),       # 蓝
    'A_PWR':  (0, 255, 255),     # 黄
    'A_area': (0, 200, 0),       # 绿
}
# H/L 文字后缀颜色
HL_COLORS = {
    'H': (0, 255, 0),    # 绿
    'L': (0, 0, 255),    # 红
}


def load_model(weights, num_classes, phi, input_shape, device):
    yolo = YoloBody(input_shape, num_classes, phi, pretrained=False)
    state = torch.load(weights, map_location=device, weights_only=False)
    if isinstance(state, dict) and 'model' in state:
        yolo.load_state_dict(state['model'])
    else:
        yolo.load_state_dict(state)
    yolo = yolo.to(device).eval()
    return yolo


def load_classifier(weights, device):
    model = TinyConv(in_channels=3, num_classes=2)
    state = torch.load(weights, map_location=device, weights_only=False)
    if isinstance(state, dict) and 'model' in state:
        model.load_state_dict(state['model'])
    else:
        model.load_state_dict(state)
    model = model.to(device).eval()
    return model


def detect_one(yolo, decodebox, num_classes, input_shape, image_pil, device,
               conf_thres, nms_thres):
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


def classify_rois(rois, classifier, device):
    """批量对 ROI 做 H/L 分类, 返回 ['H'|'L'|None, ...]"""
    if not rois:
        return []
    inputs = []
    for roi in rois:
        roi_rgb = cv2.cvtColor(roi, cv2.COLOR_BGR2RGB)
        r = cv2.resize(roi_rgb, (32, 32), interpolation=cv2.INTER_AREA)
        r = r.astype(np.float32) / 255.0
        r = np.transpose(r, (2, 0, 1))
        inputs.append(r)
    batch = torch.from_numpy(np.array(inputs)).to(device)
    with torch.no_grad():
        outputs = classifier(batch)
        _, preds = torch.max(outputs, 1)
    return ['H' if p == 1 else 'L' for p in preds.cpu().numpy()]


def draw_on_cvframe(frame, dets, class_names, hl_labels, frame_idx, fps):
    """在 OpenCV BGR 帧上绘制检测框 + 左上角信息 (线宽=1, 小字)。"""
    h, w = frame.shape[:2]
    for idx, det in enumerate(dets):
        x1, y1, x2, y2, score, cid = det
        base_cn = class_names[cid] if cid < len(class_names) else str(cid)

        # 确定显示名称和颜色 (只显示基础类名, 不显示 _H/_L 后缀)
        hl = hl_labels[idx] if idx < len(hl_labels) else None
        color = BASE_COLORS.get(base_cn, (200, 200, 200))
        display_name = base_cn

        # 线宽 1 的细框
        cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), color, 1)
        # 小字标签
        label = '%s %.2f' % (display_name, score)
        font_scale = 0.35
        thickness = 1
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thickness)
        ty = max(int(y1) - th - 3, 0)
        cv2.rectangle(frame, (int(x1), ty), (int(x1) + tw + 3, ty + th + 3), color, -1)
        cv2.putText(frame, label, (int(x1) + 1, ty + th),
                    cv2.FONT_HERSHEY_SIMPLEX, font_scale, (0, 0, 0), thickness, cv2.LINE_AA)

    # 左上角信息行 (缩小)
    info = 'frame:%d  fps:%.1f  det:%d  (q=quit, space=pause)' % (frame_idx, fps, len(dets))
    cv2.rectangle(frame, (0, 0), (460, 24), (40, 40, 40), -1)
    cv2.putText(frame, info, (6, 17), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)


class AFlashTracker:
    """A 系列 LED 状态闪烁跟踪器

    核心逻辑:
      1. YOLO 检测出 A_CLIP / A_PROT / A_PWR / A_area 四类
      2. 对 A_CLIP / A_PROT / A_PWR 做 H/L 分类
      3. 每类 LED 按 x 坐标排序分配槽位, 生成唯一 LED ID
      4. 当 LED 状态在帧间变化时, 计为一次闪烁
    """

    def __init__(self):
        self.led_ids = []
        self.history = {}
        self.flash_counts = {}
        self.last_state = {}
        self.total_frames = 0

    def update(self, frame_idx, dets, class_names, hl_labels, frame_w):
        """
        更新本帧各 LED 的状态。

        Parameters
        ----------
        frame_idx : int
        dets : list  [(x1,y1,x2,y2,score,cls_id), ...]
        hl_labels : list  ['H'|'L'|'', ...]
        frame_w : int  图像宽度
        """
        self.total_frames = max(self.total_frames, frame_idx)

        # 按 LED 类型分组 (排除 A_area)
        led_groups = {}  # {base_name: [(box, score, state), ...]}
        for i, d in enumerate(dets):
            cid = d[5]
            cn = class_names[cid] if cid < len(class_names) else str(cid)
            if cn == 'A_area':
                continue
            hl = hl_labels[i] if i < len(hl_labels) else ''
            if hl not in ('H', 'L'):
                continue
            state = 1 if hl == 'H' else 0
            box = (d[0], d[1], d[2], d[3])
            led_groups.setdefault(cn, []).append((box, d[4], state))

        # 每类按 x 坐标排序分配槽位
        frame_states = {}
        for base_cn, items in led_groups.items():
            items.sort(key=lambda x: (x[0][0] + x[0][2]) / 2.0)  # 按中心 x 排序
            for slot, (box, score, state) in enumerate(items):
                led_id = '%s_%d' % (base_cn, slot)
                if led_id not in frame_states or score > frame_states[led_id][1]:
                    frame_states[led_id] = (state, score)

        # 确保所有 LED ID 已创建, 记录状态
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
                # 未检出则保持上一帧状态
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

        colors = ['#2196F3', '#FF9800', '#4CAF50', '#E91E63', '#9C27B0', '#00BCD4']
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
            ax.set_title('%s  -  Flash count: %d' % (lid, self.flash_counts[lid]),
                         fontsize=11, fontweight='bold')
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
                print('  %-10s  Flashes: %-3d  Final: %s' % (lid, self.flash_counts[lid], final_state))
        print('=' * 60)


def main():
    parser = argparse.ArgumentParser(description='A 系列视频检测 (4 类 YOLO + TinyConv)')
    parser.add_argument('--video', required=True, help='输入视频路径')
    parser.add_argument('--weights', default=A_WEIGHTS)
    parser.add_argument('--labels', default=A_LABELS)
    parser.add_argument('--clf-weights', default=A_CLF_WEIGHTS)
    parser.add_argument('--outdir', default=A_OUTDIR)
    parser.add_argument('--phi', default='n')
    parser.add_argument('--conf', type=float, default=0.25)
    parser.add_argument('--nms', type=float, default=0.45)
    parser.add_argument('--no-preview', action='store_true',
                        help='不显示预览窗口 (无头环境用)')
    args = parser.parse_args()

    class_names, num_classes = get_classes(args.labels)
    print('YOLO 类别:', class_names, '数量:', num_classes)

    input_shape = (512, 512)
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print('设备:', device)

    if not os.path.exists(args.weights):
        print('[ERROR] 权重不存在: %s' % args.weights)
        sys.exit(1)
    if not os.path.exists(args.clf_weights):
        print('[ERROR] 分类器权重不存在: %s' % args.clf_weights)
        sys.exit(1)

    video_path = args.video
    if not os.path.exists(video_path):
        print('[ERROR] 视频不存在: %s' % video_path)
        sys.exit(1)

    # 加载模型
    yolo = load_model(args.weights, num_classes, args.phi, input_shape, device)
    decodebox = DecodeBox(num_classes=num_classes, input_shape=input_shape)
    classifier = load_classifier(args.clf_weights, device)
    print('YOLO 模型加载完成:', args.weights)
    print('TinyConv 分类器加载完成:', args.clf_weights)

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
    out_path = outdir / ('det_A_' + Path(args.video).stem + '.mp4')
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    writer = cv2.VideoWriter(str(out_path), fourcc, fps, (W, H))
    print('输出视频:', out_path)

    # 闪烁跟踪器
    tracker = AFlashTracker()

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

            # YOLO 推理
            image_pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            dets = detect_one(yolo, decodebox, num_classes, input_shape,
                              image_pil, device, args.conf, args.nms)

            # 对非 area 的 ROI 做 H/L 分类
            area_cid = class_names.index('A_area') if 'A_area' in class_names else -1
            rois = []
            roi_indices = []
            for i, d in enumerate(dets):
                x1, y1, x2, y2, _, cid = d
                if cid != area_cid:
                    x1i, y1i = max(0, int(x1)), max(0, int(y1))
                    x2i, y2i = min(W, int(x2)), min(H, int(y2))
                    if x2i > x1i and y2i > y1i:
                        rois.append(frame[y1i:y2i, x1i:x2i])
                        roi_indices.append(i)
            hl_labels = [''] * len(dets)
            if rois:
                results = classify_rois(rois, classifier, device)
                for ri, hl in zip(roi_indices, results):
                    hl_labels[ri] = hl

            # 闪烁跟踪器 (使用分类后的结果)
            tracker.update(frame_idx, dets, class_names, hl_labels, W)

            # 绘制
            elapsed = time.time() - t0
            cur_fps = frame_idx / elapsed if elapsed > 0 else 0
            draw_on_cvframe(frame, dets, class_names, hl_labels, frame_idx, cur_fps)
            writer.write(frame)

            # 终端打印
            det_summary = {}
            for i, d in enumerate(dets):
                base_cn = class_names[d[5]] if d[5] < len(class_names) else str(d[5])
                hl = hl_labels[i] if i < len(hl_labels) and hl_labels[i] else ''
                cn = '%s_%s' % (base_cn, hl) if hl and base_cn != 'A_area' else base_cn
                det_summary[cn] = det_summary.get(cn, 0) + 1
            print('  frame %4d/%d  fps %.1f  %s' % (frame_idx, total, cur_fps, det_summary), end='\r')

        if not args.no_preview:
            cv2.imshow('A detect (q=quit, space=pause)', frame)
            key = cv2.waitKey(1 if not paused else 0) & 0xFF
            if key == ord('q'):
                print('\n用户中断')
                break
            elif key == 32:
                paused = not paused
                print('\n已暂停' if paused else '继续')

    cap.release()
    writer.release()
    if not args.no_preview:
        cv2.destroyAllWindows()

    elapsed = time.time() - t0
    print()
    print('=' * 60)
    print('完成: 共 %d 帧, 耗时 %.1fs, 平均 %.1f fps' %
          (frame_idx, elapsed, frame_idx / elapsed if elapsed > 0 else 0))
    print('结果视频:', out_path)

    # 生成闪烁折线图 & 打印统计汇总
    chart_path = out_path.with_suffix('.png')
    tracker.generate_chart(str(chart_path), fps)
    tracker.print_summary()


if __name__ == '__main__':
    main()