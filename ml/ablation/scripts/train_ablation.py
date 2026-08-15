"""
消融实验训练脚本 - 动态切换模型变体 + 输入分辨率

通过 importlib 动态加载目标模型, patch sys.modules 使 train.py 的
`from model.YOLOV8 import YoloBody` 获取到目标模型, 无需修改现有代码。

用法:
  python ml/ablation/scripts/train_ablation.py --config path/to/config.json
"""
import importlib
import json
import os
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def load_and_patch_model(model_name, phi, pretrained, input_shape):
    module_path = f'model.{model_name}'
    try:
        target_module = importlib.import_module(module_path)
    except ModuleNotFoundError:
        print(f'[ERROR] 无法加载模型模块 {module_path}')
        print(f'        可用: YOLOV8, SE_YOLO, C_S_YOLO, S_C_YOLO')
        sys.exit(1)

    if not hasattr(target_module, 'YoloBody'):
        print(f'[ERROR] {module_path} 不包含 YoloBody 类')
        sys.exit(1)

    try:
        dummy = target_module.YoloBody(
            input_shape=tuple(input_shape),
            num_classes=7,
            phi=phi,
            pretrained=False
        )
        params = sum(p.numel() for p in dummy.parameters())
        print(f'[INFO] 模型 {model_name} (phi={phi}): 参数量 {params:,}')
        del dummy
    except Exception as e:
        print(f'[WARN] 实例化检查失败: {e}')

    # Patch: 使 model.YOLOV8 指向目标模块
    sys.modules['model.YOLOV8'] = target_module
    print(f'[INFO] 已加载: {module_path} → model.YOLOV8')


def main():
    if len(sys.argv) < 2 or '--config' not in sys.argv:
        print('用法: python train_ablation.py --config path/to/config.json')
        sys.exit(1)

    config_idx = sys.argv.index('--config') + 1
    config_path = sys.argv[config_idx]

    with open(config_path, encoding='utf-8') as f:
        cfg = json.load(f)

    model_name = cfg.get('model_name', 'YOLOV8')
    phi = cfg.get('phi', 'n')
    pretrained = cfg.get('pretrained', True)
    input_shape = cfg.get('input_shape', [640, 640])
    save_dir = cfg.get('save_dir', 'ablation/results')

    abs_save_dir = os.path.join(PROJECT_ROOT, save_dir)
    os.makedirs(abs_save_dir, exist_ok=True)

    print('=' * 70)
    print(f'消融实验训练')
    print(f'  模型: {model_name} (phi={phi})')
    print(f'  输入: {input_shape}')
    print(f'  配置: {config_path}')
    print(f'  输出: {save_dir}')
    print('=' * 70)

    load_and_patch_model(model_name, phi, pretrained, input_shape)

    from train import train

    t_start = time.time()
    train(cfg)
    t_elapsed = time.time() - t_start

    print(f'\n[完成] 耗时: {t_elapsed / 60:.1f} 分钟')
    print(f'结果: {abs_save_dir}')


if __name__ == '__main__':
    main()