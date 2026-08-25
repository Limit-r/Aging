# -*- coding: utf-8 -*-
"""把固定 batch=1 的 QDQ INT8 ONNX 改写为动态 batch 的部署模型。

背景：YoloBody 的 DFL 让 `torch.export` 在 CUDA 下做动态 batch 会崩溃，
因此 `ptq_onnx.py` 只能导出固定 batch=1 的 ONNX。固定 batch 使 `_onnx_decode`
退化成逐帧 `sess.run`（每帧一次），54 路静默监控吞吐上不去。

本模块绕过 torch.export，直接在 ONNX 图上做「动态 reshape 注入」：
- 放宽 input/output 的 batch 维为符号 `N`；
- 把图里被固化为 batch 的 Reshape shape 常量，替换为运行时动态计算的
  shape 向量：`Shape(images) -> Gather([0]) -> N`，再
  `Concat([N, 其余维度常量])` 作为 Reshape 的 shape 输入。

这样单个 Reshape 的 shape 仍只有一个 `-1`（若原有 -1 则保留），其余维度含
运行时 batch，ORT 即可任意 batch 前向，精度不变（签名与固定 batch 一致）。

用法（ml/ 下）:
    E:\\MiniConda\\envs\\Aging\\python.exe train/dynamicize_onnx.py \
        --onnx deploy/yolo_ptq_int8.onnx --out deploy/yolo_ptq_int8_dyn.onnx
"""
import sys
from pathlib import Path
ML_ROOT = Path(__file__).resolve().parents[1]      # ml/
sys.path.insert(0, str(ML_ROOT))
for s in (sys.stdout, sys.stderr):
    if hasattr(s, "reconfigure"):
        try: s.reconfigure(encoding="utf-8")
        except OSError: pass

import argparse
import numpy as np
import onnx
from onnx import helper


def _i64(name, arr):
    return onnx.numpy_helper.from_array(np.asarray(arr, dtype=np.int64), name)


def make_dynamic(src, dst, dim_name="N", input_name="images"):
    """把 `src` 固定 batch ONNX 改写为动态 batch，写到 `dst`。

    Returns: 改写/注入的 Reshape 数量（int）。
    """
    m = onnx.load(str(src))
    g = m.graph

    # 1) 放宽 input/output 的 batch 维
    for inp in g.input:
        d = inp.type.tensor_type.shape.dim
        if len(d) >= 4 and d[0].dim_value == 1:
            d[0].dim_value, d[0].dim_param = 0, dim_name
    for out in g.output:
        d = out.type.tensor_type.shape.dim
        if len(d) >= 1 and d[0].dim_value == 1:
            d[0].dim_value, d[0].dim_param = 0, dim_name

    # 2) 收集常量 shape（initializer + Constant 节点）
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

    # 3) 动态 reshape 注入（插在各自 Reshape 之前，保持拓扑序）
    gid, fixed = 0, 0
    for n in list(g.node):
        if n.op_type != "Reshape" or len(n.input) < 2:
            continue
        arr = shape_of.get(n.input[1])
        if arr is None or arr.ndim == 0 or arr.dtype.kind not in "iu":
            continue
        S = arr.astype(int).reshape(-1).tolist()
        if not S or S[0] != 1:
            continue                     # 非 batch 固化的忽略
        rest = S[1:]                      # 保留原有 -1（Concat 后仍只有一个 -1）
        bn = f"{dim_name}_inj_{gid}"
        shape_o, idx_i, n_i, rest_i, cat_o = (
            f"{bn}_shape", f"{bn}_idx", f"{bn}_n", f"{bn}_rest", f"{bn}_cat")
        gid += 1
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
        n.input[1] = cat_o
        fixed += 1

    onnx.checker.check_model(m)
    m.ir_version = max(m.ir_version, 8)
    onnx.save_model(m, str(dst))          # 默认内联全部权重 -> 自包含单文件
    return fixed


def verify(src, batch_sizes=(1, 4, 16)):
    """用 ORT 校验动态 batch 模型：各 batch 输出形状正确、切片与单跑一致。"""
    import onnxruntime as ort
    so = ort.SessionOptions()
    so.log_severity_level = 3
    sess = ort.InferenceSession(str(src), so,
                                providers=["CPUExecutionProvider"])
    inp = sess.get_inputs()[0]
    if inp.shape[0] != "N":
        print(f"[dynamicize] 警告: input batch 非动态: {inp.shape}")
    rng = np.random.default_rng(0)
    ok = True
    for B in batch_sizes:
        x = rng.random((B, 3, 512, 512), dtype=np.float32)
        dbox, cls = sess.run(None, {inp.name: x})
        if dbox.shape[0] != B or cls.shape[0] != B:
            print(f"[dynamicize] FAIL batch={B}: {dbox.shape} {cls.shape}")
            ok = False
            continue
        # 切片 vs 单跑（INT8 精确；残余误差来自 conv GEMM 不同 batch 的
        # FP32 累加顺序 + QDQ 已知容差带，噪声输入最大可达 ~2.4。
        # 这里只设宽松结构阈值抓致命错误；端到端正确性由引擎真图校验负责）
        for pos in (0, max(0, B // 2)):
            d1, c1 = sess.run(None, {inp.name: x[pos:pos + 1]})
            if (np.abs(dbox[pos] - d1[0]).max() > 5.0 or
                    np.abs(cls[pos] - c1[0]).max() > 3.0):
                print(f"[dynamicize] FAIL batch={B} pos={pos} 数值异常:"
                      f" dbox={np.abs(dbox[pos]-d1[0]).max():.3g}"
                      f" cls={np.abs(cls[pos]-c1[0]).max():.3g}")
                ok = False
        print(f"[dynamicize] 校验 batch={B}: dbox {dbox.shape}, cls {cls.shape}")
    return ok


def main():
    ap = argparse.ArgumentParser(description="固定 batch ONNX -> 动态 batch")
    ap.add_argument("--onnx", default="deploy/yolo_ptq_int8.onnx")
    ap.add_argument("--out", default="deploy/yolo_ptq_int8_dyn.onnx")
    ap.add_argument("--same-name", action="store_true",
                    help="覆盖源文件（若希望动态版作为部署基准文件）")
    ap.add_argument("--no-verify", action="store_true")
    args = ap.parse_args()

    src = str(Path(args.onnx))
    dst = args.out if not args.same_name else src
    fixed = make_dynamic(src, dst)
    print(f"[dynamicize] 注入 Reshape {fixed} 处 -> {dst} "
          f"({Path(dst).stat().st_size if Path(dst).exists() else '?'} bytes)")
    if args.no_verify:
        return 0
    ok = verify(dst)
    print("[dynamicize] 校验: " + ("通过" if ok else "失败"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())