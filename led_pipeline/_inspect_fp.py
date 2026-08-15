# -*- coding: utf-8 -*-
"""临时检查: classifier/data 中 H 样本的来源与现状"""
import os
from pathlib import Path

cd = Path(r'd:\Aging\led_pipeline\classifier\data')
for s in ['train', 'val', 'test']:
    for l in ['L', 'H']:
        d = cd / s / l
        if not d.exists():
            continue
        files = os.listdir(d)
        print('%s/%s: %d 个' % (s, l, len(files)))
        if l == 'H' and files:
            print('   H 样本示例:', files[:5])
            # 提取来源图前缀
            srcs = set()
            for f in files:
                # 文件名格式: frame_XXXXXX_x1_y1_x2_y2.png
                parts = f.split('_')
                srcs.add('_'.join(parts[:2]))
            print('   H 来源图数:', len(srcs))
            print('   H 来源图:', sorted(srcs)[:20])