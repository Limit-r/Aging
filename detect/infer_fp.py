# -*- coding: utf-8 -*-
"""
FP 推理验证脚本 (5 类: FP_SIG_area / FP_PWR_area / FP_VPL / FP_CPL / FP_PWR)

对 2025_val.txt 中的图片加载训练权重做推理, 输出每张图检测数 / IoU@0.5 命中 / 全局
Recall / Precision / F1, 并保存带预测框(绿)+真值框(红)的可视化结果。

核心检测/评估逻辑复用 ml/utils/det_eval.py (load_model / run_val / run_image)。

用法
----
  python detect/infer_fp.py
  python detect/infer_fp.py --weights path/to/best.pth --conf 0.05
  python detect/infer_fp.py --image path/to/single.jpg
"""
import argparse
import os
import sys
from pathlib import Path

import torch

# 模型/训练代码根 = ml/  (infer_fp.py -> detect -> 项目根, ml/ 下含 model/utils/datasets)
PROJECT_ROOT = Path(__file__).resolve().parents[1]          # d:\Aging
ML_ROOT = PROJECT_ROOT / 'ml'                               # 模型/训练代码根
sys.path.insert(0, str(ML_ROOT))

from utils.det_eval import load_model, resolve_font, run_image, run_val  # noqa: E402
from utils.utils import get_classes            # noqa: E402
from utils.utils_bbox import DecodeBox         # noqa: E402

DEFAULT_WEIGHTS = str(ML_ROOT / 'deploy' / 'yolo_best_epoch_weights.pth')
DEFAULT_DEPLOY  = str(ML_ROOT / 'deploy' / 'yolo_best_deploy.pt')
DEFAULT_LABELS  = str(ML_ROOT / 'deploy' / 'label_merged.txt')
DEFAULT_OUTDIR  = str(PROJECT_ROOT / 'detect' / 'outputs' / 'FP_v3_5classes_v4')
# split -> txt 路径
SPLIT_FILES = {
    'val':  str(ML_ROOT / 'datasets' / 'FP' / '2025_val.txt'),
    'test': str(ML_ROOT / 'datasets' / 'FP' / '2025_test.txt'),
}


def run_val_set(args, yolo, decodebox, class_names, num_classes, input_shape, device):
    """对 2025_val.txt / 2025_test.txt 全量集推理, 输出每图 + 全局指标。"""
    run_val(
        SPLIT_FILES[args.split],
        Path(args.outdir) / args.split,
        yolo, decodebox, class_names, num_classes, input_shape, device,
        font_path=resolve_font(ML_ROOT),
        conf=args.conf, nms=args.nms, iou_match=args.iou_match,
        tag='FP %s集推理' % args.split,
        base_dir=str(ML_ROOT),
    )


def main():
    parser = argparse.ArgumentParser(description='FP 推理验证 (YoloBody, 7 类)')
    parser.add_argument('--image', type=str, default=None, help='单图推理路径; 省略则跑数据集评估')
    parser.add_argument('--split', choices=['val', 'test'], default='val',
                        help='评估哪个数据集 (val/test, 默认 val)')
    parser.add_argument('--weights', default=DEFAULT_WEIGHTS)
    parser.add_argument('--deploy', default=DEFAULT_DEPLOY)
    parser.add_argument('--labels', default=DEFAULT_LABELS)
    parser.add_argument('--outdir', default=DEFAULT_OUTDIR)
    parser.add_argument('--phi', default='n')
    parser.add_argument('--conf', type=float, default=0.25, help='置信度阈值 (默认 0.25)')
    parser.add_argument('--nms', type=float, default=0.45)
    parser.add_argument('--iou_match', type=float, default=0.5)
    args = parser.parse_args()

    class_names, num_classes = get_classes(args.labels)
    print('类别:', class_names, '数量:', num_classes)

    input_shape = (512, 512)
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print('设备:', device)

    weights_path = args.deploy if os.path.exists(args.deploy) else args.weights
    if not os.path.exists(weights_path):
        print('[ERROR] 权重不存在: %s' % weights_path)
        print('        请先用 ml/train/train_merged.py 训练并部署到 ml/deploy/。')
        sys.exit(1)

    yolo = load_model(weights_path, num_classes, args.phi, input_shape, device)
    decodebox = DecodeBox(num_classes=num_classes, input_shape=input_shape)
    print('模型加载完成:', weights_path)

    if args.image:
        run_image(args.image, args.outdir, yolo, decodebox, class_names, num_classes,
                  input_shape, device, font_path=resolve_font(ML_ROOT),
                  conf=args.conf, nms=args.nms, label='FP')
    else:
        run_val_set(args, yolo, decodebox, class_names, num_classes, input_shape, device)


if __name__ == '__main__':
    main()