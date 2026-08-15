# -*- coding: utf-8 -*-
"""
A 系列数据集: 收集类别、生成 label.txt、三分 train/val/test txt

用法:
  python ml/train/gen_a_txt.py
  python ml/train/gen_a_txt.py --seed 42
"""
import argparse
import os
import random
import xml.etree.ElementTree as ET

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
A_DIR = os.path.join(PROJECT_ROOT, 'datasets', 'A')
LABEL_PATH = os.path.join(A_DIR, 'label.txt')


def collect_classes(xml_dir):
    """扫描所有 XML, 收集全部唯一类别名 (按字母排序)"""
    classes = set()
    for fname in os.listdir(xml_dir):
        if not fname.endswith('.xml'):
            continue
        tree = ET.parse(os.path.join(xml_dir, fname))
        root = tree.getroot()
        for obj in root.iter('object'):
            classes.add(obj.find('name').text)
    return sorted(classes)


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
    """将指定图片 id 列表写入 <split>.txt"""
    out = []
    for img_id in img_ids:
        xml_path = os.path.join(A_DIR, 'Annotations', img_id + '.xml')
        if not os.path.exists(xml_path):
            print('[WARN] 缺失 XML, 跳过: %s' % xml_path)
            continue
        boxes = parse_xml(xml_path, classes)
        img_rel = os.path.join(A_DIR, 'JPEGImages', img_id + '.jpg')
        boxes_str = ' '.join('%d,%d,%d,%d,%d' % b for b in boxes)
        out.append(img_rel + ' ' + boxes_str)
    out_txt = os.path.join(A_DIR, '2025_%s.txt' % split_name)
    with open(out_txt, 'w', encoding='utf-8') as f:
        f.write('\n'.join(out) + '\n')
    print('%s: %d 张图, %d 个框' % (out_txt, len(out), sum(len(b.split()) - 1 for b in out)))
    return len(out)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='A 数据集 7:2:1 三分划分')
    parser.add_argument('--seed', type=int, default=42, help='随机种子')
    parser.add_argument('--ratio', nargs=3, type=float, default=[0.7, 0.2, 0.1],
                        metavar=('TRAIN', 'VAL', 'TEST'), help='划分比例')
    args = parser.parse_args()

    r_train, r_val, r_test = args.ratio
    s = r_train + r_val + r_test
    r_train, r_val, r_test = r_train / s, r_val / s, r_test / s

    xml_dir = os.path.join(A_DIR, 'Annotations')

    # 1. 收集全部类别并写入 label.txt
    classes = collect_classes(xml_dir)
    print('类别表 (%d 类): %s' % (len(classes), classes))
    with open(LABEL_PATH, 'w', encoding='utf-8') as f:
        f.write('\n'.join(classes) + '\n')
    print('已写入: %s' % LABEL_PATH)

    # 2. 收集全部有标注图片 id
    all_ids = sorted(os.path.splitext(f)[0]
                     for f in os.listdir(xml_dir)
                     if f.endswith('.xml'))
    n = len(all_ids)
    print('有标注图片总数: %d' % n)

    # 3. 固定 seed shuffle 后三分
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
    write_split(train_ids, classes, 'train')
    write_split(val_ids, classes, 'val')
    write_split(test_ids, classes, 'test')