"""
批量更新 Annotations/ 中的 XML 标注，为所有类别名添加 FP_ 前缀。

当前 Annotations/ 中的 XML 已经是 5 类标注（无 H/L 信息）：
  SIG_area  → FP_SIG_area
  PWR_area  → FP_PWR_area
  VPL       → FP_VPL
  CPL       → FP_CPL
  PWR       → FP_PWR

用法:
    python led_pipeline/train/add_fp_prefix_to_xmls.py
"""
import os
import xml.etree.ElementTree as ET

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ANNOT_DIR = os.path.join(PROJECT_ROOT, 'datasets', 'FP', 'Annotations')

# 旧类名 → 新类名映射
CLASS_MAP = {
    'SIG_area': 'FP_SIG_area',
    'PWR_area': 'FP_PWR_area',
    'VPL': 'FP_VPL',
    'CPL': 'FP_CPL',
    'PWR': 'FP_PWR',
}


def update_xml(xml_path):
    """读取 XML，将 <name> 中的旧类名替换为带 FP_ 前缀的新类名。"""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    changed = False
    for obj in root.iter('object'):
        name_elem = obj.find('name')
        if name_elem is not None and name_elem.text in CLASS_MAP:
            name_elem.text = CLASS_MAP[name_elem.text]
            changed = True
    if changed:
        tree.write(xml_path, encoding='utf-8', xml_declaration=True)
    return changed


def main():
    xml_files = sorted(f for f in os.listdir(ANNOT_DIR) if f.endswith('.xml'))
    if not xml_files:
        print(f'[WARN] 未找到 XML 文件: {ANNOT_DIR}')
        return

    count = 0
    for fname in xml_files:
        xml_path = os.path.join(ANNOT_DIR, fname)
        if update_xml(xml_path):
            count += 1

    print(f'完成: {count}/{len(xml_files)} 个 XML 已更新 (FP_ 前缀)')
    print(f'  目录: {ANNOT_DIR}')

    # 验证一个文件
    if xml_files:
        verify_path = os.path.join(ANNOT_DIR, xml_files[0])
        tree = ET.parse(verify_path)
        names = set()
        for obj in tree.iter('object'):
            name_elem = obj.find('name')
            if name_elem is not None:
                names.add(name_elem.text)
        print(f'  验证 ({xml_files[0]}): 类别名 = {sorted(names)}')


if __name__ == '__main__':
    main()