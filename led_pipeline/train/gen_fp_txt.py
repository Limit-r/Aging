# -*- coding: utf-8 -*-
"""
FP 数据集的 2025_train.txt / 2025_val.txt / 2025_test.txt (7:2:1 三分)

策略:
  扫描 Annotations/*.xml, 收集全部有标注的图片 id, 固定 seed=42 shuffle 后
  按 7:2:1 划分到 train / val / test, 覆盖写入三个 txt。
  每次新增标注后重新运行即可, 划分可复现 (同 seed + 同图片集合 => 同结果)。

注意:
  2026-08-06: XML 标注已从 7 类名更新为 5 类名
  (VPL_L/VPL_H→FP_VPL, CPL_L→FP_CPL, PWR_H/PWR_L→FP_PWR)。
  2026-08-07: 所有类别名添加 FP_ 前缀以区分面板系列。

用法:
  python led_pipeline/train/gen_fp_txt.py
  python led_pipeline/train/gen_fp_txt.py --seed 42
  python led_pipeline/train/gen_fp_txt.py --ratio 0.7 0.2 0.1
"""
import argparse
import os
import random
import xml.etree.ElementTree as ET

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FP_DIR = os.path.join(PROJECT_ROOT, 'datasets', 'FP')
CLASSES_PATH = os.path.join(FP_DIR, 'label.txt')
# 2026-08-12: 划分必须基于 5 类合并副本 (Annotations_5class), 原因:
#   原始 Annotations/ 含 7 类名 (VPL_L/VPL_H/CPL_L/PWR_L/PWR_H),
#   而 label.txt 只有 5 类, parse_xml 会因 `cls not in classes` 跳过 7 类框,
#   导致新增 7 类标注的 LED 框全部丢失。故扫描 5 类副本目录。
XML_DIR = os.path.join(FP_DIR, 'Annotations_5class')


def get_classes(classes_path):
    with open(classes_path, encoding='utf-8') as f:
        return [c.strip() for c in f.readlines() if c.strip()]


def parse_xml(xml_path, classes):
    """从 XML 解析全部目标框, 返回 [(x1,y1,x2,y2,cls_id), ...]"""
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
        if cls not in classes or difficult == 1:
            continue
        cls_id = classes.index(cls)
        bb = obj.find('bndbox')
        x1 = int(float(bb.find('xmin').text))
        y1 = int(float(bb.find('ymin').text))
        x2 = int(float(bb.find('xmax').text))
        y2 = int(float(bb.find('ymax').text))
        objs.append((x1, y1, x2, y2, cls_id))
    return objs


def write_split(img_ids, classes, split_name):
    """将指定图片 id 列表写入 2025_<split>.txt, 返回 (图数, LED框数, area框数)。"""
    out = []
    n_led = 0
    n_area = 0
    for img_id in img_ids:
        xml_path = os.path.join(XML_DIR, img_id + '.xml')
        if not os.path.exists(xml_path):
            print('[WARN] 缺失 5 类标注, 跳过: %s' % xml_path)
            continue
        # 跳过缺图标注 (XML 存在但无对应 JPEG)
        if not os.path.exists(os.path.join(FP_DIR, 'JPEGImages', img_id + '.jpg')):
            print('[WARN] 缺失 JPEG, 跳过: %s' % img_id)
            continue
        boxes = parse_xml(xml_path, classes)
        n_led += sum(1 for b in boxes if not classes[b[4]].endswith('_area'))
        n_area += sum(1 for b in boxes if classes[b[4]].endswith('_area'))
        img_rel = 'datasets\\FP\\JPEGImages\\%s.jpg' % img_id
        boxes_str = ' '.join('%d,%d,%d,%d,%d' % b for b in boxes)
        out.append(img_rel + ' ' + boxes_str)
    out_txt = os.path.join(FP_DIR, '2025_%s.txt' % split_name)
    with open(out_txt, 'w', encoding='utf-8') as f:
        f.write('\n'.join(out) + '\n')
    print('%s: %d 张图, 框数 (LED=%d, area=%d)' % (out_txt, len(out), n_led, n_area))
    return len(out), n_led, n_area


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='FP 数据集 7:2:1 三分划分')
    parser.add_argument('--seed', type=int, default=42, help='随机种子 (默认 42, 保证可复现)')
    parser.add_argument('--ratio', nargs=3, type=float, default=[0.7, 0.2, 0.1],
                        metavar=('TRAIN', 'VAL', 'TEST'), help='划分比例 (默认 0.7 0.2 0.1)')
    args = parser.parse_args()

    # 归一化比例
    r_train, r_val, r_test = args.ratio
    s = r_train + r_val + r_test
    r_train, r_val, r_test = r_train / s, r_val / s, r_test / s

    CLASSES = get_classes(CLASSES_PATH)
    print('类别表:', CLASSES)

    # 收集全部有标注的图片 id (按名称排序保证稳定), 基于 5 类副本, 且跳过缺图
    all_ids = sorted(os.path.splitext(f)[0]
                     for f in os.listdir(XML_DIR)
                     if f.endswith('.xml')
                     and os.path.exists(os.path.join(FP_DIR, 'JPEGImages', os.path.splitext(f)[0] + '.jpg')))
    n = len(all_ids)
    print('有标注图片总数: %d' % n)

    # 固定 seed shuffle
    rng = random.Random(args.seed)
    shuffled = all_ids[:]
    rng.shuffle(shuffled)

    # 按比例切分 (train 取前 r_train, val 取接下来 r_val, 剩余给 test)
    n_train = int(round(n * r_train))
    n_val = int(round(n * r_val))
    # 修正: 保证三者之和 == n, 误差并入 train
    n_test = n - n_train - n_val
    if n_test < 0:
        n_train += n_test
        n_test = 0

    train_ids = shuffled[:n_train]
    val_ids = shuffled[n_train:n_train + n_val]
    test_ids = shuffled[n_train + n_val:]

    print('划分 (seed=%d): train=%d  val=%d  test=%d' % (args.seed, len(train_ids), len(val_ids), len(test_ids)))
    write_split(train_ids, CLASSES, 'train')
    write_split(val_ids, CLASSES, 'val')
    write_split(test_ids, CLASSES, 'test')
