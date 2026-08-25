# -*- coding: utf-8 -*-
"""FP32(效 pytorch) vs INT8(ORT QDQ ONNX) 在 test 集上的 mAP 精度对比。

目的：验证 QAT 收益——INT8 部署(via onnxruntime 真 INT8 内核)相对 FP32 的
精度损失是否可接受（AP 接近即无损）。

口径（与前一轮已确认一致）：
- 同一份 test 分割（datasets/merged/2025_test.txt，68 张）。
- 预处理两后端完全一致：letterbox 到 512²(灰128) + 除以 255。
- 解码/后处理共用 DecodeBox：
    FP32  -> decode_box( YoloBody 5 元组 )   -> non_max_suppression
    INT8  -> decode_onnx_box( [dbox,cls] )   -> non_max_suppression
- 评估用 VOC 格式 get_map（ground-truth/ + detection-results/，IoU=0.5）。

用法（在 ml/ 下运行）：
  E:\\MiniConda\\envs\\Aging\\python.exe train/compare_fp32_int8.py \
      --fp32 weights/MERGED_CMP_FP32/ep200_ckpt.pt \
      --onnx deploy/yolo_ptq_int8.onnx \
      --out detect/outputs/compare
"""
# 强制 UTF-8，避免 Windows GBK 打印中文崩
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

import numpy as np                                     # noqa: E402
import torch                                           # noqa: E402
from PIL import Image                                  # noqa: E402

from model.YOLOV8 import YoloBody                      # noqa: E402
from utils.utils import get_classes, resize_image, preprocess_input  # noqa: E402
from utils.utils_bbox import DecodeBox                 # noqa: E402
from utils.utils_map import get_map                    # noqa: E402


def load_test_txt(path):
    """读 test 分割 txt，返回 [(img_abs, [(x1,y1,x2,y2,cls_id), ...]), ...]"""
    entries = []
    with open(path, encoding='utf-8') as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            parts = ln.split()
            img = parts[0]
            boxes = []
            for tok in parts[1:]:
                xs = tok.split(",")
                boxes.append(tuple(int(x) for x in xs))
            entries.append((img, boxes))
    return entries


def write_ground_truth(entries, class_names, gt_dir):
    Path(gt_dir).mkdir(parents=True, exist_ok=True)
    for img, boxes in entries:
        image_id = Path(img).stem
        lines = []
        for (x1, y1, x2, y2, cid) in boxes:
            if cid < len(class_names):
                lines.append("%s %d %d %d %d" % (class_names[cid], x1, y1, x2, y2))
        with open(os.path.join(gt_dir, image_id + ".txt"), "w", encoding='utf-8') as f:
            f.write("\n".join(lines) + "\n")


def preprocess(image_pil, input_shape):
    """同一预处理：letterbox + /255，返回 [1,3,H,W] float32 与 image_shape"""
    image_shape = np.array(np.shape(image_pil)[0:2])
    image = resize_image(image_pil, (input_shape[1], input_shape[0]), True)
    blob = np.transpose(preprocess_input(np.array(image, dtype='float32')), (2, 0, 1))
    return blob[None], image_shape


def run_backend(entries, class_names, input_shape, conf, nms, predict_fn, dr_dir):
    """对每个测试图跑 predict_fn，写 detection-results/*.txt，返回检测框总数"""
    Path(dr_dir).mkdir(parents=True, exist_ok=True)
    n_det = 0
    for img_path, _ in entries:
        image_id = Path(img_path).stem
        image_pil = Image.open(img_path).convert('RGB')
        blob, image_shape = preprocess(image_pil, input_shape)
        results, _ = predict_fn(blob, image_shape, class_names, input_shape, conf, nms)
        det = results[0] if results is not None and len(results) > 0 else None
        lines = []
        if det is not None and len(det) > 0:
            det = np.asarray(det)
            for row in det:
                # non_max_suppression/yolo_correct_boxes 返回 (y1,x1,y2,x2)，
                # 检测文件需为 VOC (x1,y1,x2,y2) 格式，因此翻转 xy。
                x1, y1, x2, y2 = row[1], row[0], row[3], row[2]
                score = float(row[4])
                cid = int(row[5])
                if cid >= len(class_names):
                    continue
                lines.append("%s %s %d %d %d %d" % (
                    class_names[cid], str(score), int(x1), int(y1), int(x2), int(y2)))
        n_det += len(lines)
        with open(os.path.join(dr_dir, image_id + ".txt"), "w", encoding='utf-8') as f:
            f.write("\n".join(lines) + "\n")
    return n_det


