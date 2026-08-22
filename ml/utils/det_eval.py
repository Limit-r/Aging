# -*- coding: utf-8 -*-
"""
YOLO 推理评估公共函数模块

被 detect/infer_fp.py, detect/infer_a.py 复用, 消除多处重复的
load_model / parse_val_line / iou_xyxy /
detect_one / draw_boxes / run_val 逻辑。

用法 (在 cwd=项目根、且 sys.path 含 ml/ 的环境下):
    from utils.det_eval import (load_model, parse_val_line, iou_xyxy,
                                detect_one, draw_boxes, run_val, run_image)

职责拆分:
    - 模型/检测/绘图/指标 = 公共函数 (本就是 ML 库级能力)
    - 权重/数据集路径 & argparse = 各推理脚本自己声明
"""

import os
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageDraw, ImageFont

from model.YOLOV8 import YoloBody
from utils.utils_bbox import DecodeBox


# ============================================================
# 模型加载
# ============================================================
def load_model(weights, num_classes, phi, input_shape, device):
    """加载 YOLOV8 权重, 兼容 deploy 格式 (dict 含 'model') 与纯 state_dict。"""
    yolo = YoloBody(input_shape, num_classes, phi, pretrained=False)
    state = torch.load(weights, map_location=device, weights_only=False)
    if isinstance(state, dict) and 'model' in state:
        yolo.load_state_dict(state['model'])
    else:
        yolo.load_state_dict(state)
    yolo = yolo.to(device).eval()
    return yolo


# ============================================================
# 标注 txt 解析
# ============================================================
def parse_val_line(line, base_dir=None):
    """解析一行: img_path x1,y1,x2,y2,cls_id ... ; 相对路径可用 base_dir 补齐。"""
    line = line.strip()
    if not line:
        return None, []
    parts = line.split(' ')
    img_path = parts[0]
    if base_dir and not os.path.isabs(img_path):
        img_path = os.path.join(base_dir, img_path)
    gts = []
    for p in parts[1:]:
        x1, y1, x2, y2, cid = p.split(',')
        gts.append((int(x1), int(y1), int(x2), int(y2), int(cid)))
    return img_path, gts


# ============================================================
# IoU
# ============================================================
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


