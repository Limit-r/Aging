# -*- coding: utf-8 -*-
"""QAT INT8 ONNX 端到端推理测试脚本（面向部署链路验证）。

从 `ml/deploy/yolo_qat_int8.onnx`（QDQ ONNX，batch=1，512²，输出 dbox/cls）
加载模型，输入一张测试图片做完整推理，可视化检测框并保存结果。

设计：
- 用 onnxruntime 跑 ONNX，不加载 pytorch 模型（这正是验证部署链路的意义）。
- 复用项目已有的解码/后处理：`DecodeBox.decode_onnx_box` + `non_max_suppression`
  （针对只输出 dbox/cls 两头的简化 ONNX）。
- 预处理做 letterbox 到 512×512（与训练一致），输入归一化除 255。
- 类别/Detch 复用 `ml/deploy/label_merged.txt`（9 类）。

用法（在 ml/ 下运行）：
    E:\\MiniConda\\envs\\Aging\\python.exe train/infer_qat_onnx.py
    E:\\MiniConda\\envs\\Aging\\python.exe train/infer_qat_onnx.py --img <path> --conf 0.15 --nms 0.45
"""
import argparse
import io
import os
import sys
from pathlib import Path

# 强制 UTF-8，避免 Windows GBK 打印 emoji/中文崩
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ML_ROOT = Path(__file__).resolve().parents[1]          # ml/
PROJECT_ROOT = ML_ROOT.parent                          # 项目根
sys.path.insert(0, str(ML_ROOT))

import numpy as np                                     # noqa: E402
import torch                                           # noqa: E402
from PIL import Image                                  # noqa: E402

from utils.utils import get_classes                    # noqa: E402
from utils.utils_bbox import DecodeBox                 # noqa: E402
from utils.det_eval import draw_boxes, resolve_font    # noqa: E402


def letterbox_imagenumpy(image_pil, input_shape):
    """letterbox 到 input_shape (H,W)，返回 (float32 HWC, 原图像信息)。"""
    iw, ih = image_pil.size
    h, w = input_shape
    scale = min(h / ih, w / iw)
    nw, nh = int(iw * scale), int(ih * scale)
    resized = image_pil.resize((nw, nh), Image.BICUBIC)
    canvas = Image.new('RGB', (w, h), (128, 128, 128))
    canvas.paste(resized, ((w - nw) // 2, (h - nh) // 2))
    arr = np.array(canvas, dtype='float32') / 255.0     # HWC float
    return arr, np.array([ih, iw])


def main():
    ap = argparse.ArgumentParser(description="INT8(PTQ) ONNX 端到端推理（QDQ）")
    ap.add_argument("--onnx", default=str(ML_ROOT / 'deploy' / 'yolo_ptq_int8.onnx'),
                    help="QDQ ONNX 模型路径")
    ap.add_argument("--img", default=None,
                    help="测试图片路径；缺省用第一张训练图")
    ap.add_argument("--conf", type=float, default=0.15, help="置信度阈值")
    ap.add_argument("--nms", type=float, default=0.45, help="NMS 阈值")
    ap.add_argument("--out", default=str(PROJECT_ROOT / 'detect' / 'outputs' / 'onnx'),
                    help="可视化输出目录")
    args = ap.parse_args()

    # ---- 1) 加载类别 ----
    labels_txt = ML_ROOT / 'deploy' / 'label_merged.txt'
    class_names, num_classes = get_classes(str(labels_txt))
    print("[ONNX] 类别 %d 个: %s" % (num_classes, class_names))

    # ---- 2) 定位测试图片 ----
    img_path = args.img
    if img_path is None:
        train_txt = ML_ROOT / 'datasets' / 'merged' / '2025_train.txt'
        with open(train_txt, encoding='utf-8') as f:
            for ln in f:
                ln = ln.strip()
                if ln:
                    img_path = ln.split(" ")[0]
                    break
    if not img_path or not Path(img_path).exists():
        print("[ONNX] ! 找不到测试图片: %s" % img_path, file=sys.stderr)
        sys.exit(1)
    print("[ONNX] 测试图片: %s" % img_path)

    # ---- 3) 加载 ONNX（onnxruntime）----
    import onnxruntime as ort                            # noqa: E402
    onnx_path = args.onnx
    if not Path(onnx_path).exists():
        print("[ONNX] ! 找不到 ONNX: %s" % onnx_path, file=sys.stderr)
        sys.exit(1)
    so = ort.SessionOptions()
    sess = ort.InferenceSession(onnx_path, so,
                                providers=['CPUExecutionProvider'])
    inp_name = sess.get_inputs()[0].name
    print("[ONNX] 输入: %s%s 输出: %s"
          % (inp_name, sess.get_inputs()[0].shape,
             [o.name for o in sess.get_outputs()]))

    # ---- 4) 预处理 + 推理 ----
    input_shape = [512, 512]
    image_pil = Image.open(img_path).convert('RGB')
    arr_hwc, image_shape = letterbox_imagenumpy(image_pil, input_shape)
    blob = np.transpose(arr_hwc, (2, 0, 1))[None].astype(np.float32)  # 1x3x512x512
    dbox, cls = sess.run(None, {inp_name: blob})
    print("[ONNX] 推理输出: dbox%s cls%s" % (dbox.shape, cls.shape))

    # ---- 5) 解码 + NMS ----
    decodebox = DecodeBox(num_classes=num_classes, input_shape=input_shape)
    pred = decodebox.decode_onnx_box([dbox, cls])
    results = decodebox.non_max_suppression(
        pred, num_classes, input_shape=input_shape,
        image_shape=image_shape, letterbox_image=True,
        conf_thres=args.conf, nms_thres=args.nms)
    dets = []
    if results[0] is not None:
        top_label = np.array(results[0][:, 5], dtype='int32')
        top_conf = results[0][:, 4]
        top_boxes = results[0][:, :4]
        for i in range(len(top_label)):
            y1, x1, y2, x2 = top_boxes[i]            # yolo_correct_boxes y,x 顺序
            dets.append((float(x1), float(y1), float(x2), float(y2),
                         float(top_conf[i]), int(top_label[i])))

    print("[ONNX] 检出 %d 个目标（conf>=%.2f, nms=%.2f）:"
          % (len(dets), args.conf, args.nms))
    for (x1, y1, x2, y2, score, cid) in dets:
        cname = class_names[cid] if cid < len(class_names) else str(cid)
        print("  %-12s conf=%.2f box=(%d,%d,%d,%d)"
              % (cname, score, int(x1), int(y1), int(x2), int(y2)))

    # ---- 6) 可视化保存 ----
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    save_path = outdir / ('vis_' + Path(img_path).stem + '.jpg')
    font_path = resolve_font(ML_ROOT)
    draw_boxes(image_pil, dets, [], class_names, str(save_path),
               font_path=font_path)
    print("[ONNX] 可视化保存到: %s" % save_path)


if __name__ == "__main__":
    main()