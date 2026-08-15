"""
轻量化二分类模型 (TinyConv) - 判断 LED 亮灭。

架构:
    Input: 32×32×3
    ├─ Conv2D 3×3, 8ch → BN → ReLU → MaxPool 2×2  (16×16×8)
    ├─ Conv2D 3×3, 16ch → BN → ReLU → MaxPool 2×2 (8×8×16)
    ├─ Conv2D 3×3, 32ch → BN → ReLU → GlobalAvgPool (32维)
    ├─ FC 32→16 → ReLU → Dropout(0.3)
    └─ FC 16→2 → Softmax

参数量: ~15K, INT8 模型大小: ~15KB
"""
import torch
import torch.nn as nn


class TinyConv(nn.Module):
    def __init__(self, in_channels=3, num_classes=2):
        super().__init__()
        self.features = nn.Sequential(
            # 32×32 → 16×16
            nn.Conv2d(in_channels, 8, 3, padding=1),
            nn.BatchNorm2d(8),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2),

            # 16×16 → 8×8
            nn.Conv2d(8, 16, 3, padding=1),
            nn.BatchNorm2d(16),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(2),

            # 8×8 → 4×4 (GlobalAvgPool 前)
            nn.Conv2d(16, 32, 3, padding=1),
            nn.BatchNorm2d(32),
            nn.ReLU(inplace=True),
        )

        self.classifier = nn.Sequential(
            nn.AdaptiveAvgPool2d(1),   # 4×4×32 → 1×1×32
            nn.Flatten(),               # 32
            nn.Linear(32, 16),
            nn.ReLU(inplace=True),
            nn.Dropout(0.3),
            nn.Linear(16, num_classes),
        )

    def forward(self, x):
        x = self.features(x)
        x = self.classifier(x)
        return x


class MicroConv(nn.Module):
    """超轻量版, 适合 ESP32 极端资源受限场景。"""
    def __init__(self, in_channels=3, num_classes=2):
        super().__init__()
        self.features = nn.Sequential(
            # 32×32 → 8×8
            nn.Conv2d(in_channels, 4, 3, padding=1),
            nn.BatchNorm2d(4),
            nn.ReLU(inplace=True),
            nn.MaxPool2d(4),

            # 8×8 → 4×4
            nn.Conv2d(4, 8, 3, padding=1),
            nn.BatchNorm2d(8),
            nn.ReLU(inplace=True),
        )

        self.classifier = nn.Sequential(
            nn.AdaptiveAvgPool2d(1),
            nn.Flatten(),
            nn.Linear(8, 2),
        )

    def forward(self, x):
        x = self.features(x)
        x = self.classifier(x)
        return x


if __name__ == '__main__':
    # 测试模型
    model = TinyConv()
    x = torch.randn(1, 3, 32, 32)
    y = model(x)
    print(f'TinyConv 参数量: {sum(p.numel() for p in model.parameters()):,}')
    print(f'  输入: {x.shape} → 输出: {y.shape}')

    model2 = MicroConv()
    y2 = model2(x)
    print(f'MicroConv 参数量: {sum(p.numel() for p in model2.parameters()):,}')
    print(f'  输入: {x.shape} → 输出: {y2.shape}')