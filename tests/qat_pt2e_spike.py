# -*- coding: utf-8 -*-
"""QAT/pt2e spike v3：自定义 Quantizer，对 YoloBody 的每个 nn.Conv2d 直接量化（QAT）。

x86_inductor_quantizer 因 SiLU 不在 unary 融合集，实际不插入量化(fake_quant=0)。
本 spike 用自定义 Quantizer：conv 权重 per-channel/激活 per-tensor 的 QAT fake-quant。
conv 输出经 QDQ 回到 FP32，DFL 的 view/softmax 天然兼容，实现「结构化部分量化」。
"""
import os
import sys
import traceback

ML = r"d:\Aging\ml"
if ML not in sys.path:
    sys.path.insert(0, ML)
os.chdir(ML)

import torch  # noqa: E402
import torch.onnx  # noqa: E402
from model.YOLOV8 import YoloBody  # noqa: E402

INPUT_SHAPE = (512, 512)
NUM_CLASSES = 9
PHI = "n"
DEPLOY = r"d:\Aging\ml\deploy\yolo_best_deploy.pt"

# ---- 自定义 Quantizer：直接量化每个 conv（QAT, SiLU 保留 FP32）----
from torch.ao.quantization.quantizer.quantizer import (  # noqa: E402
    Quantizer, QuantizationAnnotation, QuantizationSpec)
from torch.ao.quantization.fake_quantize import FusedMovingAvgObsFakeQuantize  # noqa: E402
from torch.ao.quantization.observer import (  # noqa: E402
    MovingAverageMinMaxObserver, MovingAveragePerChannelMinMaxObserver)


def _fq(observer, qmin, qmax, dtype, qscheme, ch_axis=None):
    args = dict(observer=observer, quant_min=qmin, quant_max=qmax,
                dtype=dtype, qscheme=qscheme)
    if ch_axis is not None:
        args["ch_axis"] = ch_axis
    return FusedMovingAvgObsFakeQuantize.with_args(**args)


def _conv_targets():
    seen = set()
    seen.add("aten.convolution")
    return seen


class ConvSiluQuantizer(Quantizer):
    def __init__(self):
        self.act_spec = QuantizationSpec(
            dtype=torch.uint8, is_dynamic=False, qscheme=torch.per_tensor_affine,
            quant_min=0, quant_max=255,
            observer_or_fake_quant_ctr=_fq(MovingAverageMinMaxObserver, 0, 255,
                                           torch.quint8, torch.per_tensor_affine))
        self.w_spec = QuantizationSpec(
            dtype=torch.int8, is_dynamic=False, qscheme=torch.per_channel_symmetric,
            quant_min=-128, quant_max=127, ch_axis=0,
            observer_or_fake_quant_ctr=_fq(MovingAveragePerChannelMinMaxObserver,
                                           -128, 127, torch.qint8,
                                           torch.per_channel_symmetric, 0))

    def annotate(self, model):
        n_conv = 0
        for node in model.graph.nodes:
            if node.op == "call_function" and (
                    "conv2d" in str(node.target) or "convolution" in str(node.target)):
                args = node.args
                qmap = {args[0]: self.act_spec, args[1]: self.w_spec}
                node.meta["quantization_annotation"] = QuantizationAnnotation(
                    input_qspec_map=qmap)
                n_conv += 1
        self._n = n_conv
        return model

    def validate(self, model):
        pass


def build():
    model = YoloBody(INPUT_SHAPE, NUM_CLASSES, PHI, pretrained=False)
    try:
        sd = torch.load(DEPLOY, map_location="cpu", weights_only=False)
        w = sd.get("model", sd)
        model.load_state_dict(w, strict=False)
    except Exception:
        pass
    return model.eval()


def main():
    phase = "构造"
    try:
        model = build()
        example = torch.randn(1, 3, *INPUT_SHAPE)
        model(example)
        ref = model(example)
        print(f"[构造] OK  forward输出={len(ref)}")

        phase = "export"
        gm = torch.export.export(model, (example,))
        gmmod = gm.module()
        ct = sorted({str(n.target) for n in gmmod.graph.nodes
                     if n.op == "call_function" and "conv" in str(n.target)})
        print(f"[export] OK  nodes={len(gm.graph.nodes)} conv-like targets={ct}")

        phase = "prepare_pt2e(自定义Quantizer)"
        from torch.ao.quantization.quantize_pt2e import prepare_pt2e, convert_pt2e
        qz = ConvSiluQuantizer()
        prepared = prepare_pt2e(gmmod, qz)
        print(f"[annotate] 标注的 conv 数量={getattr(qz, '_n', '???')}")
        with torch.no_grad():
            prepared(example)
        fq = sum(1 for n in prepared.graph.nodes if "fake_quant" in n.name)
        print(f"[prepare_pt2e] OK  fake_quant 节点数={fq}")

        phase = "convert_pt2e"
        quantized = convert_pt2e(prepared)
        with torch.no_grad():
            out = quantized(example)
        print(f"[convert_pt2e] OK  前向输出数={len(out)}, dbox dtype={out[0].dtype}")
        dq = sum(1 for n in quantized.graph.nodes
                 if "quantized_decomposed" in str(n.target))
        print(f"[convert_pt2e] quantized_decomposed 算子数={dq}")

        phase = "onnx export(QDQ) legacy"
        onnx_path = r"d:\Aging\ml\_qat_qdq.onnx"
        torch.onnx.export(quantized, (example,), onnx_path,
                          opset_version=17,
                          input_names=["input"], output_names=["output"])
        import onnx  # noqa
        om = onnx.load(onnx_path)
        ops = sorted({n.op_type for n in om.graph.node})
        has_qdq = ("QuantizeLinear" in ops) or ("DequantizeLinear" in ops)
        print(f"[onnx-export] OK  Q/DQ 出现={has_qdq}")
        print(f"[onnx-export] 含量化算子: {[o for o in ops if 'lizeLinear' in o]}")
    except Exception:
        print(f"\n[FAIL @ {phase}]")
        traceback.print_exc()
        return 1
    print("\n[PT2E SPIKE v3 DONE]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())