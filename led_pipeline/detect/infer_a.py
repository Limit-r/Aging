# -*- coding: utf-8 -*-
"""
A 系列推理验证脚本 (7 类: A_CLIP_H / A_CLIP_L / A_PROT_H / A_PROT_L / A_PWR_H / A_SIG_H / A_area)

用法:
  python led_pipeline/detect/infer_a.py
  python led_pipeline/detect/infer_a.py --image path/to/image.jpg
"""
import argparse
import os
import sys
from pathlib import Path

import cv2
import numpy as np
import torch
from PIL import Image, ImageDraw, ImageFont

# 训练框架在 d:\YOLO_train
PROJECT_ROOT = r'd:\YOLO_train'
sys.path.insert(0, PROJECT_ROOT)

from model.YOLOV8 import YoloBody
from utils.utils_bbox import DecodeBox
from utils.utils import get_classes

# A 系列权重路径
A_WEIGHTS = r'd:\Aging\led_pipeline\train\weights\A\best_epoch_weights.pth'
A_DEPLOY  = r'd:\Aging\led_pipeline\train\weights\A\model_best_precision_deploy.pt'
A_LABELS  = r'd:\Aging\led_pipeline\datasets\A\label.txt'
A_OUTDIR  = r'd:\Aging\led_pipeline\detect\outputs\A'
A_VAL_TXT = r'd:\Aging\led_pipeline\datasets\A\2025_val.txt'
A_TEST_TXT = r'd:\Aging\led_pipeline\datasets\A\2025_test.txt'


def load_model(weights, num_classes, phi, input_shape, device):
    """加载 YOLOV8 权重"""
    yolo = YoloBody(input_shape, num_classes, phi, pretrained=False)
    state = torch.load(weights, map_location=device, weights_only=False)
    if isinstance(state, dict) and 'model' in state:
        yolo.load_state_dict(state['model'])
    else:
        yolo.load_state_dict(state)
    yolo = yolo.to(device).eval()
    return yolo


def parse_val_line(line):
    line = line.strip()
    if not line:
        return None, []
    parts = line.split(' ')
    img_path = parts[0]
    gts = []
    for p in parts[1:]:
        x1, y1, x2, y2, cid = p.split(',')
        gts.append((int(x1), int(y1), int(x2), int(y2), int(cid)))
    return img_path, gts


