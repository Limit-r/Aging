import numpy as np
import torch
import torch.nn as nn

from model.backbone import Backbone, C2f, Conv, Bottleneck
from model.yolo_training import weights_init
from utils.utils_bbox import make_anchors


def fuse_conv_and_bn(conv, bn):
    # 混合Conv2d + BatchNorm2d 减少计算量
    fusedconv = nn.Conv2d(
        conv.in_channels,
        conv.out_channels,
        kernel_size=conv.kernel_size,
        stride=conv.stride,
        padding=conv.padding,
        dilation=conv.dilation,
        groups=conv.groups,
        bias=True
    ).requires_grad_(False).to(conv.weight.device)

    w_conv = conv.weight.clone().view(conv.out_channels, -1)
    w_bn = torch.diag(bn.weight.div(torch.sqrt(bn.eps + bn.running_var)))
    fusedconv.weight.copy_(torch.mm(w_bn, w_conv).view(fusedconv.weight.shape))

    b_conv = torch.zeros(conv.weight.size(0), device=conv.weight.device) if conv.bias is None else conv.bias
    b_bn = bn.bias - bn.weight.mul(bn.running_mean).div(torch.sqrt(bn.running_var + bn.eps))
    fusedconv.bias.copy_(torch.mm(w_bn, b_conv.reshape(-1, 1)).reshape(-1) + b_bn)

    return fusedconv


