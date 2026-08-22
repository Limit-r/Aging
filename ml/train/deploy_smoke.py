# -*- coding: utf-8 -*-
"""部署产物冒烟验证（训练完自动部署后执行）。

从 `ml/deploy/` 集中目录加载已部署的 YOLO 检测模型 + TinyConv 亮灭分类器，
并在统一训练集中取一张真实图片做推理，验证「部署 → 可加载 → 可推理」链路成立。

设计：独立可执行脚本，由 GUI 训练完成回调以子进程方式运行，避免把 torch 载入 GUI 进程。
只做「能加载、能跑通、输出有目标」的轻量验证，不做标注比对的完整评估。

用法（在 ml/ 下运行）：
    python train/deploy_smoke.py

退出码：
    0  = 验证通过
    nonzero = 任一环节失败（见 stderr 输出）
"""
import os
import sys
import time

# 强制 UTF-8 输出，避免 Windows 默认 GBK 编码无法打印 emoji 而崩溃
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from pathlib import Path

# 项目根（deploy_smoke.py -> train -> ml -> 项目根）
PROJECT_ROOT = Path(__file__).resolve().parents[2]
ML_ROOT = PROJECT_ROOT / 'ml'
sys.path.insert(0, str(ML_ROOT))

import torch  # noqa: E402

def _fail(msg: str, phase: str = ""):
    elapsed = "(%.1fs)" % (time.time() - _T0) if "_T0" in globals() else ""
    print("[SMOKE] ! 阶段%s失败 %s: %s" % (phase, elapsed, msg), file=sys.stderr)
    sys.exit(1)


_T0 = time.time()
_LAST_T = [_T0]  # 上一阶段时间戳（list 便于闭包内更新）

def _mark(name: str):
    now = time.time()
    step = now - _LAST_T[0]          # 本阶段耗时
    total = now - _T0                # 累计耗时
    _LAST_T[0] = now
    print("[SMOKE] ✔ %-20s 阶段耗时 %.2fs · 累计 %.2fs" % (name, step, total))


def main():
    deploy = ML_ROOT / 'deploy'
    model_pt = deploy / 'yolo_best_deploy.pt'
    weights_pth = deploy / 'yolo_best_epoch_weights.pth'
    labels_txt = deploy / 'label_merged.txt'
    cls_pth = deploy / 'tinyconv_best.pth'

    print("[SMOKE] ==== 部署产物冒烟验证开始 ====")
    print("[SMOKE] 部署目录:", deploy)
    for name, p in (("部署模型", model_pt), ("权重", weights_pth),
                    ("类别表", labels_txt), ("分类器", cls_pth)):
        ok = "存在" if p.exists() else "缺失"
        print("[SMOKE]   %-6s [%s] %s" % (name, ok, p))
        if not p.exists():
            _fail("部署产物缺失: %s (%s)" % (name, p), phase="检查产物")
    _mark("产物存在性检查")

    from utils.utils import get_classes          # noqa: E402
    from utils.utils_bbox import DecodeBox        # noqa: E402
    from utils.det_eval import load_model          # noqa: E402
    from classifier.infer import LEDClassifier     # noqa: E402

    class_names, num_classes = get_classes(str(labels_txt))
    print("[SMOKE] 类别 (%d): %s" % (num_classes, class_names))

    input_shape = (512, 512)
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print("[SMOKE] 设备: %s" % device)

    # ---- 1) 加载 YOLO 部署模型 ----
    weights_path = model_pt if model_pt.exists() else weights_pth
    print("[SMOKE] 加载 YOLO: %s (num_classes=%d, phi=n, input=%s)"
          % (weights_path.name, num_classes, input_shape))
    yolo = load_model(str(weights_path), num_classes, 'n', input_shape, device)
    decodebox = DecodeBox(num_classes=num_classes, input_shape=input_shape)
    print("[SMOKE] YOLO 模型加载完成:", weights_path.name)
    _mark("YOLO 模型加载")

    # ---- 2) 加载 TinyConv 分类器 ----
    classifier = LEDClassifier(weight_path=str(cls_pth), device=device)
    print("[SMOKE] TinyConv 分类器加载完成")
    _mark("分类器加载")

    # ---- 3) 取一张真实训练图推理 ----
    train_txt = ML_ROOT / 'datasets' / 'merged' / '2025_train.txt'
    if not train_txt.exists():
        _fail("找不到训练数据清单: %s" % train_txt, phase="定位训练图")
    img_path = None
    with open(train_txt, encoding='utf-8') as f:
        for ln in f:
            ln = ln.strip()
            if ln:
                img_path = ln.split(" ")[0]
                break
    if not img_path or not Path(img_path).exists():
        _fail("训练清单中无可用图片路径: %s" % (img_path or "empty"), phase="定位训练图")
    print("[SMOKE] 冒烟图片:", img_path)

    import cv2       # noqa: E402
    import numpy as np  # noqa: E402
    img = cv2.imread(img_path)
    if img is None:
        _fail("无法读取冒烟图片: %s" % img_path, phase="读取图片")
    print("[SMOKE] 图片尺寸: %s (HxWxC=%dx%dx%d)"
          % ((img.shape[1], img.shape[0], img.shape[2]), img.shape[0], img.shape[1], img.shape[2]))

    # 复用推理流程：必要时可与 infer_fp 保持一致，此处仅验证链路可跑通
    from utils.det_eval import run_image       # noqa: E402
    outdir = PROJECT_ROOT / 'detect' / 'outputs' / 'smoke'
    outdir.mkdir(parents=True, exist_ok=True)
    run_image(img_path, str(outdir), yolo, decodebox, class_names, num_classes,
              input_shape, device, conf=0.15, nms=0.45, label='SMOKE')
    _mark("YOLO 跑图推断")

    # ---- 4) 分类器也跑一次，确认推理不报错 ----
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    cx, cy = w // 2, h // 2
    roi = img[cy - 16:cy + 16, cx - 16:cx + 16]
    if roi.size:
        pred, conf = classifier.predict(roi)
        print("[SMOKE] 分类器冒烟: pred=%s conf=%.3f" % ("H" if pred == 1 else "L", conf))
    _mark("分类器跑图推断")

    print("[SMOKE] [OK] 部署产物冒烟验证通过（可加载、可推理）")
    print("[SMOKE] 可视化输出:", outdir)
    print("[SMOKE] ==== 冒烟验证结束，总耗时 %.2fs ====" % (time.time() - _T0))


if __name__ == '__main__':
    main()