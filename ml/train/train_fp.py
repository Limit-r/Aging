# -*- coding: utf-8 -*-
"""
FP 数据集 YOLOv8 训练入口 (5 类: FP_SIG_area / FP_PWR_area / FP_VPL / FP_CPL / FP_PWR)

设计说明
--------
本脚本不再自己实现训练流程, 而是直接复用 `ml/train.py` 的 `train(cfg)` 函数 ——
即"参考的成体系 yolo 训练脚本"。这样:
  - 模型/损失/数据加载/EMA/评估/早停/断点续训 等所有成熟组件零重复实现
  - 配置完全由 config_fp_train_v3.json 驱动, 字段与 ml/train.py 期望一致
  - 仅需保证 ml/ 加入 sys.path, 让 `from train import train` 可达

模型: YoloBody (yolov8_n) + COCO 预训练主干, 512x512 输入, anchor-free + TAL
输出: weights/FP_v3_5classes/  (与旧 weights/FP_v2 隔离, 避免覆盖)

注意: 2026-08-06 从 7 类改为 5 类, LED 亮灭状态由 TinyConv 二分类器判断。

用法
----
  python ml/train/train_fp.py
  python ml/train/train_fp.py --config path/to/other.json
"""
import json
import os
import sys

# 模型/训练代码根 = ml/  (train_fp.py -> train -> ml)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# 复用 ml/ 成体系训练脚本 (train.py 的 train(cfg) 函数)
# 注意: 不能用 `from train import train` —— ml/train/ 包会遮蔽
# ml/train.py 模块。改用 importlib 按文件路径显式加载。
import importlib.util

_TRAIN_PY = os.path.join(PROJECT_ROOT, 'train.py')
_spec = importlib.util.spec_from_file_location('fp_root_train', _TRAIN_PY)
_train_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_train_mod)
train = _train_mod.train

DEFAULT_CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config_fp_train_v3.json')


def main():
    # 解析 --config 参数, 默认使用同目录 config_fp_train_v3.json
    cfg_path = DEFAULT_CONFIG
    if len(sys.argv) > 1 and sys.argv[1] == '--config' and len(sys.argv) > 2:
        cfg_path = sys.argv[2]
    with open(cfg_path, encoding='utf-8') as f:
        cfg = json.load(f)

    print('=' * 70)
    print('FP YOLOv8 训练 (5 类: FP_SIG_area / FP_PWR_area / FP_VPL / FP_CPL / FP_PWR)')
    print('  配置文件 :', cfg_path)
    print('  数据集   :', cfg['dataset_name'])
    print('  类别表   :', cfg['classes_path'])
    print('  模型     : yolov8_%s, 输入 %s' % (cfg['phi'], cfg['input_shape']))
    print('  轮次     : %d -> %d' % (cfg['Init_Epoch'], cfg['UnFreeze_Epoch']))
    print('  权重输出 :', cfg['save_dir'])
    print('  预训练   :', cfg['pretrained'], '(model_path=%r)' % cfg['model_path'])
    print('=' * 70)

    train(cfg)


if __name__ == '__main__':
    main()
