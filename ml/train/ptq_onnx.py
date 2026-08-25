# -*- coding: utf-8 -*-
"""PTQ（训练后量化）→ QDQ ONNX INT8 导出。

与 QAT 不同，PTQ 无需重训。基于已训好的 FP32 模型（weights/MERGED_CMP_FP32），
利用 backbone/neck 卷积量化（激活 per-tensor INT8、权重 per-channel INT8，SiLU/DFL 保持 FP32）
做一次前向校准统计激活/权重的量化范围，再 convert_pt2e 得到 QDQ 图，导出 ONNX INT8。

复用 qat_quantizer.ConvSiluQuantizer / prepare_qat / convert_qat：prepare_pt2e 后不再训练，
而是用校准图片跑若干次前向收集观察器统计数据，随后 convert 即得到含 QDQ 的部署图。

用法（在 ml/ 下运行）：
  E:\\MiniConda\\envs\\Aging\\python.exe train/ptq_onnx.py \
      --fp32 weights/MERGED_CMP_FP32/best_epoch_weights.pth \
      --out deploy/yolo_ptq_int8.onnx
"""
import sys
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import argparse
import os
from pathlib import Path

ML_ROOT = Path(__file__).resolve().parents[1]          # ml/
sys.path.insert(0, str(ML_ROOT))

import numpy as np                                      # noqa: E402
import torch                                            # noqa: E402
from PIL import Image                                   # noqa: E402

from model.YOLOV8 import YoloBody                       # noqa: E402
from train.qat_quantizer import convert_qat, count_quant_nodes, prepare_qat   # noqa: E402
from utils.utils import resize_image, preprocess_input  # noqa: E402


class _InferenceOnly(torch.nn.Module):
    def __init__(self, model: torch.nn.Module):
        super().__init__()
        self.model = model

    def forward(self, x):
        dbox, cls, *_ = self.model(x)
        return dbox, cls


def load_calib_images(txt_path, limit):
    paths = []
    with open(txt_path, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            paths.append(ln.split()[0])
        if len(paths) >= limit:
            return paths[:limit]
    return paths


def calibrate(prepared, calib_paths, input_shape, device, verbose=True):
    ih, iw = input_shape
    prepared.eval()
    n = 0
    with torch.no_grad():
        for p in calib_paths:
            image = Image.open(p).convert("RGB")
            resized = resize_image(image, (iw, ih), True)
            blob = np.transpose(
                preprocess_input(np.array(resized, dtype="float32")), (2, 0, 1)
            )[None]
            t = torch.from_numpy(blob).to(device)
            prepared(t)
            n += 1
    if verbose:
        print(f"[PTQ] 校准完成：前向 {n} 张图片")


def load_fp32_weights(model, ckpt_path):
    ck = torch.load(ckpt_path, map_location="cpu", weights_only=False)
    if isinstance(ck, dict) and "model" in ck:
        ck = ck["model"]
    elif isinstance(ck, dict) and "ema" in ck:
        ck = ck["ema"]
    ret = model.load_state_dict(ck, strict=True)
    print(f"[PTQ] 加载 FP32 权重: {ckpt_path} (missing={len(ret.missing_keys)} unexpected={len(ret.unexpected_keys)})")


def main():
    ap = argparse.ArgumentParser(description="PTQ -> QDQ ONNX INT8 导出")
    ap.add_argument("--fp32", default="weights/MERGED_CMP_FP32/best_epoch_weights.pth")
    ap.add_argument("--calib-txt", default="datasets/merged/2025_val.txt")
    ap.add_argument("--calib-images", type=int, default=64,
                    help="用前 N 张 val 图做校准（覆盖各亮度档位）")
    ap.add_argument("--out", default="deploy/yolo_ptq_int8.onnx")
    ap.add_argument("--classes", default="datasets/merged/label_merged.txt")
    ap.add_argument("--input-shape", default="512,512")
    ap.add_argument("--phi", default="n")
    ap.add_argument("--opset", type=int, default=18)
    ap.add_argument("--device", default="cpu")
    args = ap.parse_args()

    # 类别数从标签文件读
    with open(args.classes, encoding="utf-8") as f:
        num_classes = len([ln for ln in f if ln.strip()])
    ih, iw = [int(x) for x in args.input_shape.split(",")]
    input_shape = [ih, iw]
    device = torch.device(args.device)

    example = (torch.zeros(1, 3, ih, iw, device=device),)

    print(f"[PTQ] 重建 FP32 YoloBody（{num_classes} 类，phi={args.phi}，输入 {input_shape}）")
    model = YoloBody(input_shape, num_classes, args.phi, pretrained=False)
    load_fp32_weights(model, args.fp32)

    print(f"[PTQ] prepare_pt2e（量化 64 个 conv，激活/权重观察器）...")
    prepared, qz = prepare_qat(model, example)
    print(f"[PTQ] 标注卷积: {qz._n}")

    calib_paths = load_calib_images(args.calib_txt, args.calib_images)
    print(f"[PTQ] 校准图片数: {len(calib_paths)}")
    calibrate(prepared, calib_paths, input_shape, device)

    print("[PTQ] convert_pt2e -> QDQ ...")
    converted = convert_qat(prepared)
    print("[PTQ] 量化节点统计:", count_quant_nodes(converted))

    out_path = args.out
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    print(f"[PTQ] torch.onnx.export -> {out_path} (opset {args.opset})")
    torch.onnx.export(
        _InferenceOnly(converted),
        example,
        out_path,
        opset_version=args.opset,
        input_names=["images"],
        output_names=["dbox", "cls"],
        dynamo=True,
    )
    print(f"[PTQ] 完成: {out_path} ({os.path.getsize(out_path)} bytes)")

    import onnx
    m = onnx.load(out_path)
    onnx.checker.check_model(m)
    inp = m.graph.input[0]
    out_names = [o.name for o in m.graph.output]
    print(f"[PTQ] onnx 校验通过: input={inp.name}"
          f"{[d.dim_value or d.dim_param for d in inp.type.tensor_type.shape.dim]} outputs={out_names}")

    # ORT vs 转换后 QDQ 图数值一致性
    import onnxruntime as ort
    sess = ort.InferenceSession(out_path, providers=["CPUExecutionProvider"])
    x = np.random.rand(1, 3, ih, iw).astype(np.float32)
    onx_dbox, onx_cls = sess.run(None, {"images": x})
    with torch.no_grad():
        ref = converted(torch.from_numpy(x))
        ref_dbox, ref_cls = ref[0].numpy(), ref[1].numpy()
    print(f"[PTQ] 数值校验: dbox {onx_dbox.shape} max_abs_diff={np.abs(onx_dbox - ref_dbox).max():.6g}, "
          f"cls {onx_cls.shape} max_abs_diff={np.abs(onx_cls - ref_cls).max():.6g}")


if __name__ == "__main__":
    main()