"""检查数据集统计信息"""
import os
from pathlib import Path
import xml.etree.ElementTree as ET

fp_dir = Path('d:/Aging/led_pipeline/datasets/FP')
for split in ['train', 'val', 'test']:
    txt_path = fp_dir / f'2025_{split}.txt'
    with open(txt_path) as f:
        lines = [l.strip() for l in f if l.strip()]
    n_imgs = len(lines)
    n_rois = sum(len(l.split()) - 1 for l in lines)
    print(f'{split}: {n_imgs} 张图, {n_rois} 个 ROI 框')

xml_dir = fp_dir / 'Annotations'
xml_files = sorted(xml_dir.glob('*.xml'))
print(f'\n总 XML 标注文件: {len(xml_files)}')

total_led_rois = 0
total_area = 0
for xml_path in xml_files:
    tree = ET.parse(str(xml_path))
    root = tree.getroot()
    for obj in root.findall('object'):
        name = obj.find('name').text
        if name in ('FP_VPL', 'FP_CPL', 'FP_PWR'):
            total_led_rois += 1
        elif name in ('FP_SIG_area', 'FP_PWR_area'):
            total_area += 1
print(f'总 LED ROI (FP_VPL/FP_CPL/FP_PWR): {total_led_rois}')
print(f'总 Area ROI (FP_SIG/FP_PWR_area): {total_area}')
print(f'总 ROI 框数: {total_led_rois + total_area}')