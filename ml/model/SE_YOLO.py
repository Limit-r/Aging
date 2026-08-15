import numpy as np
import torch
import torch.nn as nn

from model.yolo_training import weights_init
from utils.utils_bbox import make_anchors

def autopad(k, p=None, d=1):  
    if d > 1:
        k = d * (k - 1) + 1 if isinstance(k, int) else [d * (x - 1) + 1 for x in k]
    if p is None:
        p = k // 2 if isinstance(k, int) else [x // 2 for x in k]
    return p

class SiLU(nn.Module):  
    @staticmethod
    def forward(x):
        return x * torch.sigmoid(x)
    
class Conv(nn.Module):
    default_act = SiLU() 
    def __init__(self, c1, c2, k=1, s=1, p=None, g=1, d=1, act=True):
        super().__init__()
        self.conv   = nn.Conv2d(c1, c2, k, s, autopad(k, p, d), groups=g, dilation=d, bias=False)
        self.bn     = nn.BatchNorm2d(c2, eps=0.001, momentum=0.03, affine=True, track_running_stats=True)
        self.act    = self.default_act if act is True else act if isinstance(act, nn.Module) else nn.Identity()

    def forward(self, x):
        return self.act(self.bn(self.conv(x)))

    def forward_fuse(self, x):
        return self.act(self.conv(x))

class Bottleneck(nn.Module):
    def __init__(self, c1, c2, shortcut=True, g=1, k=(3, 3), e=0.5):
        super().__init__()
        c_ = int(c2 * e)
        self.cv1 = Conv(c1, c_, k[0], 1)
        self.cv2 = Conv(c_, c2, k[1], 1, g=g)
        self.add = shortcut and c1 == c2

    def forward(self, x):
        return x + self.cv2(self.cv1(x)) if self.add else self.cv2(self.cv1(x))    

class C2f(nn.Module):
    def __init__(self, c1, c2, n=1, shortcut=False, g=1, e=0.5, dropout_rate=0.0):
        super().__init__()
        self.c      = int(c2 * e) 
        self.cv1    = Conv(c1, 2 * self.c, 1, 1)
        self.cv2    = Conv((2 + n) * self.c, c2, 1)
        self.m      = nn.ModuleList(Bottleneck(self.c, self.c, shortcut, g, k=((3, 3), (3, 3)), e=1.0) for _ in range(n))
        self.dropout = nn.Dropout2d(dropout_rate) if dropout_rate > 0 else None

    def forward(self, x):
        y = list(self.cv1(x).split((self.c, self.c), 1))
        y.extend(m(y[-1]) for m in self.m)
        result = self.cv2(torch.cat(y, 1))
        if self.dropout:
            result = self.dropout(result)
        return result
    
