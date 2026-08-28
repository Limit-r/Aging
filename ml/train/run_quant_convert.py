# -*- coding: utf-8 -*-
"""量化转换驱动：FP32 → PTQ INT8 ONNX（固定 batch）→ 动态 batch → 部署目录。

把「训练完成后的 FP32 模型」一键转换为视频推理/静默监控实际加载的部署模型，
覆盖 `ml/deploy/` 下的固定名文件（引擎 `DetectionEngine.deployed_paths()` 引用）：

    deploy/yolo_ptq_int8_dyn.onnx        512² 动态 batch（交互 / 视频检测，保精度）
    deploy/yolo_ptq_int8_320_dyn.onnx    320² 动态 batch（54 路静默监控，高吞吐）

流程（串行调用既有脚本，均以 ml/ 为工作目录）：
    1) train/ptq_onnx.py         FP32 → QDQ ONNX INT8（固定 batch=1）
    2) train/dynamicize_onnx.py  固定 batch → 动态 batch（注入动态 Reshape + 自校验）
    3) 清理临时固定 batch 文件

用法（裸终端 / 训练页 CONVERT 阶段）：
    python ml/train/run_quant_convert.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

# ml/ = 工作目录与相对路径基准（ptq_onnx 内部路径相对 ML 根解析）
ML_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEPLOY_DIR = os.path.join(ML_ROOT, "deploy")

# 部署目录固定名（与 ml/vision/engine.py deployed_paths() 保持一致）
ONNX_DYN_512 = "yolo_ptq_int8_dyn.onnx"
ONNX_DYN_320 = "yolo_ptq_int8_320_dyn.onnx"

# 输入规格：512² 高精度 / 320² 监控
SIZES = [
    ("512,512", ONNX_DYN_512),
    ("320,320", ONNX_DYN_320),
]

# 训练输出的 FP32 源权重（相对 ml/）
FP32_WEIGHTS = os.path.join(ML_ROOT, "weights", "MERGED", "best_epoch_weights.pth")
CALIB_TXT = os.path.join(ML_ROOT, "datasets", "merged", "2025_val.txt")
CLASSES_TXT = os.path.join(ML_ROOT, "datasets", "merged", "label_merged.txt")


def _run(cmd, on_log=None) -> int:
    """在 ml/ 下运行命令，合并 stderr，实时回调日志。返回退出码。"""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    if on_log is not None:
        on_log("  $ " + " ".join(os.path.basename(c) if c.endswith(".py") else c
                                 for c in cmd))
    proc = subprocess.Popen(
        cmd, cwd=ML_ROOT, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        bufsize=1, universal_newlines=True,
        encoding="utf-8", errors="replace",
    )
    for raw in iter(proc.stdout.readline, ""):
        line = raw.rstrip("\r\n")
        if line and on_log is not None:
            on_log("  | " + line)
    proc.stdout.close()
    return proc.wait()


def convert_all(on_log=None) -> dict:
    """执行两套规格的量化转换并覆盖部署固定名。

    on_log(msg) 可选回调。返回 {"ok": bool, "outputs": [绝对路径...], "error": str|None}。
    """
    outputs = []
    for shape, target_name in SIZES:
        if on_log is not None:
            on_log("== 量化转换 [%s] ==" % shape)
        temp = os.path.join(DEPLOY_DIR, "yolo_ptq_int8_%s_temp.onnx" % shape.replace(",", "_"))
        final = os.path.join(DEPLOY_DIR, target_name)

        # 1) PTQ 固定 batch 导出
        rc = _run([
            sys.executable, os.path.join(ML_ROOT, "train", "ptq_onnx.py"),
            "--fp32", FP32_WEIGHTS,
            "--calib-txt", CALIB_TXT,
            "--classes", CLASSES_TXT,
            "--input-shape", shape,
            "--out", temp,
        ], on_log)
        if rc != 0 or not os.path.exists(temp):
            return {"ok": False, "outputs": outputs,
                    "error": "PTQ 导出失败 [%s] (rc=%s)" % (shape, rc)}

        # 2) 动态 batch 改写 → 覆盖部署固定名
        rc = _run([
            sys.executable, os.path.join(ML_ROOT, "train", "dynamicize_onnx.py"),
            "--onnx", temp, "--out", final,
        ], on_log)
        if rc != 0 or not os.path.exists(final):
            return {"ok": False, "outputs": outputs,
                    "error": "动态 batch 改写失败 [%s] (rc=%s)" % (shape, rc)}
        outputs.append(final)
        # 清理临时固定 batch 文件（torch 导出会产生外部权重 .onnx.data 伴生文件）
        for p in (temp, temp + ".data"):
            if os.path.exists(p):
                os.remove(p)
        if on_log is not None:
            on_log("  完成 %s (%d bytes)" % (final, os.path.getsize(final)))

    update_manifest(on_log=on_log)
    return {"ok": True, "outputs": outputs, "error": None}


def update_manifest(on_log=None) -> None:
    """把量化产物登记进 ml/deploy/latest.json（保留既有字段，合并 onnx 条目）。

    引擎实际按固定文件名加载（不看清单），清单供确认当前生效模型与性能基线。
    与 deploy_models.py 的 5 键基础条目合并，避免被其覆盖后丢失 onnx 登记。
    """
    import json

    manifest_path = os.path.join(DEPLOY_DIR, "latest.json")
    manifest = {}
    try:
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
    except (OSError, ValueError):
        manifest = {}

    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    manifest["ts"] = ts
    base = ["yolo_best_deploy.pt", "yolo_best_epoch_weights.pth",
            "tinyconv_best.pth", "label_merged.txt"]
    onnx_names = [n for _, n in SIZES]
    files = []
    for n in base + onnx_names:
        if n not in files:
            files.append(n)
    manifest["files"] = files
    manifest["paths"]["onnx"] = os.path.join(DEPLOY_DIR, ONNX_DYN_512)
    manifest["paths"]["onnx_mon"] = os.path.join(DEPLOY_DIR, ONNX_DYN_320)
    manifest["onnx"] = {
        "interactive": "%s (512x512, 5376 anc, INT8)" % ONNX_DYN_512,
        "monitor": "%s (320x320, 2100 anc, INT8)" % ONNX_DYN_320,
        "monitor_fps_batch54_gpu": 381.0,   # 实测基线（RTX 5060 Ti, 320² batch=54）
        "target_fps_54ch": 216.0,
        "headroom_x": 381.0 / 216.0,
    }
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    if on_log is not None:
        on_log("  已更新部署清单 latest.json (ts=%s)" % ts)


if __name__ == "__main__":
    result = convert_all(on_log=print)
    if not result["ok"]:
        print("[convert] 失败:", result["error"])
        raise SystemExit(1)
    print("[convert] 量化转换完成，部署文件已覆盖:")
    for p in result["outputs"]:
        print("  -", p)
