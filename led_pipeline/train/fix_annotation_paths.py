# -*- coding: utf-8 -*-
"""修正 A 系列标注文件中的图片路径，补上 led_pipeline 目录"""
import os

base = r'd:\Aging\led_pipeline\datasets\A'
for fname in ['2025_train.txt', '2025_val.txt', '2025_test.txt']:
    fpath = os.path.join(base, fname)
    content = open(fpath, 'r', encoding='utf-8').read()
    new_content = content.replace(r'D:\Aging\datasets\A', r'D:\Aging\led_pipeline\datasets\A')
    open(fpath, 'w', encoding='utf-8').write(new_content)
    print(f'{fname}: 已修正')