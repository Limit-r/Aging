# -*- coding: utf-8 -*-
"""
A 系列推理验证脚本 (7 类: A_CLIP_H / A_CLIP_L / A_PROT_H / A_PROT_L / A_PWR_H / A_SIG_H / A_area)

核心检测/评估逻辑复用 ml/utils/det_eval.py (load_model / run_val / run_image)。

用法:
  python detect/infer_a.py
  python detect/infer_a.py --image path/to/image.jpg
"""
import argparse
import os
import sys
from pathlib import Path

import torch

# 模型/训练代码根 = ml/  (infer_a.py -> detect -> 项目根, ml/ 下含 model/utils/datasets)
PROJECT_ROOT = Path(__file__).resolve().parents[1]          # d:\Aging
ML_ROOT = PROJECT_ROOT / 'ml'                               # 模型/训练代码根
sys.path.insert(0, str(ML_ROOT))

from utils.det_eval import load_model, resolve_font, run_image, run_val  # noqa: E402
from utils.utils import get_classes            # noqa: E402
from utils.utils_bbox import DecodeBox         # noqa: E402

# A 系列权重路径
A_WEIGHTS = str(ML_ROOT / 'weights' / 'A' / 'best_epoch_weights.pth')
A_DEPLOY  = str(ML_ROOT / 'weights' / 'A' / 'model_best_precision_deploy.pt')
A_LABELS  = str(ML_ROOT / 'datasets' / 'A' / 'label.txt')
A_OUTDIR  = str(PROJECT_ROOT / 'detect' / 'outputs' / 'A')
A_VAL_TXT = str(ML_ROOT / 'datasets' / 'A' / '2025_val.txt')
A_TEST_TXT = str(ML_ROOT / 'datasets' / 'A' / '2025_test.txt')

# 权重缺失时附加提示
TRAIN_HINT = '        请先用 ml/train/train_a.py 完成训练。'


def run_val_set(args, yolo, decodebox, class_names, num_classes, input_shape, device):
    """对 2025_val.txt / 2025_test.txt 全量集推理, 输出每图 + 全局指标。"""
    split_txt = args.test_txt if args.split == 'test' else args.val_txt
    run_val(
        split_txt,
        Path(args.outdir) / args.split,
        yolo, decodebox, class_names, num_classes, input_shape, device,
        font_path=resolve_font(ML_ROOT),
        conf=args.conf, nms=args.nms, iou_match=args.iou_match,
        tag='A 系列 %s集推理' % args.split,
        base_dir=str(PROJECT_ROOT),
    )


def main():
    parser = argparse.ArgumentParser(description='A 系列推理验证')
    parser.add_argument('--image', type=str, default=None, help='单图推理路径')
    parser.add_argument('--split', choices=['val', 'test'], default='val')
    parser.add_argument('--weights', default=A_WEIGHTS)
    parser.add_argument('--deploy', default=A_DEPLOY)
    parser.add_argument('--labels', default=A_LABELS)
    parser.add_argument('--outdir', default=A_OUTDIR)
    parser.add_argument('--val_txt', default=A_VAL_TXT)
    parser.add_argument('--test_txt', default=A_TEST_TXT)
    parser.add_argument('--phi', default='n')
    parser.add_argument('--conf', type=float, default=0.25)
    parser.add_argument('--nms', type=float, default=0.45)
    parser.add_argument('--iou_match', type=float, default=0.5)
    args = parser.parse_args()

    class_names, num_classes = get_classes(args.labels)
    print('类别:', class_names, '数量:', num_classes)

    input_shape = (512, 512)
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print('设备:', device)

    # 优先用 deploy 模型
    weights_path = args.deploy if os.path.exists(args.deploy) else args.weights
    if not os.path.exists(weights_path):
        print('[ERROR] 权重不存在: %s' % weights_path)
        print(TRAIN_HINT)
        sys.exit(1)

    yolo = load_model(weights_path, num_classes, args.phi, input_shape, device)
    decodebox = DecodeBox(num_classes=num_classes, input_shape=input_shape)
    print('模型加载完成:', weights_path)

    if args.image:
        run_image(args.image, args.outdir, yolo, decodebox, class_names, num_classes,
                  input_shape, device, font_path=resolve_font(ML_ROOT),
                  conf=args.conf, nms=args.nms, label='A')
    else:
        run_val_set(args, yolo, decodebox, class_names, num_classes, input_shape, device)


if __name__ == '__main__':
    main()