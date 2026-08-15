"""
评估分类器混淆矩阵，找出分类器的错误模式。
"""
import sys
from pathlib import Path
import torch
from torch.utils.data import Dataset, DataLoader
import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from classifier.model import TinyConv
from classifier.train import LEDDataset, DATA_DIR, INPUT_SIZE

device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
print(f'设备: {device}')

# 加载模型
model = TinyConv(in_channels=3, num_classes=2)
weight_path = PROJECT_ROOT / 'classifier' / 'weights' / 'best_tinyconv.pth'
state = torch.load(str(weight_path), map_location=device, weights_only=True)
model.load_state_dict(state)
model = model.to(device).eval()

# 评估各 split
for split in ('train', 'val', 'test'):
    dataset = LEDDataset(DATA_DIR, split, augment=False)
    loader = DataLoader(dataset, batch_size=64, shuffle=False, num_workers=0)
    
    correct = 0
    total = 0
    # confusion matrix: [true][pred]
    cm = [[0, 0], [0, 0]]  # cm[true_L][pred_L], cm[true_L][pred_H], cm[true_H][pred_L], cm[true_H][pred_H]
    
    with torch.no_grad():
        for inputs, labels in loader:
            inputs, labels = inputs.to(device), labels.to(device)
            outputs = model(inputs)
            _, preds = torch.max(outputs, 1)
            
            for t, p in zip(labels.cpu().numpy(), preds.cpu().numpy()):
                cm[t][p] += 1
            
            correct += (preds == labels).sum().item()
            total += inputs.size(0)
    
    acc = correct / total
    print(f'\n{split} 集:')
    print(f'  准确率: {acc*100:.2f}% ({correct}/{total})')
    print(f'  混淆矩阵:')
    print(f'             预测 L    预测 H')
    print(f'  真实 L:    {cm[0][0]:6d}    {cm[0][1]:6d}  (L→H 误报: {cm[0][1]})')
    print(f'  真实 H:    {cm[1][0]:6d}    {cm[1][1]:6d}  (H→L 漏报: {cm[1][0]})')
    
    # Per-class metrics
    precision_L = cm[0][0] / (cm[0][0] + cm[1][0]) if (cm[0][0] + cm[1][0]) > 0 else 0
    recall_L = cm[0][0] / (cm[0][0] + cm[0][1]) if (cm[0][0] + cm[0][1]) > 0 else 0
    precision_H = cm[1][1] / (cm[1][1] + cm[0][1]) if (cm[1][1] + cm[0][1]) > 0 else 0
    recall_H = cm[1][1] / (cm[1][1] + cm[1][0]) if (cm[1][1] + cm[1][0]) > 0 else 0
    f1_L = 2 * precision_L * recall_L / (precision_L + recall_L) if (precision_L + recall_L) > 0 else 0
    f1_H = 2 * precision_H * recall_H / (precision_H + recall_H) if (precision_H + recall_H) > 0 else 0
    
    print(f'  L 类: Precision={precision_L:.4f} Recall={recall_L:.4f} F1={f1_L:.4f}')
    print(f'  H 类: Precision={precision_H:.4f} Recall={recall_H:.4f} F1={f1_H:.4f}')

# 检查亮度分布
print('\n\n亮度分布统计 (测试集):')
test_dataset = LEDDataset(DATA_DIR, 'test', augment=False)
brightness_L = []
brightness_H = []
for img_path, label in zip(test_dataset.images, test_dataset.labels):
    img = cv2.imread(img_path)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    b = float(np.mean(gray))
    if label == 0:
        brightness_L.append(b)
    else:
        brightness_H.append(b)

if brightness_L:
    print(f'  L 类: 均值={np.mean(brightness_L):.1f}  std={np.std(brightness_L):.1f}  min={min(brightness_L):.1f}  max={max(brightness_L):.1f}')
if brightness_H:
    print(f'  H 类: 均值={np.mean(brightness_H):.1f}  std={np.std(brightness_H):.1f}  min={min(brightness_H):.1f}  max={max(brightness_H):.1f}')

# 找出亮度重叠区域 (可能是误标样本)
overlap = [b for b in brightness_L if b >= 140] + [b for b in brightness_H if b < 140]
print(f'  亮度重叠样本数: {len(overlap)} (阈值=140)')