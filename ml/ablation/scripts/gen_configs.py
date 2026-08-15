"""
生成消融实验配置: 分辨率(3) × 注意力机制(4) × phi=n = 12 个实验
"""
import json
import os

CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'configs')
os.makedirs(CONFIG_DIR, exist_ok=True)

# ============================================================
# 实验因子
# ============================================================
RESOLUTIONS = {
    '640': [640, 640],
    '512': [512, 512],
    '416': [416, 416],
}
ATTENTIONS = {
    'baseline': 'YOLOV8',   # 无注意力
    'se':       'SE_YOLO',   # SE 注意力
    'cs':       'C_S_YOLO',  # SE + CBAM
    'sc':       'S_C_YOLO',  # ECA/SE + Dropout
}

# 基配置 (与 config_fp_train_v3.json 一致)
BASE_CFG = {
    "dataset_name": "FP_v2",
    "Cuda": True,
    "seed": 42,
    "distributed": False,
    "sync_bn": False,
    "fp16": True,
    "phi": "n",
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
    "train_annotation_path": "datasets/FP/2025_train.txt",
    "val_annotation_path": "datasets/FP/2025_val.txt",
    "classes_path": "datasets\\FP\\label.txt",
}

# 生成所有配置
generated = []
for res_name, input_shape in RESOLUTIONS.items():
    for attn_name, model_name in ATTENTIONS.items():
        exp_id = f'{res_name}_{attn_name}'
        cfg = BASE_CFG.copy()
        cfg['model_name'] = model_name
        cfg['input_shape'] = input_shape
        cfg['save_dir'] = f'ablation/results/{exp_id}'

        config_path = os.path.join(CONFIG_DIR, f'{exp_id}.json')
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, indent=4, ensure_ascii=False)

        generated.append(exp_id)

# 打印汇总
print(f'已生成 {len(generated)} 个配置:')
print('=' * 70)
print(f'{"实验ID":<18} {"模型":<12} {"输入":<10}')
print('-' * 70)
for exp_id in generated:
    res, attn = exp_id.split('_', 1)
    model_name = ATTENTIONS[attn]
    input_sz = 'x'.join(map(str, RESOLUTIONS[res]))
    print(f'{exp_id:<18} {model_name:<12} {input_sz:<10}')
print('=' * 70)
print(f'配置目录: {CONFIG_DIR}')