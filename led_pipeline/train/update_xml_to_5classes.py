"""
将 XML 标注从 7 类名更新为 5 类名。

映射规则:
  VPL_L → VPL
  VPL_H → VPL
  CPL_L → CPL
  PWR_H → PWR
  PWR_L → PWR
  SIG_area / PWR_area → 不变

用法:
  python led_pipeline/train/update_xml_to_5classes.py
"""
import os
import xml.etree.ElementTree as ET

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ANNOT_DIR = os.path.join(PROJECT_ROOT, 'datasets', 'FP', 'Annotations')

CLASS_MAP = {
    'VPL_L': 'VPL',
    'VPL_H': 'VPL',
    'CPL_L': 'CPL',
    'PWR_H': 'PWR',
    'PWR_L': 'PWR',
}

def update_xml(xml_path):
    tree = ET.parse(xml_path)
    root = tree.getroot()
    changed = False
    for obj in root.iter('object'):
        name = obj.find('name')
        if name is not None and name.text in CLASS_MAP:
            new_name = CLASS_MAP[name.text]
            if new_name != name.text:
                print(f'  {os.path.basename(xml_path)}: {name.text} → {new_name}')
                name.text = new_name
                changed = True
    if changed:
        tree.write(xml_path, encoding='utf-8', xml_declaration=True)
    return changed

def main():
    xml_files = sorted(f for f in os.listdir(ANNOT_DIR) if f.endswith('.xml'))
    print(f'找到 {len(xml_files)} 个 XML 文件')
    count = 0
    for fname in xml_files:
        xml_path = os.path.join(ANNOT_DIR, fname)
        if update_xml(xml_path):
            count += 1
    print(f'\n更新完成: {count} 个文件被修改')

if __name__ == '__main__':
    main()