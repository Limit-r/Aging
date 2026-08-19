# -*- coding: utf-8 -*-
"""
生成统一 9 类 YOLO 训练数据 (FP + A 系列合并)。

背景
----
项目原本维护 FP(5 类) / A(4 类) 两套独立 YOLO 训练体系。本脚本把两侧标注映射进
**同一份 9 类 label**（类别顺序取自类别注册表 categories.json），生成统一的
train / val / test txt，供统一模型训练使用；图片仍留在各自目录，不拷贝。

9 类顺序（来自注册表，YOLO class id = 在此列表中的下标）:
  FP_SIG_area / FP_PWR_area / FP_VPL / FP_CPL / FP_PWR
  / A_area / A_CLIP / A_PROT / A_PWR

归一化规则:
  - FP 的 Annotations 已是 5 类名（无 H/L），直接映射；
  - A 的 Annotations 是 7 类名（含 _H/_L），剥掉 H/L 后缀后映射到基础类名。
  H/L 属性仅用于 TinyConv 二分类（见 classifier 数据），YOLO 只用到 9 类基础名。

用法（在 ml/ 下运行）:
  python -m train.gen_merged_txt            （等价于: python ml/train/gen_merged_txt.py）
  python -m train.gen_merged_txt --seed 42
  python -m train.gen_merged_txt --ratio 0.7 0.2 0.1

输出:
  datasets/merged/label_merged.txt           9 类 label（按注册表顺序）
  datasets/merged/2025_train.txt / _val / _test.txt
    每行: <图片绝对路径> x1,y1,x2,y2,cls_id ...
"""
import argparse
import os
import random
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# 本项目 ml/ = PROJECT_ROOT（gen_merged_txt.py -> ml/train -> ml）
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from annotation_registry import get_registry

MERGED_DIR = PROJECT_ROOT / 'datasets' / 'merged'


def normalize_name(name: str) -> str:
    """剥掉 H/L 后缀，返回 YOLO 基础类名（FP 5 类名不受影响）。"""
    if name.endswith('_H') or name.endswith('_L'):
        return name[:-2]
    return name


def parse_xml(xml_path, class_order):
    """解析 VOC XML，返回 [(x1,y1,x2,y2,cls_id), ...]（跳过 difficult 与未知类名）。"""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    objs = []
    for obj in root.iter('object'):
        try:
            difficult = obj.find('difficult').text if obj.find('difficult') is not None else 0
            difficult = int(difficult)
        except (TypeError, ValueError):
            difficult = 0
        if difficult == 1:
            continue
        cls = normalize_name(obj.find('name').text)
        if cls not in class_order:
            continue
        cls_id = class_order[cls]
        bb = obj.find('bndbox')
        x1 = int(float(bb.find('xmin').text))
        y1 = int(float(bb.find('ymin').text))
        x2 = int(float(bb.find('xmax').text))
        y2 = int(float(bb.find('ymax').text))
        objs.append((x1, y1, x2, y2, cls_id))
    return objs


def collect_series(class_order, series_name, annot_dir, images_dir):
    """收集一个系列的所有 (图片绝对路径, boxes)。跳过缺图。"""
    entries = []
    if not annot_dir.exists():
        print('[WARN] 标注目录不存在，跳过 %s: %s' % (series_name, annot_dir))
        return entries
    for xml_path in sorted(annot_dir.glob('*.xml')):
        img_id = xml_path.stem
        img_path = images_dir / (img_id + '.jpg')
        if not img_path.exists():
            print('[WARN] 缺失 JPEG，跳过 %s: %s' % (series_name, img_path))
            continue
        boxes = parse_xml(xml_path, class_order)
        if not boxes:
            continue
        entries.append((str(img_path), boxes))
    print('  %s: %d 张图' % (series_name, len(entries)))
    return entries


def write_split(img_entries, split_name):
    """把图片条目写入 <merged>/2025_<split>.txt，返回 (图数, LED框数, area框数)。"""
    out = []
    n_led = 0
    n_area = 0
    for img_path, boxes in img_entries:
        n_led += sum(1 for b in boxes if not MP_CLASSES[b[4]].endswith('_area'))
        n_area += sum(1 for b in boxes if MP_CLASSES[b[4]].endswith('_area'))
        boxes_str = ' '.join('%d,%d,%d,%d,%d' % b for b in boxes)
        out.append(img_path + ' ' + boxes_str)
    out_txt = MERGED_DIR / ('2025_%s.txt' % split_name)
    with open(out_txt, 'w', encoding='utf-8') as f:
        f.write('\n'.join(out) + '\n')
    print('%s: %d 张图, 框数 (LED=%d, area=%d)' % (out_txt, len(out), n_led, n_area))
    return len(out), n_led, n_area


# 模块级引用，供 write_split 使用（在 main 里初始化）
MP_CLASSES = []


def main():
    parser = argparse.ArgumentParser(description='生成统一 9 类 YOLO 训练 txt')
    parser.add_argument('--seed', type=int, default=42, help='随机种子 (默认 42)')
    parser.add_argument('--ratio', nargs=3, type=float, default=[0.7, 0.2, 0.1],
                        metavar=('TRAIN', 'VAL', 'TEST'), help='划分比例 (默认 0.7 0.2 0.1)')
    args = parser.parse_args()

    r_train, r_val, r_test = args.ratio
    s = r_train + r_val + r_test
    r_train, r_val, r_test = r_train / s, r_val / s, r_test / s

    # 9 类顺序来自类别注册表
    reg = get_registry()
    global MP_CLASSES
    MP_CLASSES = reg.category_names()
    class_order = {name: i for i, name in enumerate(MP_CLASSES)}
    print('统一 9 类表: %s' % MP_CLASSES)

    # 收集两个系列
    ds = PROJECT_ROOT / 'datasets'
    all_entries = []
    all_entries += collect_series(class_order, 'FP', ds / 'FP' / 'Annotations', ds / 'FP' / 'JPEGImages')
    all_entries += collect_series(class_order, 'A', ds / 'A' / 'Annotations', ds / 'A' / 'JPEGImages')
    n = len(all_entries)
    print('有标注图片总数（合并）: %d' % n)

    # 合并后统一随机切分 7:2:1（保证 train/val/test 混合两个系列）
    rng = random.Random(args.seed)
    shuffled = all_entries[:]
    rng.shuffle(shuffled)
    n_train = int(round(n * r_train))
    n_val = int(round(n * r_val))
    n_test = n - n_train - n_val
    if n_test < 0:
        n_train += n_test
        n_test = 0
    print('划分 (seed=%d): train=%d  val=%d  test=%d' % (args.seed, n_train, n_val, n_test))

    # 写 label 与 txt
    MERGED_DIR.mkdir(parents=True, exist_ok=True)
    with open(MERGED_DIR / 'label_merged.txt', 'w', encoding='utf-8') as f:
        f.write('\n'.join(MP_CLASSES) + '\n')
    print('label: %s' % (MERGED_DIR / 'label_merged.txt'))

    write_split(shuffled[:n_train], 'train')
    write_split(shuffled[n_train:n_train + n_val], 'val')
    write_split(shuffled[n_train + n_val:], 'test')


if __name__ == '__main__':
    main()