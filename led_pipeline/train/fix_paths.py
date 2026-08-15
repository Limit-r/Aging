# -*- coding: utf-8 -*-
"""修正 A 系列标注文件中的图片路径为绝对路径"""
import os

base = r'd:\Aging\led_pipeline\datasets\A'
for fname in ['2025_train.txt', '2025_val.txt', '2025_test.txt']:
    fpath = os.path.join(base, fname)
    lines = open(fpath, encoding='utf-8').readlines()
    fixed = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        parts = line.split(' ', 1)
        img_rel = parts[0]
        # 如果已经是绝对路径则跳过
        if img_rel.startswith('D:') or img_rel.startswith('d:'):
            fixed.append(line)
            continue
        img_abs = os.path.join(r'D:\Aging\led_pipeline', img_rel)
        rest = parts[1] if len(parts) > 1 else ''
        fixed.append(f'{img_abs} {rest}')
    open(fpath, 'w', encoding='utf-8').write('\n'.join(fixed) + '\n')
    print(f'{fname}: 修正 {len(fixed)} 行')