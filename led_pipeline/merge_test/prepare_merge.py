# -*- coding: utf-8 -*-
"""
合并 FP + A 系列数据集准备脚本。

生成:
  merge_test/label_merge.txt         — 9 类合并标签
  merge_test/2025_train_merge.txt    — YOLO 训练集
  merge_test/2025_val_merge.txt      — YOLO 验证集
  merge_test/2025_test_merge.txt     — YOLO 测试集
  merge_test/clf_data/               — 合并分类器数据集

用法:
  python led_pipeline/merge_test/prepare_merge.py
"""
import argparse
import os
import random
import shutil
from pathlib import Path
import xml.etree.ElementTree as ET

import cv2

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MERGE_DIR = PROJECT_ROOT / 'merge_test'
CLF_DIR = MERGE_DIR / 'clf_data'

# === 合并类别表 (9 类) ===
# FP 系列 5 类 (0-4) + A 系列 4 类 (5-8)
COMBINED_CLASSES = [
    'FP_SIG_area',   # 0
    'FP_PWR_area',   # 1
    'FP_VPL',        # 2
    'FP_CPL',        # 3
    'FP_PWR',        # 4
    'A_CLIP',        # 5
    'A_PROT',        # 6
    'A_PWR',         # 7
    'A_area',        # 8
]

# FP 系列: 5 类标注名 → 合并 class_id
FP_CLASS_MAP = {cn: idx for idx, cn in enumerate(COMBINED_CLASSES[:5])}
# 模糊数据标注使用带 _L/_H 后缀的原始 7 类命名, 需映射回基础类别
FP_CLASS_MAP.update({
    'FP_VPL_L': FP_CLASS_MAP['FP_VPL'], 'FP_VPL_H': FP_CLASS_MAP['FP_VPL'],
    'FP_CPL_L': FP_CLASS_MAP['FP_CPL'], 'FP_CPL_H': FP_CLASS_MAP['FP_CPL'],
    'FP_PWR_L': FP_CLASS_MAP['FP_PWR'], 'FP_PWR_H': FP_CLASS_MAP['FP_PWR'],
})
# A 系列: 4 类标注名 → 合并 class_id
A_CLASS_MAP = {cn: idx for idx, cn in enumerate(COMBINED_CLASSES[5:], start=5)}


def parse_xml_boxes(xml_path, class_map):
    """解析 XML, 返回 [(x1,y1,x2,y2,cls_id), ...]"""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    objs = []
    for obj in root.iter('object'):
        try:
            difficult = obj.find('difficult').text if obj.find('difficult') is not None else 0
            difficult = int(difficult)
        except (TypeError, ValueError):
            difficult = 0
        cls = obj.find('name').text
        if cls not in class_map or difficult == 1:
            continue
        cls_id = class_map[cls]
        bb = obj.find('bndbox')
        x1 = int(float(bb.find('xmin').text))
        y1 = int(float(bb.find('ymin').text))
        x2 = int(float(bb.find('xmax').text))
        y2 = int(float(bb.find('ymax').text))
        objs.append((x1, y1, x2, y2, cls_id))
    return objs


def collect_series(series_name, annot_subdir, class_map, split_files, keep_func=None):
    """
    收集一个系列的全部标注数据。

    Parameters
    ----------
    series_name : str  'FP' 或 'A'
    annot_subdir : str  Annotations 子目录名 (如 'Annotations_5class' 或 'Annotations')
    class_map : dict  系列内类别名 → 合并 class_id
    split_files : dict  {'train': set, 'val': set, 'test': set}  (可选, 用于约束)
    keep_func : callable 或 None  对 xml_path 返回 True 才保留 (用于清洗数据)

    Returns
    -------
    list  [(img_path, boxes_str, split), ...]
    """
    dataset_dir = PROJECT_ROOT / 'datasets' / series_name
    annot_dir = dataset_dir / annot_subdir
    img_dir = dataset_dir / 'JPEGImages'

    results = []
    for xml_path in sorted(annot_dir.glob('*.xml')):
        if keep_func is not None and not keep_func(xml_path):
            continue
        img_id = xml_path.stem
        img_path = str(img_dir / f'{img_id}.jpg')

        boxes = parse_xml_boxes(xml_path, class_map)
        if not boxes:
            continue

        # 确定所属 split
        # 如果有 split_files 约束, 则按原系列的划分
        # 否则随机分配 (初次生成时)
        boxes_str = ' '.join('%d,%d,%d,%d,%d' % b for b in boxes)
        results.append((img_path, boxes_str))

    print(f'  {series_name}: {len(results)} 张图片')
    return results


