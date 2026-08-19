# -*- coding: utf-8 -*-
"""
训练统一 LED 亮灭二分类模型 (TinyConv)，数据来自合并后的 data_merged/。

依赖
----
先运行 prepare_data_merged.py 生成 classifier/data_merged/。

用法（在 ml/ 下运行）:
  python ml/classifier/train_merged.py
  python ml/classifier/train_merged.py --epochs 120 --batch 32 --lr 0.001

输出:
  ml/classifier/weights/best_tinyconv_merged.pth
  ml/classifier/weights/best_tinyconv_merged.onnx
"""
import argparse
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader

PROJECT_ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(PROJECT_ROOT))

from classifier.model import TinyConv, MicroConv

DATA_DIR = PROJECT_ROOT / 'classifier' / 'data_merged'
OUTPUT_DIR = PROJECT_ROOT / 'classifier' / 'weights'
INPUT_SIZE = 32


class LEDDataset(Dataset):
    """LED ROI 二分类数据集（data_merged 结构）。"""

    def __init__(self, root, split, augment=False):
        self.images = []
        self.labels = []
        for label_idx, label_name in enumerate(['L', 'H']):
            dir_path = root / split / label_name
            if not dir_path.exists():
                continue
            for fname in sorted(dir_path.iterdir()):
                if fname.suffix.lower() in ('.png', '.jpg', '.jpeg'):
                    self.images.append(str(fname))
                    self.labels.append(label_idx)
        self.augment = augment

    def __len__(self):
        return len(self.images)

    def __getitem__(self, idx):
        img = cv2.imread(self.images[idx])
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        img = cv2.resize(img, (INPUT_SIZE, INPUT_SIZE), interpolation=cv2.INTER_AREA)
        img = img.astype(np.float32) / 255.0

        if self.augment:
            brightness = 1.0 + np.random.uniform(-0.15, 0.15)
            contrast = 1.0 + np.random.uniform(-0.15, 0.15)
            img = np.clip((img - 0.5) * contrast + 0.5 + (brightness - 1.0), 0, 1)
            if np.random.random() > 0.5:
                img = np.fliplr(img).copy()
            if np.random.random() > 0.5:
                noise = np.random.randn(*img.shape) * 0.02
                img = np.clip(img + noise, 0, 1)

        img = np.transpose(img, (2, 0, 1))
        return torch.from_numpy(img).float(), self.labels[idx]


def train_one_epoch(model, loader, criterion, optimizer, device):
    model.train()
    total_loss = 0
    correct = 0
    total = 0
    for inputs, labels in loader:
        inputs, labels = inputs.to(device), labels.to(device)
        optimizer.zero_grad()
        outputs = model(inputs)
        loss = criterion(outputs, labels)
        loss.backward()
        optimizer.step()
        total_loss += loss.item() * inputs.size(0)
        _, preds = torch.max(outputs, 1)
        correct += (preds == labels).sum().item()
        total += inputs.size(0)
    return total_loss / total, correct / total


@torch.no_grad()
def evaluate(model, loader, criterion, device):
    model.eval()
    total_loss = 0
    correct = 0
    total = 0
    for inputs, labels in loader:
        inputs, labels = inputs.to(device), labels.to(device)
        outputs = model(inputs)
        loss = criterion(outputs, labels)
        total_loss += loss.item() * inputs.size(0)
        _, preds = torch.max(outputs, 1)
        correct += (preds == labels).sum().item()
        total += inputs.size(0)
    return total_loss / total, correct / total


