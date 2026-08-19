"""
消融实验推理评估 - 支持不同模型/输入尺寸, 输出 JSON 结果

核心检测/评估逻辑复用 ml/utils/det_eval.py (load_model / run_val / run_image),
差异点: 通过 --model_name 动态 importlib 加载模型变体。

用法:
  python ml/ablation/scripts/infer_ablation.py \
      --split val --weights path/to/weights.pth \
      --phi n --input_shape 640 640 \
      --model_name YOLOV8 --outdir path/to/output
"""
import argparse
import importlib
import json
import os
import sys
from pathlib import Path

import torch

ML_ROOT = Path(__file__).resolve().parents[2]               # d:\Aging\ml
PROJECT_ROOT = ML_ROOT.parent                                # d:\Aging
sys.path.insert(0, str(ML_ROOT))

from utils.det_eval import run_val                              # noqa: E402
from utils.utils_bbox import DecodeBox                           # noqa: E402
from utils.utils import get_classes                              # noqa: E402

SPLIT_FILES = {
    'val':  str(ML_ROOT / 'datasets' / 'FP' / '2025_val.txt'),
    'test': str(ML_ROOT / 'datasets' / 'FP' / '2025_test.txt'),
}
DEFAULT_LABELS = str(ML_ROOT / 'datasets' / 'FP' / 'label.txt')


def load_model(weights, num_classes, phi, input_shape, device, model_name):
    """按 model_name 动态 importlib 加载模型变体。"""
    module_path = f'model.{model_name}'
    try:
        target_module = importlib.import_module(module_path)
    except ModuleNotFoundError:
        print(f'[ERROR] 无法加载模型: {module_path}')
        sys.exit(1)
    yolo = target_module.YoloBody(input_shape, num_classes, phi, pretrained=False)
    state = torch.load(weights, map_location=device, weights_only=False)
    if isinstance(state, dict) and 'model' in state:
        yolo.load_state_dict(state['model'])
    else:
        yolo.load_state_dict(state)
    return yolo.to(device).eval()


def main():
    parser = argparse.ArgumentParser(description='消融实验推理评估')
    parser.add_argument('--split', choices=['val', 'test'], default='val')
    parser.add_argument('--weights', required=True)
    parser.add_argument('--labels', default=DEFAULT_LABELS)
    parser.add_argument('--outdir', required=True)
    parser.add_argument('--phi', default='n')
    parser.add_argument('--input_shape', nargs=2, type=int, default=[640, 640])
    parser.add_argument('--model_name', default='YOLOV8')
    parser.add_argument('--conf', type=float, default=0.25)
    parser.add_argument('--nms', type=float, default=0.45)
    parser.add_argument('--iou_match', type=float, default=0.5)
    args = parser.parse_args()

    input_shape = tuple(args.input_shape)
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    class_names, num_classes = get_classes(args.labels)

    print(f'[INFO] {args.model_name} phi={args.phi} input={input_shape} split={args.split}')
    print(f'[INFO] 权重: {args.weights}')

    yolo = load_model(args.weights, num_classes, args.phi, input_shape, device, args.model_name)
    decodebox = DecodeBox(num_classes=num_classes, input_shape=input_shape)

    summary = run_val(
        SPLIT_FILES[args.split],
        Path(args.outdir) / args.split,
        yolo, decodebox, class_names, num_classes, input_shape, device,
        conf=args.conf, nms=args.nms, iou_match=args.iou_match,
        tag=f'消融 {args.model_name} {args.split}集',
        base_dir=str(ML_ROOT),
    )

    # 包装实验元信息后落盘 JSON
    result = {
        'experiment': {
            'model_name': args.model_name,
            'phi': args.phi,
            'input_shape': list(input_shape),
        },
        'split': args.split,
        **summary,
    }
    summary_path = Path(args.outdir) / f'{args.split}_summary.json'
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f'结果 JSON: {summary_path}')


if __name__ == '__main__':
    main()