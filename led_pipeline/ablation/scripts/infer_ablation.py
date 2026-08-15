"""
消融实验推理评估 - 支持不同模型/输入尺寸, 输出 JSON 结果

用法:
  python led_pipeline/ablation/scripts/infer_ablation.py \
      --split val --weights path/to/weights.pth \
      --phi n --input_shape 640 640 \
      --model_name YOLOV8 --outdir path/to/output
"""
import argparse
import importlib
import json
import os
import sys
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageDraw, ImageFont

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from utils.utils_bbox import DecodeBox
from utils.utils import get_classes

SPLIT_FILES = {
    'val':  str(PROJECT_ROOT / 'datasets' / 'FP' / '2025_val.txt'),
    'test': str(PROJECT_ROOT / 'datasets' / 'FP' / '2025_test.txt'),
}
DEFAULT_LABELS = str(PROJECT_ROOT / 'datasets' / 'FP' / 'label.txt')


def load_model(weights, num_classes, phi, input_shape, device, model_name):
    module_path = f'model.{model_name}'
    try:
        target_module = importlib.import_module(module_path)
    except ModuleNotFoundError:
        print(f'[ERROR] 无法加载模型: {module_path}')
        sys.exit(1)
    yolo = target_module.YoloBody(input_shape, num_classes, phi, pretrained=False)
    state = torch.load(weights, map_location=device, weights_only=False)
    if isinstance(state, dict) and 'model' in state:
        yolo.load_state_dict(state['model'])
    else:
        yolo.load_state_dict(state)
    return yolo.to(device).eval()


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
    canvas = Image.new('RGB', (input_shape[1], input_shape[0]), (128, 128, 128))
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
        font = ImageFont.truetype(str(PROJECT_ROOT / 'weights' / 'pretrained' / 'simhei.ttf'), size=18)
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


def main():
    parser = argparse.ArgumentParser(description='消融实验推理评估')
    parser.add_argument('--split', choices=['val', 'test'], default='val')
    parser.add_argument('--weights', required=True)
    parser.add_argument('--labels', default=DEFAULT_LABELS)
    parser.add_argument('--outdir', required=True)
    parser.add_argument('--phi', default='n')
    parser.add_argument('--input_shape', nargs=2, type=int, default=[640, 640])
    parser.add_argument('--model_name', default='YOLOV8')
    parser.add_argument('--conf', type=float, default=0.25)
    parser.add_argument('--nms', type=float, default=0.45)
    parser.add_argument('--iou_match', type=float, default=0.5)
    args = parser.parse_args()

    input_shape = tuple(args.input_shape)
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    class_names, num_classes = get_classes(args.labels)

    print(f'[INFO] {args.model_name} phi={args.phi} input={input_shape} split={args.split}')
    print(f'[INFO] 权重: {args.weights}')

    yolo = load_model(args.weights, num_classes, args.phi, input_shape, device, args.model_name)
    decodebox = DecodeBox(num_classes=num_classes, input_shape=input_shape)

    split_txt = SPLIT_FILES[args.split]
    with open(split_txt, encoding='utf-8') as f:
        lines = [l for l in f.readlines() if l.strip()]

    gt_total = {n: 0 for n in class_names}
    det_total = {n: 0 for n in class_names}
    tp_total = {n: 0 for n in class_names}

    outdir = Path(args.outdir) / args.split
    outdir.mkdir(parents=True, exist_ok=True)

    for line in lines:
        img_path, gts = parse_val_line(line)
        if img_path is None or not os.path.exists(img_path):
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
                iou_val = iou_xyxy(d[:4], g[:4])
                if iou_val > best_iou:
                    best_iou, best_idx = iou_val, i
            if best_iou >= args.iou_match and best_idx >= 0:
                per_tp[gname] += 1
                matched_pred[best_idx] = True
        for d in dets:
            per_det[class_names[d[5]]] += 1

        for n in class_names:
            gt_total[n] += per_gt[n]
            det_total[n] += per_det[n]
            tp_total[n] += per_tp[n]

        # 保存可视化
        fname = Path(img_path).stem + '.jpg'
        draw_boxes(image, dets, gts, class_names, str(outdir / ('vis_' + fname)))

    # 汇总
    print(f'{"Class":<15} {"GT":>6} {"Det":>6} {"TP":>6} {"Recall":>8} {"Precision":>8}')
    sum_gt = sum_det = sum_tp = 0
    for n in class_names:
        g, d, t = gt_total[n], det_total[n], tp_total[n]
        sum_gt += g; sum_det += d; sum_tp += t
        r = t / g if g else 0
        p = t / d if d else 0
        print(f'{n:<15} {g:>6} {d:>6} {t:>6} {r:>8.4f} {p:>8.4f}')
    r = sum_tp / sum_gt if sum_gt else 0
    p = sum_tp / sum_det if sum_det else 0
    f1 = 2 * p * r / (p + r) if (p + r) else 0
    print(f'{"TOTAL":<15} {sum_gt:>6} {sum_det:>6} {sum_tp:>6} {r:>8.4f} {p:>8.4f}')
    print(f'F1-Score: {f1:.4f}')

    # 保存 JSON
    summary = {
        'experiment': {
            'model_name': args.model_name,
            'phi': args.phi,
            'input_shape': list(input_shape),
        },
        'split': args.split,
        'num_images': len(lines),
        'per_class': {},
        'total': {
            'gt': sum_gt, 'det': sum_det, 'tp': sum_tp,
            'recall': round(r, 4), 'precision': round(p, 4), 'f1': round(f1, 4),
        }
    }
    for n in class_names:
        g, d, t = gt_total[n], det_total[n], tp_total[n]
        summary['per_class'][n] = {
            'gt': g, 'det': d, 'tp': t,
            'recall': round(t / g, 4) if g else 0,
            'precision': round(t / d, 4) if d else 0,
        }
    summary_path = Path(args.outdir) / f'{args.split}_summary.json'
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f'结果 JSON: {summary_path}')


if __name__ == '__main__':
    main()