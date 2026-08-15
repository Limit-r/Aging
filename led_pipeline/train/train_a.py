# -*- coding: utf-8 -*-
"""
A 系列 YOLOv8 训练入口 (7 类: A_CLIP_H / A_CLIP_L / A_PROT_H / A_PROT_L / A_PWR_H / A_SIG_H / A_area)

用法:
  python led_pipeline/train/train_a.py
  python led_pipeline/train/train_a.py --config path/to/other.json
"""
import json
import os
import sys

# 训练框架在 d:\YOLO_train，将其加入 sys.path
YOLO_TRAIN_ROOT = r'd:\YOLO_train'
if YOLO_TRAIN_ROOT not in sys.path:
    sys.path.insert(0, YOLO_TRAIN_ROOT)

from train import train

DEFAULT_CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config_a_train.json')


def main():
    cfg_path = DEFAULT_CONFIG
    if len(sys.argv) > 1 and sys.argv[1] == '--config' and len(sys.argv) > 2:
        cfg_path = sys.argv[2]
    with open(cfg_path, encoding='utf-8') as f:
        cfg = json.load(f)

    print('=' * 70)
    print('A 系列 YOLOv8 训练 (6 类)')
    print('  配置文件 :', cfg_path)
    print('  数据集   :', cfg['dataset_name'])
    print('  类别表   :', cfg['classes_path'])
    print('  模型     : yolov8_%s, 输入 %s' % (cfg['phi'], cfg['input_shape']))
    print('  轮次     : %d -> %d' % (cfg['Init_Epoch'], cfg['UnFreeze_Epoch']))
    print('  权重输出 :', cfg['save_dir'])
    print('=' * 70)

    train(cfg)


if __name__ == '__main__':
    main()