def main():
    parser = argparse.ArgumentParser(description='统一 TinyConv 二分类训练')
    parser.add_argument('--model', default='tinyconv', choices=['tinyconv', 'microconv'])
    parser.add_argument('--epochs', type=int, default=100)
    parser.add_argument('--batch', type=int, default=32)
    parser.add_argument('--lr', type=float, default=0.001)
    parser.add_argument('--weight-decay', type=float, default=1e-4)
    args = parser.parse_args()

    if not DATA_DIR.exists():
        raise SystemExit('未找到 %s，请先运行 ml/classifier/prepare_data_merged.py' % DATA_DIR)

    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print('设备: %s' % device)
    print('输入尺寸: %d×%d' % (INPUT_SIZE, INPUT_SIZE))

    train_dataset = LEDDataset(DATA_DIR, 'train', augment=True)
    val_dataset = LEDDataset(DATA_DIR, 'val', augment=False)
    test_dataset = LEDDataset(DATA_DIR, 'test', augment=False)

    train_loader = DataLoader(train_dataset, batch_size=args.batch, shuffle=True, num_workers=0)
    val_loader = DataLoader(val_dataset, batch_size=args.batch, shuffle=False, num_workers=0)
    test_loader = DataLoader(test_dataset, batch_size=args.batch, shuffle=False, num_workers=0)

    print('训练集: %d (L:%d H:%d)' % (len(train_dataset), sum(1 for l in train_dataset.labels if l == 0), sum(1 for l in train_dataset.labels if l == 1)))
    print('验证集: %d (L:%d H:%d)' % (len(val_dataset), sum(1 for l in val_dataset.labels if l == 0), sum(1 for l in val_dataset.labels if l == 1)))
    print('测试集: %d (L:%d H:%d)' % (len(test_dataset), sum(1 for l in test_dataset.labels if l == 0), sum(1 for l in test_dataset.labels if l == 1)))

    model = TinyConv(in_channels=3, num_classes=2) if args.model == 'tinyconv' else MicroConv(in_channels=3, num_classes=2)
    model = model.to(device)
    print('模型: %s, 参数量: %s' % (args.model, format(sum(p.numel() for p in model.parameters()), ',')))

    n_l = sum(1 for l in train_dataset.labels if l == 0)
    n_h = sum(1 for l in train_dataset.labels if l == 1)
    weight = torch.tensor([1.0, n_l / max(n_h, 1)], device=device)
    print('类别权重: L=%.2f, H=%.2f' % (weight[0], weight[1]))

    criterion = nn.CrossEntropyLoss(weight=weight)
    optimizer = optim.Adam(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    scheduler = optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode='max', factor=0.5, patience=8)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    save_path = OUTPUT_DIR / f'best_{args.model}_merged.pth'

    best_val_acc = 0.0
    patience = 5
    wait = 0

    print()
    print('=' * 60)
    print('开始训练统一分类器')
    print('=' * 60)

    for epoch in range(1, args.epochs + 1):
        train_loss, train_acc = train_one_epoch(model, train_loader, criterion, optimizer, device)
        val_loss, val_acc = evaluate(model, val_loader, criterion, device)
        scheduler.step(val_acc)

        print('  epoch %3d/%d  train_loss=%.4f train_acc=%.4f  val_loss=%.4f val_acc=%.4f  lr=%.6f'
              % (epoch, args.epochs, train_loss, train_acc, val_loss, val_acc, optimizer.param_groups[0]['lr']))

        if val_acc > best_val_acc + 1e-5:
            best_val_acc = val_acc
            wait = 0
            torch.save(model.state_dict(), str(save_path))
            print('    → 保存最佳模型 (val_acc=%.4f)' % val_acc)
        else:
            wait += 1
            if wait >= patience:
                print('  Early stopping @ epoch %d' % epoch)
                break

    model.load_state_dict(torch.load(str(save_path), map_location=device))
    test_loss, test_acc = evaluate(model, test_loader, criterion, device)
    print()
    print('=' * 60)
    print('统一分类器测试集: loss=%.4f  acc=%.4f' % (test_loss, test_acc))
    print('=' * 60)

    try:
        model.eval()
        dummy = torch.randn(1, 3, INPUT_SIZE, INPUT_SIZE, device=device)
        onnx_path = str(OUTPUT_DIR / f'best_{args.model}_merged.onnx')
        torch.onnx.export(model, dummy, onnx_path, input_names=['input'], output_names=['output'], opset_version=11)
        print('ONNX 模型已导出: %s' % onnx_path)
    except Exception as e:
        print('ONNX 导出失败: %s' % e)

    print('完成! 最佳模型: %s' % save_path)


if __name__ == '__main__':
    main()