# ============================================================
# 单图检测
# ============================================================
def detect_one(yolo, decodebox, num_classes, input_shape, image_pil,
               device, conf_thres, nms_thres):
    """对单张 PIL 图像推理, 返回 [(x1,y1,x2,y2,score,cls_id), ...] (原图坐标)。"""
    iw, ih = image_pil.size
    image_shape = np.array([ih, iw])

    scale = min(input_shape[0] / ih, input_shape[1] / iw)
    nw, nh = int(iw * scale), int(ih * scale)
    resized = image_pil.resize((nw, nh), Image.BICUBIC)
    canvas = Image.new('RGB', input_shape, (128, 128, 128))
    canvas.paste(resized, ((input_shape[1] - nw) // 2, (input_shape[0] - nh) // 2))
    arr = np.array(canvas, dtype='float32') / 255.0
    arr = np.transpose(arr, (2, 0, 1))[None]  # 1x3xHxW
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
        # yolo_correct_boxes 内部 box_mins/box_maxes 走 (y, x) 顺序,
        # 末尾拼接顺序为 (y1, x1, y2, x2), 这里按该顺序解包, 否则 x/y 轴互换 (历史踩坑)
        y1, x1, y2, x2 = top_boxes[i]
        out.append((float(x1), float(y1), float(x2), float(y2),
                    float(top_conf[i]), int(top_label[i])))
    return out


# ============================================================
# 可视化
# ============================================================
def draw_boxes(image_pil, dets, gts, class_names, save_path,
               font_path=None, line_width=2, font_size=18):
    """绘制预测框(绿) 和 真值框(红)。"""
    img = image_pil.copy()
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(font_path, size=font_size) if font_path else ImageFont.load_default()
    except Exception:
        font = ImageFont.load_default()
    for (x1, y1, x2, y2, cid) in gts:
        draw.rectangle([x1, y1, x2, y2], outline=(255, 0, 0), width=line_width)
        cname = class_names[cid] if cid < len(class_names) else str(cid)
        draw.text((x1, max(0, y1 - font_size)), 'GT:' + cname, fill=(255, 0, 0), font=font)
    for (x1, y1, x2, y2, score, cid) in dets:
        draw.rectangle([x1, y1, x2, y2], outline=(0, 200, 0), width=line_width)
        cname = class_names[cid] if cid < len(class_names) else str(cid)
        draw.text((x1, min(img.size[1] - font_size, y2)), 'P:%.2f %s' % (score, cname),
                  fill=(0, 200, 0), font=font)
    img.save(save_path)


def resolve_font(ml_root, font_path=None):
    """返回可用字体路径; 无则返回 None (调用方会回退到默认字体)。"""
    if font_path and os.path.exists(font_path):
        return str(font_path)
    candidate = os.path.join(ml_root, 'weights', 'pretrained', 'simhei.ttf')
    return candidate if os.path.exists(candidate) else None


# ============================================================
# 全量集评估 (val/test)
# ============================================================
def run_val(txt_path, outdir, yolo, decodebox, class_names, num_classes,
            input_shape, device, font_path=None,
            conf=0.25, nms=0.45, iou_match=0.5,
            tag='', base_dir=None, save_vis=True, verbose_per_img=True):
    """对 txt 列出的图像全量推理, 打印汇总并有选择地保存可视化。

    返回 summary dict: {split 无关, per_class, total{gt,det,tp,recall,precision,f1}}。
    """
    with open(txt_path, 'r', encoding='utf-8') as f:
        lines = [l for l in f.readlines() if l.strip()]

    gt_total = {n: 0 for n in class_names}
    det_total = {n: 0 for n in class_names}
    tp_total = {n: 0 for n in class_names}

    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    print('=' * 70)
    print('%s 共 %d 张图  conf=%.2f  nms=%.2f  iou>=%.2f' %
          (tag or Path(txt_path).stem, len(lines), conf, nms, iou_match))
    print('=' * 70)

    for line in lines:
        img_path, gts = parse_val_line(line, base_dir)
        if img_path is None or not os.path.exists(img_path):
            print('[WARN] 图片缺失:', img_path)
            continue
        image = Image.open(img_path).convert('RGB')
        dets = detect_one(yolo, decodebox, num_classes, input_shape,
                          image, device, conf, nms)

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
                iou_val = iou_xyxy(d[:4], g[:4])
                if iou_val > best_iou:
                    best_iou, best_idx = iou_val, i
            if best_iou >= iou_match and best_idx >= 0:
                per_tp[gname] += 1
                matched_pred[best_idx] = True
        for d in dets:
            per_det[class_names[d[5]]] += 1

        for n in class_names:
            gt_total[n] += per_gt[n]
            det_total[n] += per_det[n]
            tp_total[n] += per_tp[n]

        if save_vis:
            fname = Path(img_path).stem + '.jpg'
            draw_boxes(image, dets, gts, class_names,
                       str(outdir / ('vis_' + fname)), font_path=font_path)
        if verbose_per_img:
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

    summary = {
        'num_images': len(lines),
        'per_class': {},
        'total': {
            'gt': sum_gt, 'det': sum_det, 'tp': sum_tp,
            'recall': round(r, 4), 'precision': round(p, 4), 'f1': round(f1, 4),
        },
    }
    for n in class_names:
        g, d, t = gt_total[n], det_total[n], tp_total[n]
        summary['per_class'][n] = {
            'gt': g, 'det': d, 'tp': t,
            'recall': round(t / g, 4) if g else 0,
            'precision': round(t / d, 4) if d else 0,
        }
    return summary


# ============================================================
# 单图推理
# ============================================================
def run_image(image_path, outdir, yolo, decodebox, class_names, num_classes,
              input_shape, device, font_path=None,
              conf=0.25, nms=0.45, iou_match=0.5, label=''):
    """单图推理, 保存可视化, 打印检出结果。"""
    image = Image.open(image_path).convert('RGB')
    dets = detect_one(yolo, decodebox, num_classes, input_shape,
                      image, device, conf, nms)
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    save_path = outdir / ('vis_' + os.path.basename(image_path))
    draw_boxes(image, dets, [], class_names, str(save_path),
               font_path=font_path, )
    print('%s检出 %d 个目标:' % ((label + ' ' if label else ''), len(dets)))
    for (x1, y1, x2, y2, score, cid) in dets:
        print('  %s  conf=%.2f  box=(%d,%d,%d,%d)' %
              (class_names[cid] if cid < len(class_names) else str(cid),
               score, int(x1), int(y1), int(x2), int(y2)))
    print('可视化保存到:', save_path)
    return dets