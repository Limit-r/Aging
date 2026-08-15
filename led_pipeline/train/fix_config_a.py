# -*- coding: utf-8 -*-
"""修正 YOLO_train/config.py 中 A 系列的 label_list (6 类，移除 A_SIG_H)"""
content = open(r'd:\YOLO_train\config.py', encoding='utf-8').read()
old = "'A_CLIP_H', 'A_CLIP_L', 'A_PROT_H', 'A_PROT_L', 'A_PWR_H', 'A_SIG_H', 'A_area'"
new = "'A_CLIP_H', 'A_CLIP_L', 'A_PROT_H', 'A_PROT_L', 'A_PWR_H', 'A_area'"
content = content.replace(old, new)
open(r'd:\YOLO_train\config.py', 'w', encoding='utf-8').write(content)
print('config.py A 系列 label_list 已修正为 6 类')