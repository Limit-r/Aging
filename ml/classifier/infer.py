"""
LED 亮灭二分类推理工具。

用法:
    # 单张图片推理
    python ml/classifier/infer.py --image xxx.png

    # 作为模块导入
    from ml.classifier.infer import create_classifier, predict_led
"""
import sys
from pathlib import Path

import cv2
import numpy as np
import torch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from classifier.model import TinyConv

INPUT_SIZE = 32
WEIGHT_PATH = PROJECT_ROOT / 'classifier' / 'weights' / 'best_tinyconv.pth'


class LEDClassifier:
    """LED 亮灭分类器。

    对裁剪后的 LED ROI 区域进行二分类:
    - 0 (L): 灭灯
    - 1 (H): 亮灯
    """

    def __init__(self, weight_path=None, device=None):
        if weight_path is None:
            weight_path = WEIGHT_PATH
        if device is None:
            device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

        self.device = device
        self.input_size = INPUT_SIZE

        self.model = TinyConv(in_channels=3, num_classes=2)
        state = torch.load(str(weight_path), map_location=device, weights_only=True)
        self.model.load_state_dict(state)
        self.model = self.model.to(device).eval()

    @torch.no_grad()
    def predict(self, roi_bgr):
        """对单个 LED ROI 做亮灭分类。

        Parameters
        ----------
        roi_bgr : np.ndarray
            BGR 格式的 ROI 图像裁剪 (任意尺寸)

        Returns
        -------
        int
            0 = 灭 (L), 1 = 亮 (H)
        float
            置信度 (Softmax 概率)
        """
        # BGR → RGB → resize → normalize
        img = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2RGB)
        img = cv2.resize(img, (self.input_size, self.input_size), interpolation=cv2.INTER_AREA)
        img = img.astype(np.float32) / 255.0
        img = np.transpose(img, (2, 0, 1))  # HWC → CHW
        tensor = torch.from_numpy(img).float().unsqueeze(0).to(self.device)

        outputs = self.model(tensor)
        probs = torch.softmax(outputs, dim=1)
        pred = torch.argmax(probs, dim=1).item()
        conf = probs[0, pred].item()

        return pred, conf

    @torch.no_grad()
    def predict_batch(self, rois_bgr):
        """批量对多个 LED ROI 做亮灭分类。

        Parameters
        ----------
        rois_bgr : list[np.ndarray]
            BGR 格式的 ROI 列表

        Returns
        -------
        list[int]
            每个 ROI 的预测结果 (0=L, 1=H)
        list[float]
            每个 ROI 的置信度
        """
        if not rois_bgr:
            return [], []

        batch = []
        for roi in rois_bgr:
            img = cv2.cvtColor(roi, cv2.COLOR_BGR2RGB)
            img = cv2.resize(img, (self.input_size, self.input_size), interpolation=cv2.INTER_AREA)
            img = img.astype(np.float32) / 255.0
            img = np.transpose(img, (2, 0, 1))
            batch.append(img)

        tensor = torch.from_numpy(np.array(batch)).float().to(self.device)
        outputs = self.model(tensor)
        probs = torch.softmax(outputs, dim=1)
        preds = torch.argmax(probs, dim=1).tolist()
        confs = [probs[i, p].item() for i, p in enumerate(preds)]

        return preds, confs


# 快捷函数
def create_classifier(weight_path=None, device=None):
    return LEDClassifier(weight_path, device)


def predict_led(classifier, roi_bgr):
    return classifier.predict(roi_bgr)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--image', required=True, help='待分类的 LED ROI 图片')
    parser.add_argument('--weights', default=str(WEIGHT_PATH))
    args = parser.parse_args()

    img = cv2.imread(args.image)
    if img is None:
        print(f'[ERROR] 无法读取图片: {args.image}')
        sys.exit(1)

    clf = LEDClassifier(args.weights)
    pred, conf = clf.predict(img)
    label = 'H (亮)' if pred == 1 else 'L (灭)'
    print(f'结果: {label}  置信度: {conf:.4f}')