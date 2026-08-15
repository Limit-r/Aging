# -*- coding: utf-8 -*-
"""
FP 数据集自动标注预填脚本 (VOC XML 格式)。

对 FP 数据集中「缺 XML 标注」的 JPEG 图, 用已训练好的 YOLO 模型
(FP_v3_5classes_v2) 自动生成初始标注 XML, 再由人工在 LabelImg 中打开
微调删改, 大幅提升标注效率。

输出:
  datasets/FP/Annotations/<img_id>.xml        — VOC 格式标注 (每个 object 带 <confidence>, 便于人工筛选)
  datasets/FP/outputs/auto_label_preview/     — (可选) 带框预览图, 便于快速检查

关键约束 (项目记忆):
  yolo_correct_boxes 内部走 (y, x) 顺序, 末尾拼接为 (y1, x1, y2, x2),
  解包时必须按该顺序, 否则 x/y 轴会互换 (历史采坑)。

用法:
  python led_pipeline/train/auto_label_fp.py
  python led_pipeline/train/auto_label_fp.py --conf 0.15        # 模糊帧可调低阈值
  python led_pipeline/train/auto_label_fp.py --range 000470 000535   # 只处理指定帧号区间
  python led_pipeline/train/auto_label_fp.py --image frame_000536     # 只处理单帧
  python led_pipeline/train/auto_label_fp.py --no-vis           # 不生成预览图
  python led_pipeline/train/auto_label_fp.py --overwrite        # 覆盖已存在的同名单帧 XML
"""
import argparse
import os
import sys
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageDraw

import xml.etree.ElementTree as ET

# 项目根 = led_pipeline
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from model.YOLOV8 import YoloBody
from utils.utils_bbox import DecodeBox
from utils.utils import get_classes

DEFAULT_WEIGHTS = str(PROJECT_ROOT / 'weights' / 'FP_v3_5classes_v4' / 'model_best_precision_deploy.pt')
DEFAULT_LABELS = str(PROJECT_ROOT / 'datasets' / 'FP' / 'label.txt')
FP_DIR = PROJECT_ROOT / 'datasets' / 'FP'
IMG_DIR = FP_DIR / 'JPEGImages'
ANN_DIR = FP_DIR / 'Annotations'
VIS_DIR = FP_DIR / 'outputs' / 'auto_label_preview'


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


def detect_one(yolo, decodebox, num_classes, input_shape, image_pil, device, conf_thres, nms_thres):
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
        # 关键: 按 (y1, x1, y2, x2) 解包, 否则 x/y 轴互换
        y1, x1, y2, x2 = top_boxes[i]
        out.append((float(x1), float(y1), float(x2), float(y2),
                    float(top_conf[i]), int(top_label[i])))
    return out


def clamp_box(x1, y1, x2, y2, w, h):
    """把坐标转成整数并裁剪到图像范围内, 保证 x1<x2, y1<y2。"""
    x1, y1, x2, y2 = int(round(x1)), int(round(y1)), int(round(x2)), int(round(y2))
    x1, y1 = max(0, min(x1, w - 1)), max(0, min(y1, h - 1))
    x2, y2 = max(0, min(x2, w - 1)), max(0, min(y2, h - 1))
    if x1 >= x2:
        x2 = min(w - 1, x1 + 1)
    if y1 >= y2:
        y2 = min(h - 1, y1 + 1)
    return x1, y1, x2, y2


def write_voc_xml(img_path, img_id, dets, class_names, out_path):
    """写出 VOC 格式 XML (每个 object 附带 confidence)。"""
    w, h = Image.open(img_path).size

    root = ET.Element('annotation')
    folder = ET.SubElement(root, 'folder')
    folder.text = 'JPEGImages'
    filename = ET.SubElement(root, 'filename')
    filename.text = img_id + '.jpg'
    path = ET.SubElement(root, 'path')
    path.text = str(img_path)
    source = ET.SubElement(root, 'source')
    db = ET.SubElement(source, 'database')
    db.text = 'Unknown'
    size = ET.SubElement(root, 'size')
    sw, sh, sd = ET.SubElement(size, 'width'), ET.SubElement(size, 'height'), ET.SubElement(size, 'depth')
    sw.text, sh.text, sd.text = str(w), str(h), '3'
    seg = ET.SubElement(root, 'segmented')
    seg.text = '0'

    for (x1, y1, x2, y2, score, cid) in dets:
        x1, y1, x2, y2 = clamp_box(x1, y1, x2, y2, w, h)
        obj = ET.SubElement(root, 'object')
        name = ET.SubElement(obj, 'name')
        name.text = class_names[cid]
        confidence = ET.SubElement(obj, 'confidence')
        confidence.text = '%.3f' % score
        pose = ET.SubElement(obj, 'pose')
        pose.text = 'Unspecified'
        truncated = ET.SubElement(obj, 'truncated')
        truncated.text = '0'
        difficult = ET.SubElement(obj, 'difficult')
        difficult.text = '0'
        bb = ET.SubElement(obj, 'bndbox')
        xmn, ymn, xmx, ymx = ET.SubElement(bb, 'xmin'), ET.SubElement(bb, 'ymin'), \
            ET.SubElement(bb, 'xmax'), ET.SubElement(bb, 'ymax')
        xmn.text, ymn.text, xmx.text, ymx.text = str(x1), str(y1), str(x2), str(y2)

    ET.indent(root, space='\t')
    tree = ET.ElementTree(root)
    ET.indent(tree, space='\t')
    tree.write(out_path, encoding='utf-8', xml_declaration=True)


