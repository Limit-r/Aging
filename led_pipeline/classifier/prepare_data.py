"""
从 7 类标注数据中裁剪 LED ROI，生成二分类数据集（L/H）。

标注方案说明:
  使用 labelImg 标注时保持 7 类（FP_SIG_area / FP_PWR_area / FP_VPL_L / FP_VPL_H / FP_CPL_L / FP_CPL_H / FP_PWR_L / FP_PWR_H），
  二分类数据集直接从 7 类标注中提取 H/L 标签，无需亮度阈值等启发式方法。

  对于 YOLO 训练，通过 gen_5class_xmls.py 将 7 类标注映射为 5 类 XML 副本。

用法:
    python led_pipeline/classifier/prepare_data.py

输出:
    led_pipeline/classifier/data/
        train/L/   - 灭灯 ROI (FP_VPL_L, FP_CPL_L, FP_PWR_L)
        train/H/   - 亮灯 ROI (FP_VPL_H, FP_PWR_H)
        val/L/
        val/H/
        test/L/
        test/H/
"""
import os
import sys
from pathlib import Path

import cv2
import numpy as np
from xml.etree import ElementTree as ET

# 路径配置
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATASET_DIR = PROJECT_ROOT / 'datasets' / 'FP'
ANNOT_DIR = DATASET_DIR / 'Annotations'
IMAGE_DIR = DATASET_DIR / 'JPEGImages'
SPLIT_DIR = DATASET_DIR

OUTPUT_DIR = PROJECT_ROOT / 'classifier' / 'data'

# 类别映射: 从 7 类标注名到 L/H 标签
L_CLASSES = {'FP_VPL_L', 'FP_CPL_L', 'FP_PWR_L'}
H_CLASSES = {'FP_VPL_H', 'FP_PWR_H'}
# 注意: CPL_H 在原始数据中极少出现，若未来有标注需要添加
# H_CLASSES = {'FP_VPL_H', 'FP_CPL_H', 'FP_PWR_H'}


def parse_xml(xml_path):
    """解析 VOC XML, 返回 [(class_name, x1, y1, x2, y2), ...]"""
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
    # 创建输出目录
    for split in ('train', 'val', 'test'):
        for label in ('L', 'H'):
            (OUTPUT_DIR / split / label).mkdir(parents=True, exist_ok=True)

    # 读取各 split 的文件列表
    split_files = {}
    for split in ('train', 'val', 'test'):
        txt_path = SPLIT_DIR / f'2025_{split}.txt'
        if not txt_path.exists():
            print(f'[WARN] 未找到 {txt_path}, 跳过')
            continue
        with open(txt_path, 'r') as f:
            lines = f.readlines()
        # 提取文件名 (不含扩展名)
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

    # 遍历所有 XML 标注
    xml_files = sorted(ANNOT_DIR.glob('*.xml'))
    for xml_path in xml_files:
        fname = xml_path.stem

        # 确定属于哪个 split
        split = None
        for s in ('train', 'val', 'test'):
            if fname in split_files.get(s, set()):
                split = s
                break
        if split is None:
            continue  # 不在任何 split 中

        # 读取对应图片
        img_path = IMAGE_DIR / f'{fname}.jpg'
        img = cv2.imread(str(img_path))
        if img is None:
            print(f'[WARN] 无法读取图片: {img_path}')
            continue

        # 解析标注
        objs = parse_xml(xml_path)

        for name, x1, y1, x2, y2 in objs:
            if name in L_CLASSES:
                label = 'L'
            elif name in H_CLASSES:
                label = 'H'
            else:
                continue  # 跳过 FP_SIG_area, FP_PWR_area

            # 裁剪 ROI (确保不越界)
            h, w = img.shape[:2]
            x1 = max(0, x1)
            y1 = max(0, y1)
            x2 = min(w, x2)
            y2 = min(h, y2)
            if x2 <= x1 or y2 <= y1:
                continue

            roi = img[y1:y2, x1:x2]

            # 保存
            out_dir = OUTPUT_DIR / split / label
            out_path = out_dir / f'{fname}_{x1}_{y1}_{x2}_{y2}.png'
            cv2.imwrite(str(out_path), roi)
            counts[split][label] += 1

    # 打印汇总
    print()
    print('=' * 60)
    print('ROI 数据集生成完成')
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