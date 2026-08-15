"""
分辨率 × 注意力机制 两两搭配消融实验 - 一键运行

实验设计: 分辨率(640/512/416) × 注意力机制(baseline/SE/CS/SC) = 12 个实验

用法:
  python ml/ablation/scripts/run_ablation.py              # 完整运行
  python ml/ablation/scripts/run_ablation.py --infer-only # 仅推理
  python ml/ablation/scripts/run_ablation.py --single 640_baseline  # 单实验
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ABLATION_DIR = PROJECT_ROOT / 'ablation'
CONFIG_DIR = ABLATION_DIR / 'configs'
SCRIPTS_DIR = ABLATION_DIR / 'scripts'

# 实验定义: 分辨率(3) × 注意力(4)
RESOLUTIONS = ['640', '512', '416']
ATTENTIONS = ['baseline', 'se', 'cs', 'sc']

ATTENTION_LABELS = {
    'baseline': 'YOLOV8 (无注意力)',
    'se': 'SE_YOLO',
    'cs': 'C_S_YOLO',
    'sc': 'S_C_YOLO',
}


def get_experiments():
    """返回所有实验ID列表，按分辨率分组"""
    experiments = []
    for res in RESOLUTIONS:
        for attn in ATTENTIONS:
            experiments.append(f'{res}_{attn}')
    return experiments


def get_best_weights(exp_dir):
    exp_dir = Path(exp_dir)
    for name in ['best_epoch_weights.pth', 'model_best_precision_deploy.pt']:
        p = exp_dir / name
        if p.exists():
            return str(p)
    return None


def check_trained(exp_id):
    """检查实验是否已有训练结果"""
    config_path = CONFIG_DIR / f'{exp_id}.json'
    with open(config_path, encoding='utf-8') as f:
        cfg = json.load(f)
    exp_dir = PROJECT_ROOT / cfg['save_dir']
    return get_best_weights(exp_dir) is not None


def run_training(exp_id):
    config_path = CONFIG_DIR / f'{exp_id}.json'
    res, attn = exp_id.split('_', 1)
    print(f'\n{"=" * 70}')
    print(f'[训练] {exp_id}  |  {RESOLUTIONS[RESOLUTIONS.index(res)]}×{RESOLUTIONS[RESOLUTIONS.index(res)]}  +  {ATTENTION_LABELS[attn]}')
    print(f'{"=" * 70}')

    if check_trained(exp_id):
        print(f'[SKIP] {exp_id}: 训练结果已存在, 跳过训练')
        return 0

    t_start = time.time()
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / 'train_ablation.py'), '--config', str(config_path)],
        cwd=str(PROJECT_ROOT))
    t_elapsed = time.time() - t_start

    if result.returncode == 0:
        print(f'[OK] {exp_id} 完成, 耗时 {t_elapsed / 60:.1f} 分钟')
    else:
        print(f'[FAIL] {exp_id} 返回码 {result.returncode}')
    return result.returncode


def run_inference(exp_id, phi='n'):
    config_path = CONFIG_DIR / f'{exp_id}.json'
    with open(config_path, encoding='utf-8') as f:
        cfg = json.load(f)

    exp_dir = PROJECT_ROOT / cfg['save_dir']
    weights = get_best_weights(exp_dir)
    if weights is None:
        print(f'[SKIP] {exp_id}: 无权重文件')
        return

    input_shape = cfg.get('input_shape', [640, 640])
    model_name = cfg.get('model_name', 'YOLOV8')

    print(f'\n  [推理] {exp_id}: input={input_shape} model={model_name}')

    for split in ['val', 'test']:
        subprocess.run([
            sys.executable, str(SCRIPTS_DIR / 'infer_ablation.py'),
            '--split', split,
            '--weights', weights,
            '--phi', phi,
            '--input_shape', str(input_shape[0]), str(input_shape[1]),
            '--model_name', model_name,
            '--outdir', str(exp_dir / 'inference'),
        ], cwd=str(PROJECT_ROOT))


def collect_results():
    """从所有实验的 JSON 结果中读取数据, 生成汇总报告"""
    print(f'\n\n{"=" * 70}')
    print(f'消融实验汇总报告: 分辨率 × 注意力机制')
    print(f'{"=" * 70}')

    results = {}
    for exp_id in get_experiments():
        config_path = CONFIG_DIR / f'{exp_id}.json'
        with open(config_path, encoding='utf-8') as f:
            cfg = json.load(f)

        exp_dir = PROJECT_ROOT / cfg['save_dir']
        weights = get_best_weights(exp_dir)
        has_infer = (exp_dir / 'inference' / 'val_summary.json').exists()

        val_f1 = test_f1 = '-'
        if has_infer:
            for split in ['val', 'test']:
                summary_path = exp_dir / 'inference' / f'{split}_summary.json'
                if summary_path.exists():
                    with open(summary_path, encoding='utf-8') as f:
                        data = json.load(f)
                    if split == 'val':
                        val_f1 = f'{data["total"]["f1"]:.4f}'
                    else:
                        test_f1 = f'{data["total"]["f1"]:.4f}'

        res, attn = exp_id.split('_', 1)
        results[exp_id] = {
            'resolution': res,
            'attention': attn,
            'model_name': cfg['model_name'],
            'input_shape': 'x'.join(map(str, cfg['input_shape'])),
            'weights': Path(weights).name if weights else '-',
            'val_f1': val_f1,
            'test_f1': test_f1,
        }

    # 打印热力图风格表格
    print(f'\n{"=" * 100}')
    print(f'{"F1-Score (val / test)":^98}')
    print(f'{"=" * 100}')
    header = f'{"分辨率":>8}'
    for attn in ATTENTIONS:
        header += f'  {ATTENTION_LABELS[attn]:>24}'
    print(header)
    print('-' * 100)

    for res in RESOLUTIONS:
        row = f'{res:>8}'
        for attn in ATTENTIONS:
            exp_id = f'{res}_{attn}'
            r = results.get(exp_id, {})
            vf = r.get('val_f1', '-')
            tf = r.get('test_f1', '-')
            row += f'  {vf + " / " + tf:>24}'
        print(row)

    # 打印详细对比表
    print(f'\n\n{"=" * 120}')
    print(f'{"详细对比":^118}')
    print(f'{"=" * 120}')
    print(f'{"实验ID":<16} {"模型":<16} {"输入":<10} {"权重":<16} {"val F1":<12} {"test F1":<12}')
    print('-' * 120)
    for exp_id in get_experiments():
        r = results.get(exp_id, {})
        print(f'{exp_id:<16} {r.get("model_name","-"):<16} {r.get("input_shape","-"):<10} '
              f'{r.get("weights","-"):<16} {r.get("val_f1","-"):<12} {r.get("test_f1","-"):<12}')

    print(f'\n结果目录: {ABLATION_DIR / "results"}')
    return results


def main():
    parser = argparse.ArgumentParser(description='消融实验: 分辨率×注意力 两两搭配')
    parser.add_argument('--infer-only', action='store_true', help='仅推理, 跳过训练')
    parser.add_argument('--single', type=str, default=None, help='单实验ID')
    parser.add_argument('--skip-infer', action='store_true', help='训练后跳过推理')
    args = parser.parse_args()

    if args.single:
        experiments = [args.single]
        if args.single not in get_experiments():
            print(f'[ERROR] 未知实验ID: {args.single}')
            print(f'        可用: {", ".join(get_experiments())}')
            sys.exit(1)
    else:
        experiments = get_experiments()

    print(f'分辨率 × 注意力机制 消融实验')
    print(f'  实验总数: {len(experiments)}')
    print(f'  模式: {"仅推理" if args.infer_only else "训练+推理"}')
    print(f'  因子: 分辨率 {RESOLUTIONS} × 注意力 {list(ATTENTION_LABELS.values())}')
    print()

    # 按分辨率分组运行
    current_res = None
    for exp_id in experiments:
        res = exp_id.split('_', 1)[0]
        if res != current_res:
            current_res = res
            print(f'\n{"#" * 70}')
            print(f'# 分辨率 {res}×{res} 组')
            print(f'{"#" * 70}')

        if not args.infer_only:
            ret = run_training(exp_id)
            if ret != 0:
                print(f'[WARN] {exp_id} 训练失败, 跳过')
                continue

        if not args.skip_infer:
            run_inference(exp_id)

    # 汇总报告
    collect_results()

    print(f'\n{"=" * 70}')
    print(f'所有实验完成!')
    print(f'结果目录: {ABLATION_DIR / "results"}')
    print(f'{"=" * 70}')


if __name__ == '__main__':
    main()