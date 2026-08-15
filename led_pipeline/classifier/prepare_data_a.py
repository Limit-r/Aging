# -*- coding: utf-8 -*-
"""
从 A 系列 7 类标注数据中裁剪 LED ROI，生成二分类数据集（L/H）。

用法:
    python led_pipeline/classifier/prepare_data_a.py

输出:
    led_pipeline/classifier/data_a/
        train/L/   - 灭灯 ROI (A_CLIP_L, A_PROT_L, A_PWR_L)
        train/H/   - 亮灯 ROI (A_CLIP_H, A_PROT_H, A_PWR_H)
        val/L/
        val/H/
        test/L/
        test/H/
"""
import os
from pathlib import Path

import cv2
from xml.etree import ElementTree as ET

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATASET_DIR = PROJECT_ROOT / 'datasets' / 'A'
ANNOT_DIR = DATASET_DIR / 'Annotations'
IMAGE_DIR = DATASET_DIR / 'JPEGImages'
SPLIT_DIR = DATASET_DIR

OUTPUT_DIR = PROJECT_ROOT / 'classifier' / 'data_a'

L_CLASSES = {'A_CLIP_L', 'A_PROT_L', 'A_PWR_L'}
H_CLASSES = {'A_CLIP_H', 'A_PROT_H', 'A_PWR_H'}


def parse_xml(xml_path):
    tree = ET.parse(xml_path)
    root = tree.getroot()
    objs = []
    for obj in root.findall('object'):
        name = obj.find('name').text
        bbox = obj.find('bndbox')
        x1 = int(float(bbox.find('xmin').text))
        y1 = int(float(bbox.find('ymin').text))
        x2 = int(float(bbox.find('xmax').text))
        y2 = int(float(bbox.find('ymax').text))
        objs.append((name, x1, y1, x2, y2))
    return objs


def main():
    for split in ('train', 'val', 'test'):
        for label in ('L', 'H'):
            (OUTPUT_DIR / split / label).mkdir(parents=True, exist_ok=True)

    split_files = {}
    for split in ('train', 'val', 'test'):
        txt_path = SPLIT_DIR / f'2025_{split}.txt'
        if not txt_path.exists():
            print(f'[WARN] 未找到 {txt_path}, 跳过')
            continue
        with open(txt_path, 'r') as f:
            lines = f.readlines()
        names = set()
        for line in lines:
            parts = line.strip().split()
            if parts:
                fname = Path(parts[0]).stem
                names.add(fname)
        split_files[split] = names
        print(f'  {split}: {len(names)} 张图片')

    total_l = 0
    total_h = 0
    counts = {'train': {'L': 0, 'H': 0}, 'val': {'L': 0, 'H': 0}, 'test': {'L': 0, 'H': 0}}

    xml_files = sorted(ANNOT_DIR.glob('*.xml'))
    for xml_path in xml_files:
        fname = xml_path.stem

        split = None
        for s in ('train', 'val', 'test'):
            if fname in split_files.get(s, set()):
                split = s
                break
        if split is None:
            continue

        img_path = IMAGE_DIR / f'{fname}.jpg'
        img = cv2.imread(str(img_path))
        if img is None:
            print(f'[WARN] 无法读取图片: {img_path}')
            continue

        objs = parse_xml(xml_path)
        for name, x1, y1, x2, y2 in objs:
            if name in L_CLASSES:
                label = 'L'
            elif name in H_CLASSES:
                label = 'H'
            else:
                continue  # 跳过 A_area

            h, w = img.shape[:2]
            x1 = max(0, x1)
            y1 = max(0, y1)
            x2 = min(w, x2)
            y2 = min(h, y2)
            if x2 <= x1 or y2 <= y1:
                continue

            roi = img[y1:y2, x1:x2]
            out_dir = OUTPUT_DIR / split / label
            out_path = out_dir / f'{fname}_{x1}_{y1}_{x2}_{y2}.png'
            cv2.imwrite(str(out_path), roi)
            counts[split][label] += 1

    print()
    print('=' * 60)
    print('A 系列 ROI 数据集生成完成')
    print('=' * 60)
    for split in ('train', 'val', 'test'):
        lc = counts[split]['L']
        hc = counts[split]['H']
        print(f'  {split}: L={lc}, H={hc}, 总计={lc+hc}')
        total_l += lc
        total_h += hc
    print(f'  ---')
    print(f'  总计: L={total_l}, H={total_h}, 合计={total_l+total_h}')
    print(f'  L:H 比例 = {total_l/max(total_h,1):.1f}:1')
    print('=' * 60)


if __name__ == '__main__':
    main()