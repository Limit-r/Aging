# -*- coding: utf-8 -*-
"""
统一 9 类模型 YOLOv8 训练入口 (FP + A 系列合并)。

类别表（9 类）:
  FP_SIG_area / FP_PWR_area / FP_VPL / FP_CPL / FP_PWR
  / A_area / A_CLIP / A_PROT / A_PWR

依赖 Phase 1 生成的统一数据 (datasets/merged/)：
  先运行 gen_merged_txt.py 生成 label_merged.txt + 2025_{train,val,test}.txt。

用法（在 ml/ 下运行，否则路径解析错误）:
  python ml/train/train_merged.py                     # 用 config 默认值
  python ml/train/train_merged.py --epochs 100 --batch 4 --lr 0.005
  python ml/train/train_merged.py --config path/to.json

超参数命令行覆盖（供 GUI / 一键流程使用）:
  --epochs  覆盖 UnFreeze_Epoch
  --batch   覆盖 Unfreeze_batch_size
  --lr      覆盖 Init_lr
"""
import argparse
import json
import os
import sys

# 模型/训练代码根 = ml/  (train_merged.py -> train -> ml)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# 复用 ml/ 成体系训练脚本 (train.py 的 train(cfg) 函数)
# 注意: 不能用 `from train import train` —— ml/train/ 包会遮蔽
# ml/train.py 模块。改用 importlib 按文件路径显式加载。
import importlib.util

_TRAIN_PY = os.path.join(PROJECT_ROOT, 'train.py')
_spec = importlib.util.spec_from_file_location('merged_root_train', _TRAIN_PY)
_train_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_train_mod)
train = _train_mod.train

DEFAULT_CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config_merged_train.json')

CLASS_ORDER = [
    'FP_SIG_area', 'FP_PWR_area', 'FP_VPL', 'FP_CPL', 'FP_PWR',
    'A_area', 'A_CLIP', 'A_PROT', 'A_PWR',
]


def main():
    parser = argparse.ArgumentParser(description='统一 9 类 YOLOv8 训练入口')
    parser.add_argument('--config', default=DEFAULT_CONFIG, help='配置文件路径')
    parser.add_argument('--epochs', type=int, default=None, help='覆盖训练轮次 UnFreeze_Epoch')
    parser.add_argument('--batch', type=int, default=None, help='覆盖批次 Unfreeze_batch_size')
    parser.add_argument('--lr', type=float, default=None, help='覆盖初始学习率 Init_lr')
    parser.add_argument('--phi', default=None, choices=['n', 's', 'm'],
                        help='覆盖模型尺寸 phi (n/s/m)')
    parser.add_argument('--model_path', default=None,
                        help='断点续训：指定完整 checkpoint (*_ckpt.pt) 路径，覆盖 model_path')
    parser.add_argument('--qat', action='store_true',
                        help='开启 QAT（量化感知训练，结构化部分量化，运行时强制关闭 fp16）')
    args = parser.parse_args()

    with open(args.config, encoding='utf-8') as f:
        cfg = json.load(f)

    # 命令行覆盖超参数
    if args.epochs is not None:
        cfg['UnFreeze_Epoch'] = args.epochs
    if args.batch is not None:
        cfg['Unfreeze_batch_size'] = args.batch
    if args.lr is not None:
        cfg['Init_lr'] = args.lr
    if args.phi is not None:
        cfg['phi'] = args.phi
    if args.model_path is not None:
        cfg['model_path'] = args.model_path
    if args.qat:
        cfg['qat'] = True
        if cfg.get('fp16', False):
            print('[QAT] CLI 开启 QAT，fp16 将在 train() 内强制关闭。')

    print('=' * 70)
    print('统一 YOLOv8 训练 (9 类: FP + A 合并)')
    print('  配置文件 :', args.config)
    print('  数据集   :', cfg['dataset_name'])
    print('  类别表   :', cfg['classes_path'])
    print('  模型     : yolov8_%s, 输入 %s' % (cfg['phi'], cfg['input_shape']))
    print('  轮次     : %d -> %d' % (cfg['Init_Epoch'], cfg['UnFreeze_Epoch']))
    print('  批次     :', cfg['Unfreeze_batch_size'])
    print('  学习率   :', cfg['Init_lr'])
    print('  QAT      :', '开启' if cfg.get('qat', False) else '关闭（FP32 常规训练）')
    print('  权重输出 :', cfg['save_dir'])
    print('=' * 70)

    train(cfg)


if __name__ == '__main__':
    main()