# -*- coding: utf-8 -*-
"""
合并 FP / A 两系列 LED ROI 数据，生成统一二分类数据集。

背景
----
FP 系列 ROI 现存于 archive/classifier_data/A/（classifier/data/ 已清理，FP 标注无
H/L 无法重建），A 系列 ROI 在 classifier/data_a/。本脚本把两者合并到
classifier/data_merged/（train/val/test × L/H 结构），供统一 TinyConv 训练使用。
ROI 文件名自带系列前缀（fp*/frame_* / a*），两源之间不会冲突。

用法（在 ml/ 下运行）:
  python ml/classifier/prepare_data_merged.py

输出:
  ml/classifier/data_merged/
      train/L/  train/H/
      val/L/    val/H/
      test/L/   test/H/
"""
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CLASSIFIER_DIR = PROJECT_ROOT / 'classifier'

SOURCES = [
    # FP 系列 ROI 已归档（classifier/data/ 被清理且无法重建，故从 archive 取回）
    ('FP', PROJECT_ROOT.parent / 'archive' / 'classifier_data' / 'A'),
    ('A',  CLASSIFIER_DIR / 'data_a'),
]
MERGED_DIR = CLASSIFIER_DIR / 'data_merged'


def main():
    # 清空并重建目标，保证幂等
    if MERGED_DIR.exists():
        shutil.rmtree(MERGED_DIR)
    for split in ('train', 'val', 'test'):
        for label in ('L', 'H'):
            (MERGED_DIR / split / label).mkdir(parents=True, exist_ok=True)

    total = {'L': 0, 'H': 0}
    for series, src in SOURCES:
        if not src.exists():
            print('[WARN] ROI 数据不存在，跳过 %s: %s' % (series, src))
            continue
        for split in ('train', 'val', 'test'):
            for label in ('L', 'H'):
                src_dir = src / split / label
                if not src_dir.exists():
                    continue
                files = sorted(src_dir.glob('*.png'))
                for f in files:
                    shutil.copy2(f, MERGED_DIR / split / label / f.name)
                total[label] += len(files)
                print('  %s/%s/%s: %d' % (series, split, label, len(files)))
    print()
    print('=' * 60)
    print('统一 ROI 数据集生成完成 -> %s' % MERGED_DIR)
    print('  L: %d, H: %d, 合计: %d' % (total['L'], total['H'], total['L'] + total['H']))
    print('=' * 60)


if __name__ == '__main__':
    main()