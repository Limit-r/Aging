# -*- coding: utf-8 -*-
"""
集中配置文件 - YOLOv8 训练参数管理 (FP 项目专用)
所有训练、预测、评估参数在此统一管理。
"""
import os
import json
import copy

# ============================================================
# 数据集定义 (仅 FP)
# ============================================================
DATASETS = {
    'FP': {
        'display_name': 'FP 系列 LED 检测',
        'classes_path': r'datasets\FP\label.txt',
        'train_annotation_path': 'datasets/FP/2025_train.txt',
        'val_annotation_path': 'datasets/FP/2025_val.txt',
        'label_list': ['FP_SIG_area', 'FP_PWR_area', 'FP_VPL', 'FP_CPL', 'FP_PWR'],
        'default_phi': 'n',
        'save_dir': 'weights/FP',
    },
}

# ============================================================
# 默认训练参数
# ============================================================
DEFAULT_CONFIG = {
    # --- 数据集 ---
    'dataset_name': 'FP',

    # --- 运行环境 ---
    'Cuda': True,
    'seed': 11,
    'distributed': False,
    'sync_bn': False,
    'fp16': True,

    # --- 模型参数 ---
    'phi': 'n',
    'input_shape': [512, 512],
    'model_path': '',
    'pretrained': True,

    # --- 数据增强 ---
    'mosaic': True,
    'mosaic_prob': 0.05,
    'mixup': True,
    'mixup_prob': 0.05,
    'special_aug_ratio': 0.3,
    'label_smoothing': 0.015,

    # --- 冻结阶段 ---
    'Init_Epoch': 0,
    'Freeze_Epoch': 0,
    'Freeze_batch_size': 2,
    'Freeze_Train': False,

    # --- 解冻阶段 ---
    'UnFreeze_Epoch': 80,
    'Unfreeze_batch_size': 2,

    # --- 学习率与优化器 ---
    'Init_lr': 0.01,
    'Min_lr': 0.00001,
    'optimizer_type': 'sgd',
    'momentum': 0.9,
    'weight_decay': 0.0005,
    'lr_decay_type': 'cos',

    # --- 保存与评估 ---
    'save_period': 10,
    'save_dir': 'weights/FP',
    'eval_flag': True,
    'eval_period': 2,
    'num_workers': 2,

    # --- 梯度与阈值 ---
    'gradient_clip_norm': 7.0,
    'min_recall_threshold': 0.85,
    'min_f1_threshold': 0.7,
    'export_deploy_model': True,

    # --- 早停机制 ---
    'early_stop_enabled': True,
    'early_stop_patience': 5,
    'early_stop_metric': 'val_loss',

    # --- Checkpoint 命名偏移 ---
    'epoch_offset': 0,

    # --- 数据标注路径 ---
    'train_annotation_path': 'datasets/FP/2025_train.txt',
    'val_annotation_path': 'datasets/FP/2025_val.txt',
    'classes_path': r'datasets\FP\label.txt',
}


def get_config(dataset_name=None):
    """
    获取当前配置字典
    """
    cfg = copy.deepcopy(DEFAULT_CONFIG)

    if dataset_name is None:
        dataset_name = cfg['dataset_name']

    if dataset_name in DATASETS:
        ds = DATASETS[dataset_name]
        cfg['dataset_name'] = dataset_name
        cfg['classes_path'] = ds['classes_path']
        cfg['train_annotation_path'] = ds['train_annotation_path']
        cfg['val_annotation_path'] = ds['val_annotation_path']
        cfg['phi'] = ds['default_phi']
        cfg['save_dir'] = ds.get('save_dir', 'logs')

    return cfg


def save_config_to_file(cfg, filepath='config_runtime.json'):
    """将配置保存为 JSON 文件"""
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=4, ensure_ascii=False)


def load_config_from_file(filepath='config_runtime.json'):
    """从 JSON 文件加载配置"""
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


def get_dataset_label_list(dataset_name):
    """获取数据集的标签列表"""
    if dataset_name in DATASETS:
        return DATASETS[dataset_name]['label_list']
    return []


def list_datasets():
    """列出所有可用数据集"""
    return list(DATASETS.keys())