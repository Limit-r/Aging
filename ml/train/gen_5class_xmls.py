"""
从 7 类标注 XML 生成 5 类 YOLO 标注副本。

设计说明:
  labelImg 标注时保持 7 类（保留 H/L 信息），本脚本将 7 类映射为 5 类，
  输出到 Annotations_5class/ 目录，供 YOLO 训练使用。

  这样原始标注不会丢失 H/L 信息，二分类任务可直接使用原始标注。

映射规则:
  FP_VPL_L → FP_VPL
  FP_VPL_H → FP_VPL
  FP_CPL_L → FP_CPL
  FP_CPL_H → FP_CPL
  FP_PWR_H → FP_PWR
  FP_PWR_L → FP_PWR
  FP_SIG_area / FP_PWR_area → 不变

用法:
    python ml/train/gen_5class_xmls.py

输出:
    datasets/FP/Annotations_5class/  (与原 Annotations 结构相同，仅类别名映射为 5 类)
"""
import os
import shutil
from pathlib import Path
import xml.etree.ElementTree as ET

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ANNOT_DIR = PROJECT_ROOT / 'datasets' / 'FP' / 'Annotations'
OUTPUT_DIR = PROJECT_ROOT / 'datasets' / 'FP' / 'Annotations_5class'

# 7 类 → 5 类映射 (FP 系列前缀统一为 FP_)
CLASS_MAP = {
    'FP_VPL_L': 'FP_VPL',
    'FP_VPL_H': 'FP_VPL',
    'FP_CPL_L': 'FP_CPL',
    'FP_CPL_H': 'FP_CPL',
    'FP_PWR_H': 'FP_PWR',
    'FP_PWR_L': 'FP_PWR',
}


def convert_xml(xml_path, out_path):
    """读取 7 类 XML，写入 5 类 XML 副本。"""
    tree = ET.parse(xml_path)
    root = tree.getroot()

    for obj in root.iter('object'):
        name_elem = obj.find('name')
        if name_elem is not None and name_elem.text in CLASS_MAP:
            name_elem.text = CLASS_MAP[name_elem.text]

    tree.write(out_path, encoding='utf-8', xml_declaration=True)


def main():
    # 创建输出目录
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    xml_files = sorted(ANNOT_DIR.glob('*.xml'))
    if not xml_files:
        print(f'[WARN] 未找到 XML 文件: {ANNOT_DIR}')
        print('        请先在 Annotations/ 目录中放置 7 类标注 XML')

    count = 0
    for xml_path in xml_files:
        out_path = OUTPUT_DIR / xml_path.name
        convert_xml(xml_path, out_path)
        count += 1

    print(f'完成: {count} 个 XML 从 7 类 → 5 类')
    print(f'  源目录: {ANNOT_DIR}')
    print(f'  输出目录: {OUTPUT_DIR}')
    print()
    print('提示: 训练 YOLO 时请将数据集的 Annotations 路径指向 Annotations_5class/')
    print('      二分类任务仍使用 Annotations/ 中的原始 7 类标注')


if __name__ == '__main__':
    main()