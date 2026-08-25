# -*- coding: utf-8 -*-
"""QAT 可行性 spike：对 YoloBody 实测 prepare_qat -> forward -> convert -> QDQ ONNX。

目的：在改动训练脚本前，用最小代价验证 PyTorch `torch.ao.quantization` 对这个
自定义 YoloBody（Conv=conv+bn+SiLU、C2f、DFL，含 view/transpose/softmax）能否
完成「量化感知训练(fake-quant) + convert + 导出带 Q/DQ 的 ONNX 供 TensorRT」。

运行（在 ml/ 下）::
    E:\\MiniConda\\envs\\Aging\\python.exe tests_qat_spike.py
"""
import os
import sys
import traceback

ML = r"d:\Aging\ml"
if ML not in sys.path:
    sys.path.insert(0, ML)
os.chdir(ML)

import torch  # noqa: E402
import torch.ao.quantization as quant  # noqa: E402

from model.YOLOV8 import YoloBody  # noqa: E402

INPUT_SHAPE = (512, 512)
NUM_CLASSES = 9
PHI = "n"
DEPLOY = r"d:\Aging\ml\deploy\yolo_best_deploy.pt"
ONNX_PATH = r"d:\Aging\ml\_qat_spike.onnx"


def build_weighted_model():
    model = YoloBody(INPUT_SHAPE, NUM_CLASSES, PHI, pretrained=False)
    try:
        sd = torch.load(DEPLOY, map_location="cpu", weights_only=False)
        w = sd.get("model", sd)
    except Exception:
        w = {}
    if isinstance(w, dict):
        model.load_state_dict(w, strict=False)
    model.eval()
    return model


def count_fake_quant(model):
    n = sum(1 for m in model.modules()
            if hasattr(m, "is_quantized") is False and
            type(m).__name__ in ("FakeQuantize", "FusedMovingAvgObsFakeQuantize") or
            "FakeQuantize" in type(m).__name__)
    return n


def main():
    phase = "构造模型"
    try:
        model = build_weighted_model()
        dummy = torch.randn(1, 3, *INPUT_SHAPE)
        # 保持输出结构参考
        ref = model(dummy)
        print(f"[构造] OK  forward输出 %d 个张量, 主输出: {tuple(ref[1].shape)}, {tuple(ref[2][0].shape)}" % len(ref))

        phase = "prepare_qat"
        model.train()  # prepare_qat 仅接受 training 模式
        model.qconfig = quant.get_default_qat_qconfig("qnnpack")
        try:
            qm = quant.prepare_qat(model, inplace=True)
        except TypeError:
            qm = model
            model.qconfig = quant.QConfig(
                activation=quant.FakeQuantize.with_args(observer=quant.MovingAverageMinMaxObserver,
                                                        quant_min=0, quant_max=255, dtype=torch.quint8),
                weight=quant.FakeQuantize.with_args(observer=quant.MinMaxObserver,
                                                    quant_min=-128, quant_max=127, dtype=torch.qint8))
        fq = count_fake_quant(model)
        print(f"[prepare_qat] OK  检测到 FakeQuantize 模块数: {fq}")

        phase = "forward(train)"
        model.train()
        out = model(dummy)
        print(f"[forward-train] OK  输出 dtype: {out[1].dtype}")

        phase = "convert"
        model.eval()
        quant.convert(model, inplace=True)
        conv = model(dummy)
        print(f"[convert] OK  convert 后能前向, 输出 count={len(conv)}, dbox dtype={conv[0].dtype}")
        int8_layers = sum(1 for m in model.modules()
                          if type(m).__name__.startswith("QuantizedConv") or "Quantized" in type(m).__name__)
        print(f"[convert] 量化卷积层数: {int8_layers}")

        phase = "onnx export (QDQ)"
        model.eval()
        torch.onnx.export(model, dummy, ONNX_PATH,
                          input_names=["input"], output_names=["output"],
                          opset_version=13, do_constant_folding=True)
        import onnx
        m = onnx.load(ONNX_PATH)
        op_names = sorted({n.op_type for n in m.graph.node})
        print(f"[onnx] OK  节点总览: {op_names}")
        print(f"[onnx] 含 Q/DQ: {'QuantizeLinear' in op_names or 'DequantizeLinear' in op_names}")
    except Exception:
        print(f"\n[FAIL @ {phase}]")
        traceback.print_exc()
        return 1
    print("\n[SPIKE DONE]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())