def iou_xyxy(a, b):
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    area_a = (ax2 - ax1) * (ay2 - ay1)
    area_b = (bx2 - bx1) * (by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def detect_one(yolo, decodebox, num_classes, input_shape, image_pil, device, conf_thres, nms_thres):
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


def draw_boxes(image_pil, dets, gts, class_names, save_path):
    img = image_pil.copy()
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(r'd:\YOLO_train\weights\pretrained\simhei.ttf', size=18)
    except Exception:
        font = ImageFont.load_default()
    for (x1, y1, x2, y2, cid) in gts:
        draw.rectangle([x1, y1, x2, y2], outline=(255, 0, 0), width=2)
        cname = class_names[cid] if cid < len(class_names) else str(cid)
        draw.text((x1, max(0, y1 - 18)), 'GT:' + cname, fill=(255, 0, 0), font=font)
    for (x1, y1, x2, y2, score, cid) in dets:
        draw.rectangle([x1, y1, x2, y2], outline=(0, 200, 0), width=2)
        cname = class_names[cid] if cid < len(class_names) else str(cid)
        draw.text((x1, min(img.size[1] - 18, y2)), 'P:%.2f %s' % (score, cname),
                  fill=(0, 200, 0), font=font)
    img.save(save_path)


def run_val(args, yolo, decodebox, class_names, num_classes, input_shape, device):
    split_txt = args.test_txt if args.split == 'test' else args.val_txt
    with open(split_txt, 'r', encoding='utf-8') as f:
        lines = [l for l in f.readlines() if l.strip()]

    gt_total = {n: 0 for n in class_names}
    det_total = {n: 0 for n in class_names}
    tp_total = {n: 0 for n in class_names}

    outdir = Path(args.outdir) / args.split
    outdir.mkdir(parents=True, exist_ok=True)

    print('=' * 70)
    print('A 系列 %s集推理  共 %d 张图  conf=%.2f  nms=%.2f  iou>=%.2f' %
          (args.split, len(lines), args.conf, args.nms, args.iou_match))
    print('=' * 70)

    for line in lines:
        img_path, gts = parse_val_line(line)
        if img_path is None or not os.path.exists(img_path):
            print('[WARN] 图片缺失:', img_path)
            continue
        image = Image.open(img_path).convert('RGB')
        dets = detect_one(yolo, decodebox, num_classes, input_shape,
                          image, device, args.conf, args.nms)

        per_gt = {n: 0 for n in class_names}
        per_det = {n: 0 for n in class_names}
        per_tp = {n: 0 for n in class_names}
        for g in gts:
            per_gt[class_names[g[4]]] += 1
        matched_pred = [False] * len(dets)
        for g in gts:
            gname = class_names[g[4]]
            best_iou, best_idx = 0.0, -1
            for i, d in enumerate(dets):
                if matched_pred[i] or d[5] != g[4]:
                    continue
                iou = iou_xyxy(d[:4], g[:4])
                if iou > best_iou:
                    best_iou, best_idx = iou, i
            if best_iou >= args.iou_match and best_idx >= 0:
                per_tp[gname] += 1
                matched_pred[best_idx] = True
        for d in dets:
            per_det[class_names[d[5]]] += 1

        for n in class_names:
            gt_total[n] += per_gt[n]
            det_total[n] += per_det[n]
            tp_total[n] += per_tp[n]

        fname = Path(img_path).stem + '.jpg'
        save_path = outdir / ('vis_' + fname)
        draw_boxes(image, dets, gts, class_names, str(save_path))

        print('  %s  GT=%s  DET=%s  TP=%s' %
              (Path(img_path).name, per_gt, per_det, per_tp))

    print('=' * 70)
    print('全局汇总:')
    print('%-15s %6s %6s %6s %8s %8s' % ('Class', 'GT', 'Det', 'TP', 'Recall', 'Precision'))
    sum_gt = sum_det = sum_tp = 0
    for n in class_names:
        g, d, t = gt_total[n], det_total[n], tp_total[n]
        sum_gt += g; sum_det += d; sum_tp += t
        r = t / g if g else 0
        p = t / d if d else 0
        print('%-15s %6d %6d %6d %8.2f %8.2f' % (n, g, d, t, r, p))
    r = sum_tp / sum_gt if sum_gt else 0
    p = sum_tp / sum_det if sum_det else 0
    f1 = 2 * p * r / (p + r) if (p + r) else 0
    print('%-15s %6d %6d %6d %8.2f %8.2f' % ('TOTAL', sum_gt, sum_det, sum_tp, r, p))
    print('F1-Score: %.4f' % f1)
    print('可视化结果保存到: %s' % outdir)


def run_image(args, yolo, decodebox, class_names, num_classes, input_shape, device):
    image = Image.open(args.image).convert('RGB')
    dets = detect_one(yolo, decodebox, num_classes, input_shape,
                      image, device, args.conf, args.nms)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    save_path = outdir / ('vis_' + Path(args.image).name)
    draw_boxes(image, dets, [], class_names, str(save_path))
    print('检出 %d 个目标:' % len(dets))
    for (x1, y1, x2, y2, score, cid) in dets:
        print('  %s  conf=%.2f  box=(%d,%d,%d,%d)' %
              (class_names[cid] if cid < len(class_names) else str(cid),
               score, int(x1), int(y1), int(x2), int(y2)))
    print('可视化保存到:', save_path)


def main():
    parser = argparse.ArgumentParser(description='A 系列推理验证')
    parser.add_argument('--image', type=str, default=None, help='单图推理路径')
    parser.add_argument('--split', choices=['val', 'test'], default='val')
    parser.add_argument('--weights', default=A_WEIGHTS)
    parser.add_argument('--deploy', default=A_DEPLOY)
    parser.add_argument('--labels', default=A_LABELS)
    parser.add_argument('--outdir', default=A_OUTDIR)
    parser.add_argument('--val_txt', default=A_VAL_TXT)
    parser.add_argument('--test_txt', default=A_TEST_TXT)
    parser.add_argument('--phi', default='n')
    parser.add_argument('--conf', type=float, default=0.25)
    parser.add_argument('--nms', type=float, default=0.45)
    parser.add_argument('--iou_match', type=float, default=0.5)
    args = parser.parse_args()

    class_names, num_classes = get_classes(args.labels)
    print('类别:', class_names, '数量:', num_classes)

    input_shape = (512, 512)
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print('设备:', device)

    # 优先用 deploy 模型
    weights_path = args.deploy if os.path.exists(args.deploy) else args.weights
    if not os.path.exists(weights_path):
        print('[ERROR] 权重不存在: %s' % weights_path)
        print('        请先完成训练。')
        sys.exit(1)

    yolo = load_model(weights_path, num_classes, args.phi, input_shape, device)
    decodebox = DecodeBox(num_classes=num_classes, input_shape=input_shape)
    print('模型加载完成:', weights_path)

    if args.image:
        run_image(args, yolo, decodebox, class_names, num_classes, input_shape, device)
    else:
        run_val(args, yolo, decodebox, class_names, num_classes, input_shape, device)


if __name__ == '__main__':
    main()