def write_split_txt(data, split_name, out_dir):
    """写入 split txt 文件。"""
    out_path = out_dir / f'2025_{split_name}_merge.txt'
    with open(out_path, 'w', encoding='utf-8') as f:
        for img_path, boxes_str in data:
            f.write(f'{img_path} {boxes_str}\n')
    box_count = sum(len(b.split(',')) // 5 for _, b in data)
    print(f'  {split_name}: {len(data)} 张图, {box_count} 个框 → {out_path.name}')
    return len(data)


def collect_clf_rois(src_clf_dir, series_prefix, split_names=('train', 'val', 'test')):
    """
    从已有分类器数据集复制 ROI 到合并目录。

    Parameters
    ----------
    src_clf_dir : Path  源分类器数据目录 (如 classifier/data 或 classifier/data_a)
    series_prefix : str  系列前缀, 附加到文件名避免冲突
    """
    total = 0
    for split in split_names:
        for label in ('L', 'H'):
            src_dir = src_clf_dir / split / label
            if not src_dir.exists():
                continue
            dst_dir = CLF_DIR / split / label
            dst_dir.mkdir(parents=True, exist_ok=True)
            count = 0
            for fname in sorted(src_dir.iterdir()):
                if fname.suffix.lower() in ('.png', '.jpg', '.jpeg'):
                    new_name = f'{series_prefix}_{fname.name}'
                    shutil.copy2(str(fname), str(dst_dir / new_name))
                    count += 1
            total += count
            if count > 0:
                print(f'    {split}/{label}: {count} 张')
    return total


def main():
    parser = argparse.ArgumentParser(description='合并 FP + A 数据集')
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--ratio', nargs=3, type=float, default=[0.7, 0.2, 0.1])
    args = parser.parse_args()

    MERGE_DIR.mkdir(parents=True, exist_ok=True)

    # 1. 写入合并标签文件
    label_path = MERGE_DIR / 'label_merge.txt'
    with open(label_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(COMBINED_CLASSES) + '\n')
    print(f'标签文件: {label_path} ({len(COMBINED_CLASSES)} 类)')

    # 2. 收集两个系列的数据
    print('收集标注数据...')
    # 注意: 带 _H/_L 后缀的标注已通过 FP_CLASS_MAP 归一化到基础类别 (如 CPL_H/CPL_L → CPL),
    # H/L 仅用于后续二分类 ROI 训练, 不参与 YOLO 类别区分。
    fp_data = collect_series('FP', 'Annotations', FP_CLASS_MAP, None)
    a_data = collect_series('A', 'Annotations_5class', A_CLASS_MAP, None)

    all_data = fp_data + a_data
    print(f'总计: {len(all_data)} 张图片')

    # 3. 随机划分
    r_train, r_val, r_test = args.ratio
    s = r_train + r_val + r_test
    r_train, r_val, r_test = r_train / s, r_val / s, r_test / s

    rng = random.Random(args.seed)
    shuffled = all_data[:]
    rng.shuffle(shuffled)

    n = len(shuffled)
    n_train = int(round(n * r_train))
    n_val = int(round(n * r_val))
    n_test = n - n_train - n_val
    if n_test < 0:
        n_train += n_test
        n_test = 0

    train_data = shuffled[:n_train]
    val_data = shuffled[n_train:n_train + n_val]
    test_data = shuffled[n_train + n_val:]

    print(f'\n划分 (seed={args.seed}): train={len(train_data)}  val={len(val_data)}  test={len(test_data)}')

    write_split_txt(train_data, 'train', MERGE_DIR)
    write_split_txt(val_data, 'val', MERGE_DIR)
    write_split_txt(test_data, 'test', MERGE_DIR)

    # 4. 合并分类器数据
    print('\n合并分类器数据集...')
    # 从 FP 的 classifier/data/ 复制
    fp_clf = PROJECT_ROOT / 'classifier' / 'data'
    if fp_clf.exists():
        print('  FP 分类器数据:')
        collect_clf_rois(fp_clf, 'FP')
    # 从 A 的 classifier/data_a/ 复制
    a_clf = PROJECT_ROOT / 'classifier' / 'data_a'
    if a_clf.exists():
        print('  A 分类器数据:')
        collect_clf_rois(a_clf, 'A')

    # 统计合并后的分类器数据
    print('\n合并分类器数据统计:')
    total_l = 0
    total_h = 0
    for split in ('train', 'val', 'test'):
        for label in ('L', 'H'):
            d = CLF_DIR / split / label
            if d.exists():
                cnt = len(list(d.glob('*.png')))
                print(f'  {split}/{label}: {cnt}')
                if label == 'L':
                    total_l += cnt
                else:
                    total_h += cnt
    print(f'  总计: L={total_l}, H={total_h}, 合计={total_l+total_h}')

    print('\n完成! 合并数据集已准备好:')
    print(f'  标签: {label_path}')
    print(f'  训练: {MERGE_DIR / "2025_train_merge.txt"}')
    print(f'  验证: {MERGE_DIR / "2025_val_merge.txt"}')
    print(f'  测试: {MERGE_DIR / "2025_test_merge.txt"}')
    print(f'  分类器: {CLF_DIR}')


if __name__ == '__main__':
    main()