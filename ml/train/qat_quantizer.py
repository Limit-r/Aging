# -*- coding: utf-8 -*-
"""QAT 结构化部分量化——自定义 Quantizer（面向 torch2.8 + SiLU 的 YoloBody）。

背景（详见 docs/ 与 memory）：
- torch2.8 已废弃 eager quantization（2.10 移除），torchao 0.18 需 torch>=2.11 与 2.8 不兼容；
- x86_inductor_quantizer 因 SiLU 不在 unary 融合集，实际不插入任何量化；
- 全模型 INT8 在 DFL(view/transpose/softmax) 处结构上不可行（只能吃 FP32）。

因此采用「自定义 Quantizer + torch2.8 内置 pt2e」实现结构化部分量化：
- 只量化每个 nn.Conv2d 的权重（per-channel symmetric）与激活（per-tensor affine）；
- conv 输出经 QDQ 回到 FP32，SiLU / DFL 保持 FP32，天然兼容不破坏结构；
- QAT 训练阶段前向即插入了 FakeQuantize(fake-quant) 模拟 INT8 精度损失。

使用：训练时关闭 fp16，走 prepare_pt2e -> (前向校准/训练) -> convert_pt2e；
convert 后得到含 quantized_decomposed(QDQ) 算子的 GraphModule，可再导出 QDQ ONNX / TensorRT。
"""
from __future__ import annotations

import torch
from torch.ao.quantization import allow_exported_model_train_eval
from torch.ao.quantization.fake_quantize import FusedMovingAvgObsFakeQuantize
from torch.ao.quantization.observer import (
    MovingAverageMinMaxObserver,
    MovingAveragePerChannelMinMaxObserver,
)
from torch.ao.quantization.quantizer.quantizer import (
    QuantizationAnnotation,
    QuantizationSpec,
    Quantizer,
)

__all__ = [
    "ConvSiluQuantizer",
    "prepare_qat",
    "convert_qat",
    "count_quant_nodes",
]


def _fq(observer, qmin: int, qmax: int, dtype, qscheme, ch_axis=None):
    """构造 QAT 用的 FusedMovingAvgObsFakeQuantize 构造函数（with_args 返回类工厂）。"""
    args = dict(
        observer=observer,
        quant_min=qmin,
        quant_max=qmax,
        dtype=dtype,
        qscheme=qscheme,
    )
    if ch_axis is not None:
        args["ch_axis"] = ch_axis
    return FusedMovingAvgObsFakeQuantize.with_args(**args)


def _is_conv(node) -> bool:
    return node.op == "call_function" and (
        "conv2d" in str(node.target) or "convolution" in str(node.target)
    )


class ConvSiluQuantizer(Quantizer):
    """只量化每个卷积的权重/激活，保留 SiLU、BN 折叠及 DFL 解码为 FP32。

    权重：per-channel symmetric INT8；激活：per-tensor affine UINT8。
    采用 MovingAverage 观察器 + FusedMovingAvgObsFakeQuantize，支持训练时 QAT。
    """

    def __init__(self):
        self.act_spec = QuantizationSpec(
            dtype=torch.uint8,
            is_dynamic=False,
            qscheme=torch.per_tensor_affine,
            quant_min=0,
            quant_max=255,
            observer_or_fake_quant_ctr=_fq(
                MovingAverageMinMaxObserver, 0, 255,
                torch.quint8, torch.per_tensor_affine,
            ),
        )
        self.w_spec = QuantizationSpec(
            dtype=torch.int8,
            is_dynamic=False,
            qscheme=torch.per_channel_symmetric,
            quant_min=-128,
            quant_max=127,
            ch_axis=0,
            observer_or_fake_quant_ctr=_fq(
                MovingAveragePerChannelMinMaxObserver,
                -128, 127, torch.qint8, torch.per_channel_symmetric, 0,
            ),
        )
        self._n = 0

    def annotate(self, model):
        n_conv = 0
        for node in model.graph.nodes:
            if not _is_conv(node):
                continue
            args = node.args
            # input edge (activation) + weight（注意 annotation key 为单数复数均可，
            # 官方约定用单数 quantizer.py 的 key；此处显式写单数字典兼容 prepare_pt2e）
            qmap = {args[0]: self.act_spec, args[1]: self.w_spec}
            node.meta["quantization_annotation"] = QuantizationAnnotation(
                input_qspec_map=qmap
            )
            n_conv += 1
        self._n = n_conv
        return model

    def validate(self, model):
        """默认不做额外校验；子类可覆加载入约束。"""
        pass


def prepare_qat(model, example_input, quantizer=None):
    """把训练模型转换为 QAT 就绪模型（插入 FakeQuantize 节点）。

    参数：
        model:         待量化模型（调用方负责 load_state_dict、置 train 或 eval）
        example_input:  用于 torch.export 的示例输入（元组）
        quantizer:      自定义 Quantizer 实例（默认 ConvSiluQuantizer）
    返回：
        (prepared, quantizer) —— prepared 为可训练的 GraphModule，直接替换原模型
        参与训练/前向校准；quantizer 记录了标注的卷积数量。
    """
    from torch.ao.quantization.quantize_pt2e import prepare_pt2e

    qz = quantizer or ConvSiluQuantizer()

    # 预热惰性缓存：YoloBody 的 anchors/strides/shape 是 forward 内延迟生成的实例属性，
    # torch.export 拒绝在 traced forward 里"新建"属性。先跑一次前向把它们物化。
    was_training = model.training
    model.eval()
    with torch.no_grad():
        model(*example_input)
    if was_training:
        model.train()

    # 静态导出：torch.export 会把示例输入的 batch 尺寸固化为常量，
    # 因此 example_input 的 batch 必须与训练/推理实际 batch 一致（训练 batch=2）。
    # 注意：不要在这里用动态 batch（Dim DYNAMIC），YoloBody 的 DFL view 派生出的
    # batch 整除约束会让 torch.export 在 CUDA 下崩溃（AssertionError batch < ...）。
    # 评估侧若需不同 batch，请另行用匹配 batch 的推理（见 EvalCallback 的 batch 处理）。
    gm = torch.export.export(model, example_input).module()
    prepared = prepare_pt2e(gm, qz)
    # pt2e 导出的模型默认禁用 train()/eval()；放开以便接入现有训练循环（Dataset/BatchNorm 等）。
    allow_exported_model_train_eval(prepared)
    return prepared, qz


def convert_qat(prepared):
    """把 QAT(训练/校准) 完成的模型转换为真正的整型结构（含 QDQ 算子）。"""
    from torch.ao.quantization.quantize_pt2e import convert_pt2e

    return convert_pt2e(prepared)


def count_quant_nodes(graph_module) -> dict:
    """统计量化相关节点数量，便于日志/校验：{'fake_quant': n, 'q_dq': n}。"""
    fq = sum(1 for n in graph_module.graph.nodes if "fake_quant" in n.name)
    qd = sum(
        1
        for n in graph_module.graph.nodes
        if "quantized_decomposed" in str(n.target)
    )
    return {"fake_quant": fq, "q_dq": qd}