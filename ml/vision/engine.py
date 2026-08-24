# -*- coding: utf-8 -*-
"""统一检测引擎：从 `ml/deploy/` 懒加载 YOLO(9类) + TinyConv(H/L) 亮灭分类器。

本模块会被 worker 子进程（如 `run_video.py`）通过 sys.path 引入；
**GUI 进程绝不 import 本模块**，以维持 Main.py 启动不加载 torch 的约定。
"""
from __future__ import annotations

import sys
from pathlib import Path

# 模型/训练代码根 = ml/
ML_ROOT = Path(__file__).resolve().parents[1]
if str(ML_ROOT) not in sys.path:
    sys.path.insert(0, str(ML_ROOT))

DEPLOY_DIR = ML_ROOT / "deploy"

# 默认推理参数（与 detect 程序保持一致）
DEFAULT_PHI = "n"
DEFAULT_INPUT_SHAPE = (512, 512)
DEFAULT_CONF = 0.25
DEFAULT_NMS = 0.45
CLASSIFIER_INPUT = 32


def is_background_class(name: str) -> bool:
    """是否纯背景面积类（应排除，不纳入 LED 统计）。

    - 一般 `*_area`（如 `FP_SIG_area`、`A_area`）是电路/板面背景区域，
      不应视为信号灯。
    - 但部署模型中**功率灯以 `*_PWR_area` 表达**（FP 板功率灯只报出
      `FP_PWR_area`，不会单报 `FP_PWR`），它识别到的是功率信号灯本身，
      需视作信号灯纳入统计，不按背景排除。
    """
    is_area = name.endswith("_area") or name.lower().endswith("area")
    if not is_area:
        return False
    return "pwr" not in name.lower()


def deployed_paths() -> dict:
    """返回 ml/deploy/ 下的统一部署产物路径（5 键）。"""
    return {
        "model": str(DEPLOY_DIR / "yolo_best_deploy.pt"),
        "labels": str(DEPLOY_DIR / "label_merged.txt"),
        "classifier": str(DEPLOY_DIR / "tinyconv_best.pth"),
    }


