"""
训练 LED 亮灭二分类模型 (TinyConv) - 使用固定类别权重。

旧模型偏向 L 类 (H 召回率仅 4.6%)，导致 FP04 视频结果稳定但不够准确。
新模型更平衡但准确率 96%，在 FP04 上产生不同结果。

本脚本尝试不同 H 权重找到最佳平衡点。
"""
import argparse
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from classifier.model import TinyConv, MicroConv

DATA_DIR = PROJECT_ROOT / 'classifier' / 'data'
OUTPUT_DIR = PROJECT_ROOT / 'classifier' / 'weights'
INPUT_SIZE = 32


class LEDDataset(Dataset):
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
            brightness = 1.0 + np.random.uniform(-0.1, 0.1)
            contrast = 1.0 + np.random.uniform(-0.1, 0.1)
            img = np.clip((img - 0.5) * contrast + 0.5 + (brightness - 1.0), 0, 1)
            if np.random.random() > 0.5:
                img = np.fliplr(img).copy()
            if np.random.random() > 0.5:
                noise = np.random.randn(*img.shape) * 0.01
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
    cm = [[0, 0], [0, 0]]
    for inputs, labels in loader:
        inputs, labels = inputs.to(device), labels.to(device)
        outputs = model(inputs)
        loss = criterion(outputs, labels)
        total_loss += loss.item() * inputs.size(0)
        _, preds = torch.max(outputs, 1)
        correct += (preds == labels).sum().item()
        total += inputs.size(0)
        for t, p in zip(labels.cpu().numpy(), preds.cpu().numpy()):
            cm[t][p] += 1
    return total_loss / total, correct / total, cm


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', default='tinyconv', choices=['tinyconv', 'microconv'])
    parser.add_argument('--epochs', type=int, default=150)
    parser.add_argument('--batch', type=int, default=32)
    parser.add_argument('--lr', type=float, default=0.001)
    parser.add_argument('--weight-decay', type=float, default=1e-4)
    parser.add_argument('--h-weight', type=float, default=None,
                        help='H 类权重 (默认自动计算)')
    parser.add_argument('--augment', action='store_true', default=True,
                        help='使用数据增强')
    parser.add_argument('--no-augment', action='store_true',
                        help='禁用数据增强')
    args = parser.parse_args()

    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    use_augment = args.augment and not args.no_augment

    train_dataset = LEDDataset(DATA_DIR, 'train', augment=use_augment)
    val_dataset = LEDDataset(DATA_DIR, 'val', augment=False)
    test_dataset = LEDDataset(DATA_DIR, 'test', augment=False)

    train_loader = DataLoader(train_dataset, batch_size=args.batch, shuffle=True, num_workers=0)
    val_loader = DataLoader(val_dataset, batch_size=args.batch, shuffle=False, num_workers=0)
    test_loader = DataLoader(test_dataset, batch_size=args.batch, shuffle=False, num_workers=0)

    n_l = sum(1 for l in train_dataset.labels if l == 0)
    n_h = sum(1 for l in train_dataset.labels if l == 1)

    print(f'设备: {device}')
    print(f'输入尺寸: {INPUT_SIZE}×{INPUT_SIZE}')
    print(f'数据增强: {use_augment}')
    print(f'训练集: {len(train_dataset)}  (L:{n_l} H:{n_h})')
    print(f'验证集: {len(val_dataset)}  (L:{sum(1 for l in val_dataset.labels if l==0)} H:{sum(1 for l in val_dataset.labels if l==1)})')
    print(f'测试集: {len(test_dataset)}  (L:{sum(1 for l in test_dataset.labels if l==0)} H:{sum(1 for l in test_dataset.labels if l==1)})')

    if args.model == 'tinyconv':
        model = TinyConv(in_channels=3, num_classes=2)
    else:
        model = MicroConv(in_channels=3, num_classes=2)
    model = model.to(device)
    print(f'模型: {args.model}, 参数量: {sum(p.numel() for p in model.parameters()):,}')

    # 类别权重
    if args.h_weight is not None:
        weight = torch.tensor([1.0, args.h_weight], device=device)
        print(f'类别权重: L=1.00, H={args.h_weight:.2f} (固定)')
    else:
        weight = torch.tensor([1.0, n_l / max(n_h, 1)], device=device)
        print(f'类别权重: L={weight[0]:.2f}, H={weight[1]:.2f} (自动)')

    criterion = nn.CrossEntropyLoss(weight=weight)
    optimizer = optim.Adam(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    scheduler = optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode='max', factor=0.5, patience=8)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    best_val_acc = 0.0
    best_cm = None
    patience = 25
    wait = 0

    print()
    print('=' * 60)
    print('开始训练')
    print('=' * 60)

    for epoch in range(1, args.epochs + 1):
        train_loss, train_acc = train_one_epoch(model, train_loader, criterion, optimizer, device)
        val_loss, val_acc, val_cm = evaluate(model, val_loader, criterion, device)
        scheduler.step(val_acc)

        print(f'  epoch {epoch:3d}/{args.epochs}  '
              f'train_loss={train_loss:.4f} train_acc={train_acc:.4f}  '
              f'val_loss={val_loss:.4f} val_acc={val_acc:.4f}  '
              f'lr={optimizer.param_groups[0]["lr"]:.6f}')

        if val_acc > best_val_acc + 1e-5:
            best_val_acc = val_acc
            best_cm = val_cm
            wait = 0
            torch.save(model.state_dict(), str(OUTPUT_DIR / f'best_{args.model}.pth'))
            print(f'    → 保存最佳模型 (val_acc={val_acc:.4f})')
        else:
            wait += 1
            if wait >= patience:
                print(f'  Early stopping @ epoch {epoch}')
                break

    # 测试集评估
    model.load_state_dict(torch.load(str(OUTPUT_DIR / f'best_{args.model}.pth'), map_location=device))
    test_loss, test_acc, test_cm = evaluate(model, test_loader, criterion, device)

    print()
    print('=' * 60)
    print(f'测试集: loss={test_loss:.4f}  acc={test_acc:.4f}')
    print(f'混淆矩阵:')
    print(f'             预测 L    预测 H')
    print(f'  真实 L:    {test_cm[0][0]:6d}    {test_cm[0][1]:6d}')
    print(f'  真实 H:    {test_cm[1][0]:6d}    {test_cm[1][1]:6d}')
    
    pL = test_cm[0][0] / (test_cm[0][0] + test_cm[1][0]) if (test_cm[0][0] + test_cm[1][0]) > 0 else 0
    rL = test_cm[0][0] / (test_cm[0][0] + test_cm[0][1]) if (test_cm[0][0] + test_cm[0][1]) > 0 else 0
    pH = test_cm[1][1] / (test_cm[1][1] + test_cm[0][1]) if (test_cm[1][1] + test_cm[0][1]) > 0 else 0
    rH = test_cm[1][1] / (test_cm[1][1] + test_cm[1][0]) if (test_cm[1][1] + test_cm[1][0]) > 0 else 0
    f1L = 2 * pL * rL / (pL + rL) if (pL + rL) > 0 else 0
    f1H = 2 * pH * rH / (pH + rH) if (pH + rH) > 0 else 0
    print(f'  L 类: Precision={pL:.4f} Recall={rL:.4f} F1={f1L:.4f}')
    print(f'  H 类: Precision={pH:.4f} Recall={rH:.4f} F1={f1H:.4f}')
    print('=' * 60)
    print(f'完成! 最佳模型: {OUTPUT_DIR / f"best_{args.model}.pth"}')


if __name__ == '__main__':
    main()