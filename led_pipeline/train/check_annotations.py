# -*- coding: utf-8 -*-
"""检查 A 系列标注状态"""
import os, xml.etree.ElementTree as ET

xml_dir = r'd:\Aging\led_pipeline\datasets\A\Annotations'
classes = set()
xml_files = sorted([f for f in os.listdir(xml_dir) if f.endswith('.xml')])
total_objs = 0
for fname in xml_files:
    tree = ET.parse(os.path.join(xml_dir, fname))
    objs = list(tree.getroot().iter('object'))
    total_objs += len(objs)
    for obj in objs:
        classes.add(obj.find('name').text)

print(f"标注文件: {len(xml_files)} 张")
print(f"总目标框: {total_objs} 个")
print(f"类别 ({len(classes)}): {sorted(classes)}")