class DetectionEngine:
    """YOLO 目标检测 + TinyConv LED 亮灭分类的统一入口。

    线程安全性：模型推理在单 worker 进程内顺序调用，无需并发锁。
    """

    def __init__(
        self,
        device: str | None = None,
        phi: str = DEFAULT_PHI,
        input_shape: tuple[int, int] = DEFAULT_INPUT_SHAPE,
        conf: float = DEFAULT_CONF,
        nms: float = DEFAULT_NMS,
    ):
        # -- 延迟 import torch / 模型（本模块被 worker 进程引入时才加载）----
        import torch
        from classifier.model import TinyConv
        from model.YOLOV8 import YoloBody
        from utils.utils import get_classes
        from utils.utils_bbox import DecodeBox

        paths = deployed_paths()
        self._check_paths(paths)

        self.device = torch.device(
            "cuda" if torch.cuda.is_available() else "cpu"
        )
        self.conf = conf
        self.nms = nms
        self.input_shape = tuple(input_shape)
        self.phi = phi

        self.class_names, self.num_classes = get_classes(paths["labels"])

        self.yolo = self._load_yolo(
            YoloBody, torch, paths["model"], self.num_classes, phi)
        self.decodebox = DecodeBox(
            num_classes=self.num_classes, input_shape=self.input_shape)
        self.classifier = self._load_classifier(TinyConv, torch, paths["classifier"])

    @staticmethod
    def _check_paths(paths: dict) -> None:
        missing = [v for v in paths.values() if not Path(v).exists()]
        if missing:
            raise FileNotFoundError(
                "模型缺失，请先训练并部署（deploy_models.py），缺少: "
                + ", ".join(missing)
            )

    def _load_yolo(self, YoloBody, torch, weights, num_classes, phi):
        yolo = YoloBody(self.input_shape, num_classes, phi, pretrained=False)
        state = torch.load(weights, map_location=self.device, weights_only=False)
        if isinstance(state, dict) and "model" in state:
            yolo.load_state_dict(state["model"])
        else:
            yolo.load_state_dict(state)
        yolo = yolo.to(self.device).eval()
        return yolo

    def _load_classifier(self, TinyConv, torch, weights):
        model = TinyConv(in_channels=3, num_classes=2)
        state = torch.load(weights, map_location=self.device, weights_only=False)
        if isinstance(state, dict) and "model" in state:
            model.load_state_dict(state["model"])
        else:
            model.load_state_dict(state)
        model = model.to(self.device).eval()
        return model

    # ------------------------------------------------------------------ 推理
    def detect(self, frame_bgr) -> list[dict]:
        """对单帧 BGR 图像做 YOLO 检测。

        Returns
        -------
        list[dict]
            每个检测目标: {x1,y1,x2,y2,score,cid,name}
            name 为标注类别名（如 FP_VPL / A_CLIP，保留基础名）。
        """
        import numpy as np
        import torch
        from PIL import Image

        h, w = frame_bgr.shape[:2]
        image_shape = np.array([h, w])
        scale = min(self.input_shape[0] / h, self.input_shape[1] / w)
        nw, nh = int(w * scale), int(h * scale)
        pil = Image.fromarray(frame_bgr[:, :, ::-1])  # BGR -> RGB
        resized = pil.resize((nw, nh), Image.BICUBIC)
        canvas = Image.new("RGB", self.input_shape, (128, 128, 128))
        canvas.paste(resized, ((self.input_shape[1] - nw) // 2,
                               (self.input_shape[0] - nh) // 2))
        arr = np.array(canvas, dtype="float32") / 255.0
        arr = np.transpose(arr, (2, 0, 1))[None]
        images = torch.from_numpy(arr).to(self.device)

        with torch.no_grad():
            outputs = self.yolo.forward(images)
            results = self.decodebox.decode_box(outputs)
            results = self.decodebox.non_max_suppression(
                results, self.num_classes, input_shape=self.input_shape,
                image_shape=image_shape, letterbox_image=True,
                conf_thres=self.conf, nms_thres=self.nms)

        dets = []
        if results[0] is None:
            return dets
        top_boxes = results[0][:, :4]
        top_conf = results[0][:, 4]
        top_label = results[0][:, 5].astype("int32")
        for i in range(len(top_label)):
            y1, x1, y2, x2 = top_boxes[i]
            cid = int(top_label[i])
            dets.append({
                "x1": float(x1), "y1": float(y1),
                "x2": float(x2), "y2": float(y2),
                "score": float(top_conf[i]), "cid": cid,
                "name": self.class_names[cid] if cid < len(self.class_names) else str(cid),
            })
        return dets

    # ------------------------------------------------------------ H/L 分类
    def classify(self, frame_bgr, dets) -> dict[int, tuple[str, float]]:
        """对非 area 检测框逐 ROI 做 H/L 二分类。

        Returns
        -------
        dict[det索引 -> (label, conf)]
            label ∈ {"H","L"}；仅包含 area 类别之外的检测框。
        """
        import cv2
        import numpy as np
        import torch

        h, w = frame_bgr.shape[:2]
        indexes = [(i, d) for i, d in enumerate(dets)
                   if not is_background_class(d["name"])]
        if not indexes:
            return {}

        batch = []
        rois = []
        for _i, d in indexes:
            x1i, y1i = max(0, int(d["x1"])), max(0, int(d["y1"]))
            x2i, y2i = min(w, int(d["x2"])), min(h, int(d["y2"]))
            if x2i <= x1i or y2i <= y1i:
                continue
            roi = frame_bgr[y1i:y2i, x1i:x2i]
            roi_rgb = cv2.cvtColor(roi, cv2.COLOR_BGR2RGB)
            r = cv2.resize(roi_rgb, (CLASSIFIER_INPUT, CLASSIFIER_INPUT),
                           interpolation=cv2.INTER_AREA).astype("float32") / 255.0
            batch.append(np.transpose(r, (2, 0, 1)))
            rois.append((_i, d))
        if not batch:
            return {}

        tensor = torch.from_numpy(np.array(batch)).to(self.device)
        with torch.no_grad():
            outputs = self.classifier(tensor)
            probs = torch.softmax(outputs, dim=1)
            _, preds = torch.max(outputs, 1)
        preds = preds.cpu().numpy()
        probs = probs.cpu().numpy()

        result = {}
        for k, (_i, _d) in enumerate(rois):
            label = "H" if preds[k] == 1 else "L"
            result[_i] = (label, float(probs[k, preds[k]]))
        return result