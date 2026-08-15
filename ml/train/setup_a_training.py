# -*- coding: utf-8 -*-
"""配置 A 系列训练：更新 config.py + 创建训练配置文件 + 训练入口"""
import os
import json

# 1. 更新 d:\YOLO_train\config.py
config_path = r'd:\YOLO_train\config.py'
with open(config_path, 'r', encoding='utf-8') as f:
    content = f.read()

old_end = """    'FP_LED': {
        'display_name': 'FP 系列 LED 检测',
        'classes_path': r'datasets\FP_LED\label.txt',
        'train_annotation_path': 'datasets/FP_LED/2025_train.txt',
        'val_annotation_path': 'datasets/FP_LED/2025_val.txt',
        'label_list': ['VPL', 'CPL', 'PWR'],
        'default_phi': 'n',
        'save_dir': 'weights/FP_LED',
    },
}"""

new_entry = """    'FP_LED': {
        'display_name': 'FP 系列 LED 检测',
        'classes_path': r'datasets\FP_LED\label.txt',
        'train_annotation_path': 'datasets/FP_LED/2025_train.txt',
        'val_annotation_path': 'datasets/FP_LED/2025_val.txt',
        'label_list': ['VPL', 'CPL', 'PWR'],
        'default_phi': 'n',
        'save_dir': 'weights/FP_LED',
    },
    'A': {
        'display_name': 'A 系列 LED 检测',
        'classes_path': r'datasets\A\label.txt',
        'train_annotation_path': 'datasets/A/2025_train.txt',
        'val_annotation_path': 'datasets/A/2025_val.txt',
        'label_list': ['A_CPL_L', 'A_PROT', 'A_PROT_L', 'A_PWR', 'A_PWR_L', 'A_SiIG_L'],
        'default_phi': 'n',
        'save_dir': 'weights/A',
    },
}"""

if old_end in content:
    content = content.replace(old_end, new_entry)
    with open(config_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print('config.py: A 数据集配置已添加')
else:
    print('config.py: 未找到 FP_LED 段尾，请检查文件')

# 2. 创建训练配置文件
train_cfg = {
    "dataset_name": "A",
    "Cuda": True,
    "seed": 42,
    "distributed": False,
    "sync_bn": False,
    "fp16": True,
    "phi": "n",
    "input_shape": [512, 512],
    "model_path": "",
    "pretrained": True,
    "mosaic": True,
    "mosaic_prob": 0.3,
    "mixup": True,
    "mixup_prob": 0.1,
    "special_aug_ratio": 0.4,
    "label_smoothing": 0.01,
    "Init_Epoch": 0,
    "Freeze_Epoch": 0,
    "Freeze_batch_size": 2,
    "Freeze_Train": False,
    "UnFreeze_Epoch": 200,
    "Unfreeze_batch_size": 2,
    "Init_lr": 0.005,
    "Min_lr": 0.00001,
    "optimizer_type": "sgd",
    "momentum": 0.9,
    "weight_decay": 0.0005,
    "lr_decay_type": "cos",
    "save_period": 25,
    "save_dir": "weights/A",
    "eval_flag": True,
    "eval_period": 5,
    "num_workers": 2,
    "gradient_clip_norm": 7.0,
    "min_recall_threshold": 0.6,
    "min_f1_threshold": 0.5,
    "export_deploy_model": True,
    "early_stop_enabled": True,
    "early_stop_patience": 30,
    "early_stop_metric": "val_loss",
    "epoch_offset": 0,
    "train_annotation_path": "datasets/A/2025_train.txt",
    "val_annotation_path": "datasets/A/2025_val.txt",
    "classes_path": "datasets\\A\\label.txt"
}

cfg_out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config_a_train.json')
with open(cfg_out, 'w', encoding='utf-8') as f:
    json.dump(train_cfg, f, indent=2, ensure_ascii=False)
print(f'训练配置已写入: {cfg_out}')

# 3. 创建训练入口脚本
train_a_py = r'''# -*- coding: utf-8 -*-
"""
A 系列 YOLOv8 训练入口 (6 类: A_CPL_L / A_PROT / A_PROT_L / A_PWR / A_PWR_L / A_SiIG_L)

用法:
  python ml/train/train_a.py
  python ml/train/train_a.py --config path/to/other.json
"""
import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

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
'''

train_a_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'train_a.py')
with open(train_a_path, 'w', encoding='utf-8') as f:
    f.write(train_a_py)
print(f'训练入口已创建: {train_a_path}')
print('完成!')