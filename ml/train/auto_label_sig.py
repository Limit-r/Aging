# -*- coding: utf-8 -*-
"""
用训练好的模型自动标注 A_SIG_H 类到所有未标注图片。

用法:
  conda activate Aging
  python ml/train/auto_label_sig.py

流程:
  1. 扫描 datasets/A/JPEGImages 中的所有图片
  2. 对每张没有对应 XML 标注的图片运行推理
  3. 只保存 A_SIG_H (class_id=5) 的检测结果
  4. 生成 Pascal VOC 格式的 XML 标注文件
"""
import os
import sys
import xml.etree.ElementTree as ET
from xml.dom import minidom
from pathlib import Path

import cv2
import numpy as np
import torch
from PIL import Image

# 模型/训练代码根 = ml/  (auto_label_sig.py -> train -> ml)
ML_ROOT = Path(__file__).resolve().parents[2]
if str(ML_ROOT) not in sys.path:
    sys.path.insert(0, str(ML_ROOT))

from model.YOLOV8 import YoloBody
from utils.utils_bbox import DecodeBox

# ===== 配置 =====
A_SIG_CLASS_ID = 5          # A_SIG_H 在 label.txt 中的索引
CONF_THRES = 0.15           # 低阈值以捕获更多候选
NMS_THRES = 0.45
INPUT_SHAPE = (512, 512)
DEVICE = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

DATASET_DIR = str(ML_ROOT / 'datasets' / 'A')
JPEG_DIR = os.path.join(DATASET_DIR, 'JPEGImages')
ANNO_DIR = os.path.join(DATASET_DIR, 'Annotations')
WEIGHTS = str(ML_ROOT / 'weights' / 'A' / 'model_best_precision_deploy.pt')
CLASSES_PATH = os.path.join(DATASET_DIR, 'label.txt')
PHI = 'n'


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


def detect_one(yolo, decodebox, num_classes, input_shape, image_pil, device,
               conf_thres, nms_thres):
    """对单张图片进行推理"""
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


def create_xml(filename, img_path, width, height, depth, objects):
    """
    创建 Pascal VOC XML 标注文件
    objects: list of (xmin, ymin, xmax, ymax, class_name)
    """
    annotation = ET.Element('annotation')

    folder = ET.SubElement(annotation, 'folder')
    folder.text = 'JPEGImages'

    fn = ET.SubElement(annotation, 'filename')
    fn.text = filename

    path = ET.SubElement(annotation, 'path')
    path.text = img_path

    source = ET.SubElement(annotation, 'source')
    database = ET.SubElement(source, 'database')
    database.text = 'AutoLabel_SIG'

    size = ET.SubElement(annotation, 'size')
    w = ET.SubElement(size, 'width')
    w.text = str(width)
    h = ET.SubElement(size, 'height')
    h.text = str(height)
    d = ET.SubElement(size, 'depth')
    d.text = str(depth)

    segmented = ET.SubElement(annotation, 'segmented')
    segmented.text = '0'

    for xmin, ymin, xmax, ymax, cls_name in objects:
        obj = ET.SubElement(annotation, 'object')
        name = ET.SubElement(obj, 'name')
        name.text = cls_name
        pose = ET.SubElement(obj, 'pose')
        pose.text = 'Unspecified'
        truncated = ET.SubElement(obj, 'truncated')
        truncated.text = '0'
        difficult = ET.SubElement(obj, 'difficult')
        difficult.text = '0'
        bndbox = ET.SubElement(obj, 'bndbox')
        xmin_e = ET.SubElement(bndbox, 'xmin')
        xmin_e.text = str(int(round(xmin)))
        ymin_e = ET.SubElement(bndbox, 'ymin')
        ymin_e.text = str(int(round(ymin)))
        xmax_e = ET.SubElement(bndbox, 'xmax')
        xmax_e.text = str(int(round(xmax)))
        ymax_e = ET.SubElement(bndbox, 'ymax')
        ymax_e.text = str(int(round(ymax)))

    # 格式化输出
    xml_str = minidom.parseString(ET.tostring(annotation)).toprettyxml(indent='\t')
    return xml_str


def main():
    print('=' * 60)
    print('A_SIG_H 自动标注工具')
    print('  模型: %s' % WEIGHTS)
    print('  设备: %s' % DEVICE)
    print('  置信度阈值: %.2f' % CONF_THRES)
    print('  图片目录: %s' % JPEG_DIR)
    print('  标注输出: %s' % ANNO_DIR)
    print('=' * 60)

    # 读取类别
    with open(CLASSES_PATH, 'r') as f:
        class_names = [l.strip() for l in f if l.strip()]
    num_classes = len(class_names)
    print('类别表 (%d): %s' % (num_classes, class_names))

    # 加载模型
    print('加载模型中...')
    yolo = load_model(WEIGHTS, num_classes, PHI, INPUT_SHAPE, DEVICE)
    decodebox = DecodeBox(num_classes=num_classes, input_shape=INPUT_SHAPE)
    print('模型加载完成')

    # 扫描已标注的图片（有 XML 的）
    annotated_set = set()
    for fname in os.listdir(ANNO_DIR):
        if fname.endswith('.xml'):
            annotated_set.add(Path(fname).stem)

    # 扫描所有图片
    all_images = sorted([f for f in os.listdir(JPEG_DIR) if f.endswith('.jpg')])
    to_label = [f for f in all_images if Path(f).stem not in annotated_set]
    print('\n图片总数: %d' % len(all_images))
    print('已标注: %d' % len(annotated_set))
    print('待标注: %d' % len(to_label))

    if not to_label:
        print('没有需要标注的图片！')
        return

    # 逐张推理标注
    total_sig_detected = 0
    total_images_with_sig = 0

    for idx, fname in enumerate(to_label):
        img_path = os.path.join(JPEG_DIR, fname)
        stem = Path(fname).stem
        xml_path = os.path.join(ANNO_DIR, stem + '.xml')

        # 读取图片
        image = Image.open(img_path).convert('RGB')
        width, height = image.size

        # 推理
        dets = detect_one(yolo, decodebox, num_classes, INPUT_SHAPE,
                          image, DEVICE, CONF_THRES, NMS_THRES)

        # 只保留 A_SIG_H 检测结果
        sig_dets = [d for d in dets if d[5] == A_SIG_CLASS_ID]

        if sig_dets:
            objects = []
            for d in sig_dets:
                x1, y1, x2, y2, score, cid = d
                objects.append((x1, y1, x2, y2, class_names[cid]))
                total_sig_detected += 1

            xml_str = create_xml(fname, img_path, width, height, 3, objects)
            with open(xml_path, 'w', encoding='utf-8') as f:
                f.write(xml_str)
            total_images_with_sig += 1

            if (idx + 1) % 10 == 0 or idx == len(to_label) - 1:
                print('  [%d/%d] %s → %d 个 A_SIG_H 标注' %
                      (idx + 1, len(to_label), fname, len(sig_dets)))
        else:
            if (idx + 1) % 20 == 0 or idx == len(to_label) - 1:
                print('  [%d/%d] %s → 无 A_SIG_H 检测结果' %
                      (idx + 1, len(to_label), fname))

    print('\n' + '=' * 60)
    print('标注完成！')
    print('  检测到 A_SIG_H 的图片: %d / %d' % (total_images_with_sig, len(to_label)))
    print('  共标注 A_SIG_H 框: %d 个' % total_sig_detected)
    print('  标注文件保存到: %s' % ANNO_DIR)
    print('=' * 60)


if __name__ == '__main__':
    main()