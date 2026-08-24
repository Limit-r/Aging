# -*- coding: utf-8 -*-
"""统一检测引擎：从 `ml/deploy/` 懒加载 YOLO(9类) + TinyConv(H/L) 亮灭分类器。

本模块会被 worker 子进程（如 `run_video.py`）通过 sys.path 引入；
**GUI 进程绝不 import 本模块**，以维持 Main.py 启动不加载 torch 的约定。
"""
from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
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

    @staticmethod
    def _floatify(container):
        import torch
        if isinstance(container, torch.Tensor):
            return container.float()
        if isinstance(container, (list, tuple)):
            return type(container)(DetectionEngine._floatify(x) for x in container)
        return container

    def _preprocess(self, frame_bgr) -> "torch.Tensor":
        """cv2 letterbox：等比缩放 + RGB 序 + 灰边(128) 填充到 input_shape。

        返回 shape [1, 3, H, W] 的 float32 tensor（置于 self.device）。
        """
        return self._preprocess_batch([frame_bgr])

    def _preprocess_batch(self, frames_bgr) -> "torch.Tensor":
        """批量 letterbox 预处理（一次 CPU 构造 + 单次 GPU 拷贝）。

        在 CPU 上把整批帧构造成一个连续 [B,3,H,W] uint8 数组，再一次性拷到
        设备，并在 GPU 上完成 /255 归一化。相比逐帧 `cvtColor/resize/.to`
        各做一遍，多路并发时减少整幅拷贝次数与中间张量分配。

        Returns
        -------
        float32 tensor，[B, 3, input_shape[0], input_shape[1]]（[0,1]）
        """
        import cv2
        import numpy as np
        import torch

        insh = self.input_shape
        canvas = np.full((len(frames_bgr), insh[0], insh[1], 3),
                         128, dtype="uint8")
        for i, frame in enumerate(frames_bgr):
            h, w = frame.shape[:2]
            scale = min(insh[0] / h, insh[1] / w)
            nw, nh = int(round(w * scale)), int(round(h * scale))
            resized = cv2.resize(
                cv2.cvtColor(frame, cv2.COLOR_BGR2RGB), (nw, nh),
                interpolation=cv2.INTER_AREA)
            top = (insh[0] - nh) // 2
            left = (insh[1] - nw) // 2
            canvas[i, top:top + nh, left:left + nw] = resized
        arr = np.ascontiguousarray(np.transpose(canvas, (0, 3, 1, 2)))  # B,H,W,3 -> B,3,H,W
        t = torch.from_numpy(arr).to(self.device, non_blocking=True)     # uint8 on GPU
        return t.float().div_(255.0)                                     # GPU 侧归一化

    @staticmethod
    def _to_dets(nms_results, class_names) -> list[dict]:
        """把单图 NMS 结果转成 det 列表。"""
        dets = []
        if nms_results[0] is None:
            return dets
        top_boxes = nms_results[0][:, :4]
        top_conf = nms_results[0][:, 4]
        top_label = nms_results[0][:, 5].astype("int32")
        for i in range(len(top_label)):
            y1, x1, y2, x2 = top_boxes[i]
            cid = int(top_label[i])
            dets.append({
                "x1": float(x1), "y1": float(y1),
                "x2": float(x2), "y2": float(y2),
                "score": float(top_conf[i]), "cid": cid,
                "name": class_names[cid] if cid < len(class_names) else str(cid),
            })
        return dets

    # ------------------------------------------------------------------ 推理
    def detect(self, frame_bgr) -> list[dict]:
        """对单帧 BGR 图像做 YOLO 检测。

        - 输入：cv2 letterbox 等比缩放 + 灰边填充到 `input_shape`，RGB 通道序。
        - 推理：CUDA 下用 FP16 autocast 加速，输出解码仍回 FP32 保证精度。

        Returns
        -------
        list[dict]
            每个检测目标: {x1,y1,x2,y2,score,cid,name}
            name 为标注类别名（如 FP_VPL / A_CLIP，保留基础名）。
        """
        import numpy as np
        import torch

        h, w = frame_bgr.shape[:2]
        image_shape = np.array([h, w])
        images = self._preprocess(frame_bgr)

        with torch.no_grad():
            ctx = (torch.amp.autocast(device_type="cuda", dtype=torch.float16)
                   if self.device.type == "cuda" else nullcontext())
            with ctx:
                outputs = self.yolo.forward(images)
            # 解码回 FP32，避免 FP16 精度影响 NMS/坐标（输出为嵌套 list）
            outputs = self._floatify(outputs)
            results = self.decodebox.decode_box(outputs)
            results = self.decodebox.non_max_suppression(
                results, self.num_classes, input_shape=self.input_shape,
                image_shape=image_shape, letterbox_image=True,
                conf_thres=self.conf, nms_thres=self.nms)
        return self._to_dets(results, self.class_names)

    def detect_batch(self, frames_bgr, shapes) -> list[list[dict]]:
        """批量 YOLO 检测（一次前向），供视频流调度器多路逐帧使用。

        - 前向整批一次（摊销固定开销）；`decode_box` batch 感知一次完成；
          `non_max_suppression` 对每路用其**自身** `image_shape` 逐路执行
          （NMS 内部 image_shape 是单一值，无法跨不同分辨率 batch 生效）。

        Parameters
        ----------
        frames_bgr : list[np.ndarray]   每路一帧 BGR
        shapes     : list[list[int,int]] 每路 [h, w]

        Returns
        -------
        list[list[dict]]  与输入同序，每路一个 det 列表
        """
        import numpy as np
        import torch

        if not frames_bgr:
            return []
        prediction = self._decode_batch(frames_bgr)
        return [self._nms_one(prediction[i:i + 1], shapes[i])
                for i in range(len(shapes))]

    def _decode_batch(self, frames_bgr) -> "torch.Tensor":
        """批量前向 + 解码（不含 NMS），返回 `prediction` [B, 8400, no]。

        CPU 预处理器 + 一次 GPU batch 前向 + batch 感知 `decode_box`。
        NMS 需逐图自身的 `image_shape`，由调用方并行执行 `_nms_one`。
        """
        import torch

        if not frames_bgr:
            return None
        images = self._preprocess_batch(frames_bgr)
        with torch.no_grad():
            ctx = (torch.amp.autocast(device_type="cuda", dtype=torch.float16)
                   if self.device.type == "cuda" else nullcontext())
            with ctx:
                outputs = self.yolo.forward(images)
            outputs = self._floatify(outputs)
            return self.decodebox.decode_box(outputs)  # [B, 8400, no]

    def _nms_one(self, pred, image_shape) -> list[dict]:
        """对单图执行 NMS + 转 det 列表（用该图自身 image_shape）。"""
        import numpy as np

        image_shape = np.array(image_shape, dtype=float)
        nms = self.decodebox.non_max_suppression(
            pred, self.num_classes, input_shape=self.input_shape,
            image_shape=image_shape, letterbox_image=True,
            conf_thres=self.conf, nms_thres=self.nms)
        return self._to_dets(nms, self.class_names)

    def detect_batch_parallel(self, frames_bgr, shapes,
                              max_workers: int = 8) -> list[list[dict]]:
        """批量检测，后处理（NMS/转 det）跨图并行，用于高并发静默监控。

        一次 `_decode_batch` 前向（GPU batch）后，把每图的 NMS/解码丢进线程池
        并行计算——测得串行后处理是全流程主要耗时（可占 70%~90%），并行摊平。
        与 `detect_batch` 结果一致（NMS 各图相互独立）。

        Parameters
        ----------
        max_workers : int   并行线程数（建议 ≈ CPU 逻辑核数）
        """
        prediction = self._decode_batch(frames_bgr)
        if prediction is None:
            return []
        n = len(shapes)
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            return list(ex.map(self._nms_one,
                               (prediction[i:i + 1] for i in range(n)),
                               shapes))

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
            ctx = (torch.amp.autocast(device_type="cuda", dtype=torch.float16)
                   if self.device.type == "cuda" else nullcontext())
            with ctx:
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

    def classify_batch(self, jobs) -> list[dict]:
        """跨多路流合并 ROI 做一次 H/L 分类前向。

        Parameters
        ----------
        jobs : list[(frame_bgr, dets)]
            每路一帧与其检测框 dDets。

        Returns
        -------
        list[dict]  与 jobs 同序；每路 dict 为 {det索引 -> (label, conf)}
        """
        import cv2
        import numpy as np
        import torch

        results = [{} for _ in jobs]
        roi_batch = []
        meta = []           # (job_idx, det_idx)
        for ji, (frame, dets) in enumerate(jobs):
            h, w = frame.shape[:2]
            for i, d in enumerate(dets):
                if is_background_class(d["name"]):
                    continue
                x1i, y1i = max(0, int(d["x1"])), max(0, int(d["y1"]))
                x2i, y2i = min(w, int(d["x2"])), min(h, int(d["y2"]))
                if x2i <= x1i or y2i <= y1i:
                    continue
                roi = frame[y1i:y2i, x1i:x2i]
                r = cv2.resize(
                    cv2.cvtColor(roi, cv2.COLOR_BGR2RGB),
                    (CLASSIFIER_INPUT, CLASSIFIER_INPUT),
                    interpolation=cv2.INTER_AREA).astype("float32") / 255.0
                roi_batch.append(np.transpose(r, (2, 0, 1)))
                meta.append((ji, i))
        if not roi_batch:
            return results
        tensor = torch.from_numpy(np.array(roi_batch)).to(self.device)
        with torch.no_grad():
            ctx = (torch.amp.autocast(device_type="cuda", dtype=torch.float16)
                   if self.device.type == "cuda" else nullcontext())
            with ctx:
                outputs = self.classifier(tensor)
                probs = torch.softmax(outputs, dim=1)
                _, preds = torch.max(outputs, 1)
        probs = probs.cpu().numpy()
        preds = preds.cpu().numpy()
        for k, (ji, i) in enumerate(meta):
            label = "H" if preds[k] == 1 else "L"
            results[ji][i] = (label, float(probs[k, preds[k]]))
        return results