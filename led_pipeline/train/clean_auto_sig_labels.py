# -*- coding: utf-8 -*-
"""
清理自动标注的 A_SIG_H XML 文件。
只删除那些仅包含 A_SIG_H 类别的自动生成的标注文件。
手动标注的文件（包含多个类别）将被保留，但也会移除其中的 A_SIG_H 对象。

用法:
  conda run -n Aging python led_pipeline/train/clean_auto_sig_labels.py
"""
import os
import xml.etree.ElementTree as ET

ANNO_DIR = r'd:\Aging\led_pipeline\datasets\A\Annotations'


def get_objects_in_xml(xml_path):
    """返回 XML 中所有 object 的 (name, class_id) 列表"""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    objects = []
    for obj in root.iter('object'):
        name = obj.find('name').text
        objects.append(name)
    return objects


def main():
    # 扫描所有 XML 文件
    xml_files = sorted([f for f in os.listdir(ANNO_DIR) if f.endswith('.xml')])

    auto_deleted = 0      # 仅含 A_SIG_H 的自动标注，直接删除
    sig_removed = 0       # 手动标注中移除了 A_SIG_H 对象
    classes_removed = 0   # 移除的 A_SIG_H 对象总数

    for fname in xml_files:
        xml_path = os.path.join(ANNO_DIR, fname)
        objects = get_objects_in_xml(xml_path)

        unique_classes = set(objects)

        if unique_classes == {'A_SIG_H'}:
            # 仅含 A_SIG_H → 自动标注，直接删除
            os.remove(xml_path)
            auto_deleted += 1
            classes_removed += len(objects)
            print('  [删除] %s (仅 A_SIG_H, %d 个框)' % (fname, len(objects)))
        elif 'A_SIG_H' in unique_classes and len(unique_classes) > 1:
            # 手动标注文件，包含 A_SIG_H 和其他类别 → 移除 A_SIG_H 对象
            tree = ET.parse(xml_path)
            root = tree.getroot()
            removed_count = 0
            for obj in list(root.iter('object')):
                if obj.find('name').text == 'A_SIG_H':
                    root.remove(obj)
                    removed_count += 1
            if removed_count > 0:
                tree.write(xml_path, encoding='utf-8', xml_declaration=True)
                sig_removed += 1
                classes_removed += removed_count
                print('  [移除] %s 中移除了 %d 个 A_SIG_H 框' % (fname, removed_count))

    print('\n' + '=' * 60)
    print('清理完成！')
    print('  删除的自动标注文件: %d' % auto_deleted)
    print('  移除 A_SIG_H 的手动标注文件: %d' % sig_removed)
    print('  共移除 A_SIG_H 框: %d 个' % classes_removed)

    # 最终统计
    remaining = [f for f in os.listdir(ANNO_DIR) if f.endswith('.xml')]
    print('  剩余标注文件: %d 个' % len(remaining))
    print('=' * 60)


if __name__ == '__main__':
    main()