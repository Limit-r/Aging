# -*- coding: utf-8 -*-
"""
从 7 类标注 XML 生成 4 类 YOLO 标注副本（A 系列）。

映射规则:
  A_CLIP_H / A_CLIP_L → A_CLIP
  A_PROT_H / A_PROT_L → A_PROT
  A_PWR_H  / A_PWR_L  → A_PWR
  A_area → 不变

用法:
    python ml/train/gen_5class_xmls_a.py

输出:
    datasets/A/Annotations_5class/
"""
import os
from pathlib import Path
import xml.etree.ElementTree as ET

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ANNOT_DIR = PROJECT_ROOT / 'datasets' / 'A' / 'Annotations'
OUTPUT_DIR = PROJECT_ROOT / 'datasets' / 'A' / 'Annotations_5class'

CLASS_MAP = {
    'A_CLIP_H': 'A_CLIP',
    'A_CLIP_L': 'A_CLIP',
    'A_PROT_H': 'A_PROT',
    'A_PROT_L': 'A_PROT',
    'A_PWR_H': 'A_PWR',
    'A_PWR_L': 'A_PWR',
}


def convert_xml(xml_path, out_path):
    tree = ET.parse(xml_path)
    root = tree.getroot()
    for obj in root.iter('object'):
        name_elem = obj.find('name')
        if name_elem is not None and name_elem.text in CLASS_MAP:
            name_elem.text = CLASS_MAP[name_elem.text]
    tree.write(out_path, encoding='utf-8', xml_declaration=True)


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    xml_files = sorted(ANNOT_DIR.glob('*.xml'))
    if not xml_files:
        print(f'[WARN] 未找到 XML 文件: {ANNOT_DIR}')
        return
    count = 0
    for xml_path in xml_files:
        out_path = OUTPUT_DIR / xml_path.name
        convert_xml(xml_path, out_path)
        count += 1
    print(f'完成: {count} 个 XML 从 7 类 → 4 类 (A 系列)')
    print(f'  源目录: {ANNOT_DIR}')
    print(f'  输出目录: {OUTPUT_DIR}')


if __name__ == '__main__':
    main()