class ECA(nn.Module):
    """Efficient Channel Attention (ECA)"""
    def __init__(self, c, k=3):
        super(ECA, self).__init__()
        self.avg_pool = nn.AdaptiveAvgPool2d(1)
        self.conv = nn.Conv1d(1, 1, kernel_size=k, padding=(k - 1) // 2, bias=False)
        self.sigmoid = nn.Sigmoid()

    def forward(self, x):
        b, c, h, w = x.size()
        y = self.avg_pool(x)
        y = self.conv(y.squeeze(-1).transpose(-1, -2)).transpose(-1, -2).unsqueeze(-1)
        y = self.sigmoid(y)
        return x * y.expand_as(x)


class SE(nn.Module):
    """Squeeze-and-Excitation (SE)"""
    def __init__(self, c, r=16):
        super(SE, self).__init__()
        self.avg_pool = nn.AdaptiveAvgPool2d(1)
        self.fc = nn.Sequential(
            nn.Linear(c, c // r, bias=False),
            nn.ReLU(inplace=True),
            nn.Linear(c // r, c, bias=False),
            nn.Sigmoid()
        )

    def forward(self, x):
        b, c, _, _ = x.size()
        y = self.avg_pool(x).view(b, c)
        y = self.fc(y).view(b, c, 1, 1)
        return x * y


class DFL(nn.Module):
    # Distribution Focal Loss (DFL)
    def __init__(self, c1=16):
        super().__init__()
        self.conv = nn.Conv2d(c1, 1, 1, bias=False).requires_grad_(False)
        x = torch.arange(c1, dtype=torch.float)
        self.conv.weight.data[:] = nn.Parameter(x.view(1, c1, 1, 1))
        self.c1 = c1

    def forward(self, x):
        b, c, a = x.shape
        return self.conv(x.view(b, 4, self.c1, a).transpose(2, 1).softmax(1)).view(b, 4, a)


#---------------------------------------------------#
#   修改后的 C2f 类：支持 ECA、SE 和 Dropout
#---------------------------------------------------#
class C2f(nn.Module):
    def __init__(self, c1, c2, n=1, shortcut=False, g=1, e=0.5, eca=False, se=False, dropout_rate=0.0):
        super().__init__()
        self.c = int(c2 * e)  # hidden channels
        self.cv1 = Conv(c1, 2 * self.c, 1, 1)
        self.cv2 = Conv((2 + n) * self.c, c2, 1)  # final output channels
        self.m = nn.ModuleList(Bottleneck(self.c, self.c, shortcut, g, k=((3, 3), (3, 3)), e=1.0) for _ in range(n))
        self.eca = ECA(c2) if eca else None
        self.se = SE(c2) if se else None
        # 添加Dropout层
        self.dropout = nn.Dropout2d(dropout_rate) if dropout_rate > 0 else None

    def forward(self, x):
        # 保持与 backbone.py 中 C2f 相同的逻辑
        y = list(self.cv1(x).split((self.c, self.c), 1))
        y.extend(m(y[-1]) for m in self.m)
        result = self.cv2(torch.cat(y, 1))
        
        # 添加注意力机制
        if self.eca is not None:
            result = self.eca(result)
        if self.se is not None:
            result = self.se(result)
            
        # 应用Dropout
        if self.dropout is not None:
            result = self.dropout(result)
            
        return result


#---------------------------------------------------#
#   改进的 Bottleneck 类：增加 Dropout
#---------------------------------------------------#
class Bottleneck(nn.Module):
    # 标准瓶颈结构，残差结构
    # c1为输入通道数，c2为输出通道数
    def __init__(self, c1, c2, shortcut=True, g=1, k=(3, 3), e=0.5, dropout_rate=0.0):
        super().__init__()
        c_ = int(c2 * e)  # hidden channels
        self.cv1 = Conv(c1, c_, k[0], 1)
        self.cv2 = Conv(c_, c2, k[1], 1, g=g)
        self.add = shortcut and c1 == c2
        # 添加Dropout层
        self.dropout = nn.Dropout2d(dropout_rate) if dropout_rate > 0 else None

    def forward(self, x):
        if self.add:
            result = x + self.cv2(self.cv1(x))
        else:
            result = self.cv2(self.cv1(x))
        
        # 应用Dropout
        if self.dropout is not None:
            result = self.dropout(result)
            
        return result


#---------------------------------------------------#
#   改进的 Conv 类：增加可选的 Dropout
#---------------------------------------------------#
class Conv(nn.Module):
    # 标准卷积+标准化+激活函数
    default_act = nn.SiLU() 
    def __init__(self, c1, c2, k=1, s=1, p=None, g=1, d=1, act=True, dropout_rate=0.0):
        super().__init__()
        self.conv   = nn.Conv2d(c1, c2, k, s, autopad(k, p, d), groups=g, dilation=d, bias=False)
        self.bn     = nn.BatchNorm2d(c2, eps=0.001, momentum=0.03, affine=True, track_running_stats=True)
        self.act    = self.default_act if act is True else act if isinstance(act, nn.Module) else nn.Identity()
        # 添加Dropout层
        self.dropout = nn.Dropout2d(dropout_rate) if dropout_rate > 0 else None

    def forward(self, x):
        result = self.act(self.bn(self.conv(x)))
        # 应用Dropout
        if self.dropout is not None:
            result = self.dropout(result)
        return result

    def forward_fuse(self, x):
        result = self.act(self.conv(x))
        # 应用Dropout
        if self.dropout is not None:
            result = self.dropout(result)
        return result


def autopad(k, p=None, d=1):  
    # kernel, padding, dilation
    # 对输入的特征层进行自动padding，按照Same原则
    if d > 1:
        # actual kernel-size
        k = d * (k - 1) + 1 if isinstance(k, int) else [d * (x - 1) + 1 for x in k]
    if p is None:
        # auto-pad
        p = k // 2 if isinstance(k, int) else [x // 2 for x in k]
    return p


#---------------------------------------------------#
#   YoloBody 主体类（含注意力机制、Dropout 和改进的正则化）
#---------------------------------------------------#
class YoloBody(nn.Module):
    def __init__(self, input_shape, num_classes, phi, pretrained=False):
        super(YoloBody, self).__init__()
        depth_dict = {'n': 0.33, 's': 0.33, 'm': 0.67, 'l': 1.00, 'x': 1.00}
        width_dict = {'n': 0.25, 's': 0.50, 'm': 0.75, 'l': 1.00, 'x': 1.25}
        deep_width_dict = {'n': 1.00, 's': 1.00, 'm': 0.75, 'l': 0.50, 'x': 0.50}
        dep_mul, wid_mul, deep_mul = depth_dict[phi], width_dict[phi], deep_width_dict[phi]

        base_channels = int(wid_mul * 64)
        base_depth = max(round(dep_mul * 3), 1)

        # 主干网络 - 增加轻微的dropout
        self.backbone = Backbone(base_channels, base_depth, deep_mul, phi, pretrained=pretrained)

        # Neck 网络（加强特征提取）
        self.upsample = nn.Upsample(scale_factor=2, mode="nearest")

        # P5 -> P4: 上采样 + 融合
        self.conv3_for_upsample1 = C2f(
            int(base_channels * 16 * deep_mul) + base_channels * 8,
            base_channels * 8,
            base_depth,
            shortcut=False,
            eca=False,  # 主干已有 ECA，Neck 不重复
            se=True,    # 在 Neck 加入 SE
            dropout_rate=0.05  # 添加轻微dropout
        )
        # P4 -> P3: 上采样 + 融合
        self.conv3_for_upsample2 = C2f(
            base_channels * 8 + base_channels * 4,
            base_channels * 4,
            base_depth,
            shortcut=False,
            se=True,
            dropout_rate=0.05
        )
        # P3 -> P4: 下采样 + 融合
        self.down_sample1 = Conv(base_channels * 4, base_channels * 4, 3, 2, dropout_rate=0.02)
        self.conv3_for_downsample1 = C2f(
            base_channels * 8 + base_channels * 4,
            base_channels * 8,
            base_depth,
            shortcut=False,
            se=True,
            dropout_rate=0.05
        )
        # P4 -> P5: 下采样 + 融合
        self.down_sample2 = Conv(base_channels * 8, base_channels * 8, 3, 2, dropout_rate=0.02)
        self.conv3_for_downsample2 = C2f(
            int(base_channels * 16 * deep_mul) + base_channels * 8,
            int(base_channels * 16 * deep_mul),
            base_depth,
            shortcut=False,
            se=True,
            dropout_rate=0.05
        )

        ch = [base_channels * 4, base_channels * 8, int(base_channels * 16 * deep_mul)]
        self.shape = None
        self.nl = len(ch)
        self.stride = torch.tensor([256 / x.shape[-2] for x in self.backbone.forward(torch.zeros(1, 3, 256, 256))])
        self.reg_max = 16
        self.no = num_classes + self.reg_max * 4
        self.num_classes = num_classes

        # 在检测头中添加正则化
        c2, c3 = max((16, ch[0] // 4, self.reg_max * 4)), max(ch[0], num_classes)
        self.cv2 = nn.ModuleList(
            nn.Sequential(
                Conv(x, c2, 3, dropout_rate=0.02), 
                Conv(c2, c2, 3, dropout_rate=0.02), 
                nn.Conv2d(c2, 4 * self.reg_max, 1)
            ) for x in ch
        )
        self.cv3 = nn.ModuleList(
            nn.Sequential(
                Conv(x, c3, 3, dropout_rate=0.02), 
                Conv(c3, c3, 3, dropout_rate=0.02), 
                nn.Conv2d(c3, num_classes, 1)
            ) for x in ch
        )
        
        if not pretrained:
            weights_init(self)
        self.dfl = DFL(self.reg_max) if self.reg_max > 1 else nn.Identity()

    def fuse(self):
        print('Fusing layers... ')
        for m in self.modules():
            if type(m) is Conv and hasattr(m, 'bn'):
                m.conv = fuse_conv_and_bn(m.conv, m.bn)
                delattr(m, 'bn')
                m.forward = m.forward_fuse
        return self

    def forward(self, x):
        feat1, feat2, feat3 = self.backbone.forward(x)

        #------------------------加强特征提取网络------------------------#
        P5_upsample = self.upsample(feat3)
        P4 = torch.cat([P5_upsample, feat2], 1)
        P4 = self.conv3_for_upsample1(P4)

        P4_upsample = self.upsample(P4)
        P3 = torch.cat([P4_upsample, feat1], 1)
        P3 = self.conv3_for_upsample2(P3)

        P3_downsample = self.down_sample1(P3)
        P4 = torch.cat([P3_downsample, P4], 1)
        P4 = self.conv3_for_downsample1(P4)

        P4_downsample = self.down_sample2(P4)
        P5 = torch.cat([P4_downsample, feat3], 1)
        P5 = self.conv3_for_downsample2(P5)
        #------------------------加强特征提取网络------------------------#

        shape = P3.shape
        x = [P3, P4, P5]
        for i in range(self.nl):
            x[i] = torch.cat((self.cv2[i](x[i]), self.cv3[i](x[i])), 1)

        if self.shape != shape:
            self.anchors, self.strides = (x.transpose(0, 1) for x in make_anchors(x, self.stride, 0.5))
            self.shape = shape

        box, cls = torch.cat([xi.view(shape[0], self.no, -1) for xi in x], 2).split((self.reg_max * 4, self.num_classes), 1)
        dbox = self.dfl(box)
        return dbox, cls, x, self.anchors.to(dbox.device), self.strides.to(dbox.device)