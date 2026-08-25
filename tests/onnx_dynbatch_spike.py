# -*- coding: utf-8 -*-
"""Spike：已导出的固定 batch=1 QDQ INT8 ONNX 改写为动态 batch。

背景：YoloBody DFL 使 torch.export 动态 batch 崩溃；图里 batch 被固化进
Reshape 的 shape 常量（如 [1,4,16,5376]、[1,73,-1]）。绕过 torch.export，
直接在图上做「动态 reshape 注入」：
    Shape(images) -> Gather([0]) -> scalar_N
    Concat([scalar_N, 其余维度常量]) -> Reshape.shape
并放宽 input/output 的 batch 维为符号 N。

用法（ml/ 下）:
    E:\\MiniConda\\envs\\Aging\\python.exe tests/onnx_dynbatch_spike.py
"""
import sys
from pathlib import Path
ML = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ML))
for s in (sys.stdout, sys.stderr):
    if hasattr(s, "reconfigure"):
        try: s.reconfigure(encoding="utf-8")
        except OSError: pass

import numpy as np
import onnx
from onnx import helper, TensorProto

SRC = ML / "ml" / "deploy" / "yolo_ptq_int8.onnx"
DST = ML / "ml" / "deploy" / "yolo_ptq_int8_dyn.onnx"


def _i64(name, arr):
    return onnx.numpy_helper.from_array(np.asarray(arr, dtype=np.int64), name)


def make_dynamic(src, dst, dim_name="N", input_name="images"):
    m = onnx.load(str(src))
    g = m.graph

    # ---------------- 1) 放宽 input/output 的 batch 维 ----------------
    for inp in g.input:
        tt = inp.type.tensor_type
        d = tt.shape.dim
        if len(d) >= 4 and d[0].dim_value == 1:
            d[0].dim_value, d[0].dim_param = 0, dim_name
            print(f"input {inp.name}: batch -> {dim_name}")
    for out in g.output:
        d = out.type.tensor_type.shape.dim
        if len(d) >= 1 and d[0].dim_value == 1:
            d[0].dim_value, d[0].dim_param = 0, dim_name
            print(f"output {out.name}: batch -> {dim_name}")

    # ---------------- 2) 常量 shape 收集（initializer + Constant） ----------------
    init = {}
    for it in g.initializer:
        try: init[it.name] = onnx.numpy_helper.to_array(it)
        except Exception: pass
    cnode = {}
    for n in g.node:
        if n.op_type == "Constant":
            a = next((x for x in n.attribute if x.name == "value"), None)
            if a is not None and a.t is not None:
                try: cnode[n.output[0]] = onnx.numpy_helper.to_array(a.t)
                except Exception: pass
    shape_of = {**init, **cnode}

    # ---------------- 3) 动态 reshape 注入 ----------------
    gid = 0
    fixed = []
    node_list = list(g.node)
    for n in node_list:
        if n.op_type != "Reshape" or len(n.input) < 2:
            continue
        shp_name = n.input[1]
        arr = shape_of.get(shp_name)
        if arr is None or arr.ndim == 0 or arr.dtype.kind not in "iu":
            continue
        S = arr.astype(int).reshape(-1).tolist()
        if not S or S[0] != 1:
            continue                      # 非 batch 固化的忽略
        rest = S[1:]                       # 含原有 -1 也保留（Concat 后仅一个 -1，合法）
        bn = f"{dim_name}_inj_{gid}"
        shape_o, idx_i, n_i, rest_i, cat_o = (
            f"{bn}_shape", f"{bn}_idx", f"{bn}_n", f"{bn}_rest", f"{bn}_cat")
        gid += 1
        # 注入组（必须在 reshape 之前，保持拓扑序）
        grp = [
            helper.make_node("Shape", [input_name], [shape_o]),
            helper.make_node("Gather", [shape_o, idx_i], [n_i], axis=0),
            helper.make_node("Concat", [n_i, rest_i], [cat_o], axis=0),
        ]
        idx = next((i for i, x in enumerate(g.node) if x is n), None)
        for k, newn in enumerate(grp):
            g.node.insert(idx + k, newn)
        g.initializer.append(_i64(idx_i, [0]))
        g.initializer.append(_i64(rest_i, rest))
        # Repoint Reshape shape 输入
        n.input[1] = cat_o
        fixed.append((n.name or "?", S, rest))

    if fixed:
        print(f"动态 reshape 注入 ({len(fixed)} 处):")
        for nm, S, rest in fixed:
            print(f"  {nm}: const {S} -> concat([N, {rest}])")
    else:
        print("未发现需动态化的 Reshape")

    # 若旧 shape 常量只被本 reshape 引用，改为 unused（保留无害）
    onnx.checker.check_model(m)
    m.ir_version = max(m.ir_version, 8)
    onnx.save_model(m, str(dst))           # 默认内联权重 -> 自包含
    print(f"changed model: {dst}")
    return dst


def run_and_check(path, B):
    import onnxruntime as ort
    so = ort.SessionOptions()
    so.log_severity_level = 3
    sess = ort.InferenceSession(path, so, providers=["CPUExecutionProvider"])
    print(f"ORT input shape: {sess.get_inputs()[0].shape}")
    rng = np.random.default_rng(0)
    x = rng.random((B, 3, 512, 512), dtype=np.float32)
    dbox, cls = sess.run(None, {"images": x})
    assert dbox.shape[0] == B and cls.shape[0] == B, (dbox.shape, cls.shape)
    # 与 batch=1 单跑逐帧对比（INT8 确定）
    x1 = x[:1]
    d1, c1 = sess.run(None, {"images": x1})
    dd = max(np.abs(dbox[:1] - d1).max(),
             np.abs(dbox[B // 2:B // 2 + 1] - sess.run(None, {"images": x[B // 2:B // 2 + 1]})[0]).max())
    cc = np.abs(cls[:1] - c1).max()
    print(f"batch={B}: dbox {dbox.shape}, cls {cls.shape}; 切片vs单跑 dbox={dd:.6g} cls={cc:.6g}")
    return True


if __name__ == "__main__":
    print("== 1) 动态 reshape 注入 + batch 放宽 ==")
    dyn = make_dynamic(SRC, DST)
    print("== 2) ORT 校验(CPU) batch=1/4/16 ==")
    for B in (1, 4, 16):
        run_and_check(dyn, B)
    print("OK: 动态 batch ONNX 改写并校验通过", DST)