def save_preview(img_path, dets, class_names, out_path):
    """保存带框预览图 (绿框 + 类别 + 置信度)。"""
    img = Image.open(img_path).convert('RGB').copy()
    draw = ImageDraw.Draw(img)
    for (x1, y1, x2, y2, score, cid) in dets:
        x1, y1, x2, y2 = clamp_box(x1, y1, x2, y2, img.size[0], img.size[1])
        draw.rectangle([x1, y1, x2, y2], outline=(0, 200, 0), width=2)
        draw.text((x1, max(0, y1 - 14)), '%s %.2f' % (class_names[cid], score), fill=(0, 200, 0))
    img.save(out_path)


def collect_missing(only_ids=None, lo=None, hi=None):
    """收集缺 XML 标注的图片 id (按名称排序)。"""
    anns = {os.path.splitext(f)[0] for f in os.listdir(ANN_DIR) if f.endswith('.xml')}
    missing = []
    for f in sorted(os.listdir(IMG_DIR)):
        if not f.endswith('.jpg'):
            continue
        img_id = os.path.splitext(f)[0]
        if img_id in anns:
            continue
        if only_ids and img_id not in only_ids:
            continue
        # 用数字后缀做区间比较 (img_id 形如 frame_000470)
        num = img_id.rsplit('_', 1)[-1]
        if lo is not None and num < lo:
            continue
        if hi is not None and num > hi:
            continue
        missing.append(img_id)
    return missing


def main():
    parser = argparse.ArgumentParser(description='FP 数据集自动标注预填 (生成 VOC XML 供 LabelImg 微调)')
    parser.add_argument('--weights', default=DEFAULT_WEIGHTS)
    parser.add_argument('--labels', default=DEFAULT_LABELS)
    parser.add_argument('--phi', default='n')
    parser.add_argument('--conf', type=float, default=0.25, help='置信度阈值 (模糊帧可调低)')
    parser.add_argument('--nms', type=float, default=0.45)
    parser.add_argument('--range', nargs=2, metavar=('LO', 'HI'), default=None,
                        help='只处理帧号区间, 如 000470 000535')
    parser.add_argument('--image', type=str, default=None, help='只处理单帧图像 id, 如 frame_000536')
    parser.add_argument('--no-vis', action='store_true', help='不生成预览图')
    parser.add_argument('--overwrite', action='store_true', help='覆盖已存在的 XML')
    args = parser.parse_args()

    class_names, num_classes = get_classes(args.labels)
    print('类别:', class_names, '数量:', num_classes)

    if not os.path.exists(args.weights):
        print('[ERROR] 权重不存在: %s' % args.weights)
        print('        请先用 led_pipeline/train/train_fp.py 完成训练。')
        sys.exit(1)

    input_shape = (512, 512)
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print('设备:', device)

    yolo = load_model(args.weights, num_classes, args.phi, input_shape, device)
    decodebox = DecodeBox(num_classes=num_classes, input_shape=input_shape)
    print('模型加载完成:', args.weights)

    only_ids = {args.image} if args.image else None
    lo, hi = args.range if args.range else (None, None)
    missing = collect_missing(only_ids=only_ids, lo=lo, hi=hi)
    if not missing:
        print('没有需要标注的图片 (均已标注或无匹配)。')
        return

    print('待标注 %d 张:' % len(missing))
    for i in missing:
        print('  ', i)

    ANN_DIR.mkdir(parents=True, exist_ok=True)
    if not args.no_vis:
        VIS_DIR.mkdir(parents=True, exist_ok=True)

    n_written = 0
    n_skip = 0
    empty = 0
    for img_id in missing:
        img_path = IMG_DIR / (img_id + '.jpg')
        xml_path = ANN_DIR / (img_id + '.xml')
        if xml_path.exists() and not args.overwrite:
            print('  [SKIP] 已存在 XML: %s' % img_id)
            n_skip += 1
            continue

        image = Image.open(img_path).convert('RGB')
        dets = detect_one(yolo, decodebox, num_classes, input_shape,
                          image, device, args.conf, args.nms)
        write_voc_xml(img_path, img_id, dets, class_names, xml_path)
        if not args.no_vis:
            save_preview(img_path, dets, class_names, VIS_DIR / (img_id + '.jpg'))
        n_written += 1
        if not dets:
            empty += 1
        # 正式输出用自然语言描述, 便于阅读
        print('  [OK] %s  检出 %d 个目标' % (img_id, len(dets)))

    print('=' * 60)
    print('完成! 新写 XML: %d, 跳过: %d, 其中 0 目标(需人工标注): %d' % (n_written, n_skip, empty))
    print('标注目录: %s' % ANN_DIR)
    if not args.no_vis:
        print('预览目录: %s' % VIS_DIR)
    print('提示: 用 LabelImg 打开 JPEGImages 目录, 逐帧核对/微调这些预填框。')


if __name__ == '__main__':
    main()