class SPPF(nn.Module):
    def __init__(self, c1, c2, k=5):
        super().__init__()
        c_          = c1 // 2
        self.cv1    = Conv(c1, c_, 1, 1)
        self.cv2    = Conv(c_ * 4, c2, 1, 1)
        self.m      = nn.MaxPool2d(kernel_size=k, stride=1, padding=k // 2)

    def forward(self, x):
        x = self.cv1(x)
        y1 = self.m(x)
        y2 = self.m(y1)
        return self.cv2(torch.cat((x, y1, y2, self.m(y2)), 1))

class SEBlock(nn.Module):
    """
    Squeeze-and-Excitation Block
    https://arxiv.org/abs/1709.01507
    """
    def __init__(self, channels, reduction=16):
        super(SEBlock, self).__init__()
        self.fc1 = nn.Conv2d(channels, channels // reduction, kernel_size=1)
        self.relu = nn.ReLU(inplace=True)
        self.fc2 = nn.Conv2d(channels // reduction, channels, kernel_size=1)
        self.sigmoid = nn.Sigmoid()

    def forward(self, x):
        y = torch.mean(x, dim=(2, 3), keepdim=True)
        y = self.fc1(y)
        y = self.relu(y)
        y = self.fc2(y)
        y = self.sigmoid(y)
        return x * y

class Backbone(nn.Module):
    def __init__(self, base_channels, base_depth, deep_mul, phi, pretrained=False):
        super().__init__()
        self.stem = Conv(3, base_channels, 3, 2)
        
        self.dark2 = nn.Sequential(
            Conv(base_channels, base_channels * 2, 3, 2),
            C2f(base_channels * 2, base_channels * 2, base_depth, True, dropout_rate=0.05),
            SEBlock(base_channels * 2, reduction=8)
        )
        self.dark3 = nn.Sequential(
            Conv(base_channels * 2, base_channels * 4, 3, 2),
            C2f(base_channels * 4, base_channels * 4, base_depth * 2, True, dropout_rate=0.05),
            SEBlock(base_channels * 4, reduction=8)
        )
        self.dark4 = nn.Sequential(
            Conv(base_channels * 4, base_channels * 8, 3, 2),
            C2f(base_channels * 8, base_channels * 8, base_depth * 2, True, dropout_rate=0.05),
            SEBlock(base_channels * 8, reduction=8)
        )
        self.dark5 = nn.Sequential(
            Conv(base_channels * 8, int(base_channels * 16 * deep_mul), 3, 2),
            C2f(int(base_channels * 16 * deep_mul), int(base_channels * 16 * deep_mul), base_depth, True, dropout_rate=0.05),
            SPPF(int(base_channels * 16 * deep_mul), int(base_channels * 16 * deep_mul), k=5),
            SEBlock(int(base_channels * 16 * deep_mul), reduction=8)
        )
        
        if pretrained:
            url = {
                "n" : 'https://github.com/bubbliiiing/yolov8-pytorch/releases/download/v1.0/yolov8_n_backbone_weights.pth',
                "s" : 'https://github.com/bubbliiiing/yolov8-pytorch/releases/download/v1.0/yolov8_s_backbone_weights.pth',
                "m" : 'https://github.com/bubbliiiing/yolov8-pytorch/releases/download/v1.0/yolov8_m_backbone_weights.pth',
                "l" : 'https://github.com/bubbliiiing/yolov8-pytorch/releases/download/v1.0/yolov8_l_backbone_weights.pth',
                "x" : 'https://github.com/bubbliiiing/yolov8-pytorch/releases/download/v1.0/yolov8_x_backbone_weights.pth',
            }[phi]
            checkpoint = torch.hub.load_state_dict_from_url(url=url, map_location="cpu", model_dir="./weights/pretrained")
            self.load_state_dict(checkpoint, strict=False)
            print("Load weights from " + url.split('/')[-1])

    def forward(self, x):
        x = self.stem(x)
        x = self.dark2(x)
        x = self.dark3(x)
        feat1 = x
        x = self.dark4(x)
        feat2 = x
        x = self.dark5(x)
        feat3 = x
        return feat1, feat2, feat3

def fuse_conv_and_bn(conv, bn):
    fusedconv = nn.Conv2d(conv.in_channels,
                          conv.out_channels,
                          kernel_size=conv.kernel_size,
                          stride=conv.stride,
                          padding=conv.padding,
                          dilation=conv.dilation,
                          groups=conv.groups,
                          bias=True).requires_grad_(False).to(conv.weight.device)

    w_conv = conv.weight.clone().view(conv.out_channels, -1)
    w_bn = torch.diag(bn.weight.div(torch.sqrt(bn.eps + bn.running_var)))
    fusedconv.weight.copy_(torch.mm(w_bn, w_conv).view(fusedconv.weight.shape))

    b_conv = torch.zeros(conv.weight.size(0), device=conv.weight.device) if conv.bias is None else conv.bias
    b_bn = bn.bias - bn.weight.mul(bn.running_mean).div(torch.sqrt(bn.running_var + bn.eps))
    fusedconv.bias.copy_(torch.mm(w_bn, b_conv.reshape(-1, 1)).reshape(-1) + b_bn)

    return fusedconv

class DFL(nn.Module):
    def __init__(self, c1=16):
        super().__init__()
        self.conv   = nn.Conv2d(c1, 1, 1, bias=False).requires_grad_(False)
        x           = torch.arange(c1, dtype=torch.float)
        self.conv.weight.data[:] = nn.Parameter(x.view(1, c1, 1, 1))
        self.c1     = c1

    def forward(self, x):
        b, c, a = x.shape
        return self.conv(x.view(b, 4, self.c1, a).transpose(2, 1).softmax(1)).view(b, 4, a)
        
class YoloBody(nn.Module):
    def __init__(self, input_shape, num_classes, phi, pretrained=False):
        super(YoloBody, self).__init__()
        depth_dict = {'n' : 0.33, 's' : 0.33, 'm' : 0.67, 'l' : 1.00, 'x' : 1.00,}
        width_dict = {'n' : 0.25, 's' : 0.50, 'm' : 0.75, 'l' : 1.00, 'x' : 1.25,}
        deep_width_dict = {'n' : 1.00, 's' : 1.00, 'm' : 0.75, 'l' : 0.50, 'x' : 0.50,}
        dep_mul, wid_mul, deep_mul = depth_dict[phi], width_dict[phi], deep_width_dict[phi]

        base_channels = int(wid_mul * 64)
        base_depth = max(round(dep_mul * 3), 1)

        self.backbone = Backbone(base_channels, base_depth, deep_mul, phi, pretrained=pretrained)

        self.upsample = nn.Upsample(scale_factor=2, mode="nearest")

        self.conv3_for_upsample1 = C2f(int(base_channels * 16 * deep_mul) + base_channels * 8, 
                                       base_channels * 8, base_depth, shortcut=False, dropout_rate=0.05)
        self.conv3_for_upsample2 = C2f(base_channels * 8 + base_channels * 4, 
                                       base_channels * 4, base_depth, shortcut=False, dropout_rate=0.05)
        
        self.down_sample1 = Conv(base_channels * 4, base_channels * 4, 3, 2)
        self.conv3_for_downsample1 = C2f(base_channels * 8 + base_channels * 4, 
                                         base_channels * 8, base_depth, shortcut=False, dropout_rate=0.05)

        self.down_sample2 = Conv(base_channels * 8, base_channels * 8, 3, 2)
        self.conv3_for_downsample2 = C2f(int(base_channels * 16 * deep_mul) + base_channels * 8, 
                                         int(base_channels * 16 * deep_mul), base_depth, shortcut=False, dropout_rate=0.05)
        
        ch = [base_channels * 4, base_channels * 8, int(base_channels * 16 * deep_mul)]
        self.shape = None
        self.nl = len(ch)
        self.stride = torch.tensor([256 / x.shape[-2] for x in self.backbone.forward(torch.zeros(1, 3, 256, 256))])
        self.reg_max = 16
        self.no = num_classes + self.reg_max * 4
        self.num_classes = num_classes
        
        c2, c3 = max((16, ch[0] // 4, self.reg_max * 4)), max(ch[0], num_classes)
        self.cv2 = nn.ModuleList(nn.Sequential(Conv(x, c2, 3), Conv(c2, c2, 3), 
                                               nn.Conv2d(c2, 4 * self.reg_max, 1)) for x in ch)
        self.cv3 = nn.ModuleList(nn.Sequential(Conv(x, c3, 3), Conv(c3, c3, 3), 
                                               nn.Conv2d(c3, num_classes, 1)) for x in ch)
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