def make_fp32_predictor(ckpt_path, num_classes, phi, input_shape, device):
    model = YoloBody(input_shape, num_classes, phi, pretrained=False)
    ck = torch.load(ckpt_path, map_location='cpu', weights_only=False)
    sd = ck.get('ema') or ck.get('model')
    if sd is None:
        raise RuntimeError("checkpoint 缺少 model/ema: %s" % ckpt_path)
    ret = model.load_state_dict(sd, strict=False)
    if ret.missing_keys or ret.unexpected_keys:
        print("[FP32] load 提示 missing=%d unexpected=%d"
              % (len(ret.missing_keys), len(ret.unexpected_keys)))
    model = model.to(device).float().eval()
    db = DecodeBox(num_classes=num_classes, input_shape=input_shape)

    def predict_fn(blob, image_shape, class_names, input_shape, conf, nms):
        with torch.no_grad():
            images = torch.from_numpy(blob).to(device)
            outputs = model(images)
            y = db.decode_box(outputs)
            results = db.non_max_suppression(
                y, num_classes, input_shape, image_shape, True,
                conf_thres=conf, nms_thres=nms)
            return results, db
    return predict_fn


def make_int8_predictor(onnx_path, num_classes, input_shape):
    import onnxruntime as ort
    so = ort.SessionOptions()
    sess = ort.InferenceSession(onnx_path, so, providers=['CUDAExecutionProvider', 'CPUExecutionProvider'])
    inp_name = sess.get_inputs()[0].name
    db = DecodeBox(num_classes=num_classes, input_shape=input_shape)

    def predict_fn(blob, image_shape, class_names, input_shape, conf, nms):
        dbox, cls = sess.run(None, {inp_name: blob})
        y = db.decode_onnx_box([dbox, cls])
        results = db.non_max_suppression(
            y, num_classes, input_shape, image_shape, True,
            conf_thres=conf, nms_thres=nms)
        return results, db
    return predict_fn


def main():
    ap = argparse.ArgumentParser(description="FP32 vs INT8 (ORT) mAP 对比")
    ap.add_argument("--test", default=str(ML_ROOT / 'datasets' / 'merged' / '2025_test.txt'))
    ap.add_argument("--classes", default=str(ML_ROOT / 'datasets' / 'merged' / 'label_merged.txt'))
    ap.add_argument("--fp32", default=None, help="FP32 pytorch checkpoint (ep*_ckpt.pt)")
    ap.add_argument("--onnx", default=None, help="QDQ ONNX 路径 (INT8)")
    ap.add_argument("--phi", default="n")
    ap.add_argument("--input-shape", default="512,512")
    ap.add_argument("--conf", type=float, default=0.05, help="生成检测框的置信度阈值")
    ap.add_argument("--nms", type=float, default=0.45, help="NMS IoU 阈值")
    ap.add_argument("--out", default=str(ML_ROOT.parent / 'detect' / 'outputs' / 'compare'))
    args = ap.parse_args()

    class_names, num_classes = get_classes(args.classes)
    input_shape = [int(x) for x in args.input_shape.split(",")]
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print("[对比] 类别 %d，test=%s，device=%s，conf=%s nms=%s" % (
        num_classes, args.test, device, args.conf, args.nms))

    entries = load_test_txt(args.test)
    print("[对比] test 张数: %d" % len(entries))

    out = Path(args.out)
    results_summary = []

    for tag, make in [("fp32", make_fp32_predictor), ("int8", make_int8_predictor)]:
        src = args.fp32 if tag == "fp32" else args.onnx
        if not src or not Path(src).exists():
            print("[对比] 跳过 %s：缺少 %s" % (tag, src))
            continue
        base = out / tag
        gt_dir = base / "ground-truth"
        dr_dir = base / "detection-results"
        write_ground_truth(entries, class_names, gt_dir)
        if tag == "fp32":
            predict_fn = make(Path(src), num_classes, args.phi, input_shape, device)
        else:
            predict_fn = make_int8_predictor(Path(src), num_classes, input_shape)
        n_det = run_backend(entries, class_names, input_shape, args.conf, args.nms,
                            predict_fn, dr_dir)
        mAP = get_map(0.5, False, path=str(base))
        print("[对比] %-5s mAP=%.2f%%  检测框=%d" % (tag, mAP * 100, n_det))
        results_summary.append((tag, mAP, n_det))

    print("\n============ 汇总 ============")
    d = {t: m for t, m, _ in results_summary}
    if "fp32" in d and "int8" in d:
        loss = d["fp32"] - d["int8"]
        print("FP32 mAP=%.2f%%  INT8 mAP=%.2f%%  绝对差=%.2fpp" % (d["fp32"] * 100, d["int8"] * 100, loss * 100))
        print("结论: INT8 相对 FP32 %s" % ("无损/可接受 (loss<1pp)" if loss <= 0.01 else "退化 %.2fpp" % (loss * 100)))
    else:
        print("至少缺一个后端，无法对比。")


if __name__ == "__main__":
    main()