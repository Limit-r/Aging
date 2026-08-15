# -*- coding: utf-8 -*-
"""复制 A 数据集到 YOLO_train"""
import shutil, os

src = r'd:\Aging\led_pipeline\datasets\A'
dst = r'd:\YOLO_train\datasets\A'

if os.path.exists(dst):
    shutil.rmtree(dst)
    print('已删除旧目录')

shutil.copytree(src, dst)
annos = len(os.listdir(os.path.join(dst, 'Annotations')))
images = len(os.listdir(os.path.join(dst, 'JPEGImages')))
print('复制完成: %d 张图, %d 个标注' % (images, annos))