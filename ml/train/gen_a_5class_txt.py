# -*- coding: utf-8 -*-
"""
从 Annotations_5class/ 生成 4 类 YOLO 训练 txt 文件。

用法:
  python ml/train/gen_a_5class_txt.py
"""
import argparse
import os
import random
import xml.etree.ElementTree as ET

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
A_DIR = os.path.join(PROJECT_ROOT, 'datasets', 'A')
LABEL_PATH = os.path.join(A_DIR, 'label_5class.txt')
ANNOT_DIR = os.path.join(A_DIR, 'Annotations_5class')


def get_classes(classes_path):
    with open(classes_path, encoding='utf-8') as f:
        return [c.strip() for c in f.readlines() if c.strip()]


def parse_xml(xml_path, classes):
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
    out = []
    for img_id in img_ids:
        xml_path = os.path.join(ANNOT_DIR, img_id + '.xml')
        if not os.path.exists(xml_path):
            print('[WARN] 缺失 XML, 跳过: %s' % xml_path)
            continue
        boxes = parse_xml(xml_path, classes)
        img_rel = os.path.join(A_DIR, 'JPEGImages', img_id + '.jpg')
        boxes_str = ' '.join('%d,%d,%d,%d,%d' % b for b in boxes)
        out.append(img_rel + ' ' + boxes_str)
    out_txt = os.path.join(A_DIR, '2025_%s_5class.txt' % split_name)
    with open(out_txt, 'w', encoding='utf-8') as f:
        f.write('\n'.join(out) + '\n')
    print('%s: %d 张图, %d 个框' % (out_txt, len(out), sum(len(b.split()) - 1 for b in out)))
    return len(out)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='A 系列 4 类 YOLO 训练 txt 生成')
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--ratio', nargs=3, type=float, default=[0.7, 0.2, 0.1])
    args = parser.parse_args()

    r_train, r_val, r_test = args.ratio
    s = r_train + r_val + r_test
    r_train, r_val, r_test = r_train / s, r_val / s, r_test / s

    CLASSES = get_classes(LABEL_PATH)
    print('类别表 (4 类):', CLASSES)

    all_ids = sorted(os.path.splitext(f)[0]
                     for f in os.listdir(ANNOT_DIR)
                     if f.endswith('.xml'))
    n = len(all_ids)
    print('有标注图片总数: %d' % n)

    rng = random.Random(args.seed)
    shuffled = all_ids[:]
    rng.shuffle(shuffled)

    n_train = int(round(n * r_train))
    n_val = int(round(n * r_val))
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