# -*- coding: utf-8 -*-
"""
评估合并模型：加载 model_best_precision_deploy.pt，在测试集上计算 per-class 的 AP、Precision、Recall、F1。
"""
import os
import sys
import shutil
import json
import numpy as np
from PIL import Image
from tqdm import tqdm

import torch

# 添加 YOLO_train 到 sys.path 以便导入其模块
YOLO_TRAIN = r'D:\YOLO_train'
if YOLO_TRAIN not in sys.path:
    sys.path.insert(0, YOLO_TRAIN)

from model.YOLOV8 import YoloBody
from utils.utils_bbox import DecodeBox
from utils.utils import cvtColor, preprocess_input, resize_image
from utils.utils_map import get_map

# ========== 配置 ==========
MODEL_PATH = r'D:\Aging\led_pipeline\merge_test\weights\model_best_precision_deploy.pt'
LABEL_PATH = r'D:\Aging\led_pipeline\merge_test\label_merge.txt'
TEST_ANNO  = r'D:\Aging\led_pipeline\merge_test\2025_test_merge.txt'
OUT_DIR    = r'D:\Aging\led_pipeline\merge_test\eval_map_out'
CUDA       = torch.cuda.is_available()
DEVICE     = torch.device('cuda' if CUDA else 'cpu')

# 评估参数（与 get_map.py 一致）
CONFIDENCE    = 0.001      # 推理置信度阈值，尽量低以获取全部预测框
NMS_IOU       = 0.5        # NMS 的 IoU 阈值
MINOVERLAP    = 0.5        # 计算 mAP 时的 IoU 阈值
SCORE_THRESH  = 0.5        # 计算 Precision/Recall/F1 时的门限值
LETTERBOX     = True
MAX_BOXES     = 100

# ========== 读取类别 ==========
with open(LABEL_PATH, 'r', encoding='utf-8') as f:
    class_names = [line.strip() for line in f.readlines()]
num_classes = len(class_names)
print(f'类别 ({num_classes} 个): {class_names}')

# ========== 读取测试标注 ==========
with open(TEST_ANNO, 'r', encoding='utf-8') as f:
    test_lines = [line.strip() for line in f.readlines() if line.strip()]
print(f'测试样本数: {len(test_lines)}')

# ========== 加载模型 ==========
print(f'\n加载模型: {MODEL_PATH}')
checkpoint = torch.load(MODEL_PATH, map_location='cpu', weights_only=False)

# 从 checkpoint 中读取模型参数
input_shape = checkpoint.get('input_shape', [512, 512])
phi = checkpoint.get('phi', 'n')
nc = checkpoint.get('num_classes', num_classes)
print(f'  input_shape: {input_shape}, phi: {phi}, num_classes: {nc}')

model = YoloBody(input_shape, nc, phi, pretrained=False)
model_dict = checkpoint['model']

# 清理 state_dict 中的 module. 前缀（如果有）
cleaned_dict = {}
for k, v in model_dict.items():
    key = k.replace('module.', '') if k.startswith('module.') else k
    cleaned_dict[key] = v

model.load_state_dict(cleaned_dict, strict=False)
model = model.to(DEVICE)
model.eval()
print('模型加载完成')

# 融合 BN 加速推理
model.fuse()
print('模型 BN 融合完成')

# 初始化解码器
decoder = DecodeBox(nc, input_shape)

# ========== 准备输出目录 ==========
if os.path.exists(OUT_DIR):
    shutil.rmtree(OUT_DIR)
gt_dir = os.path.join(OUT_DIR, 'ground-truth')
dr_dir = os.path.join(OUT_DIR, 'detection-results')
os.makedirs(gt_dir, exist_ok=True)
os.makedirs(dr_dir, exist_ok=True)

# ========== 逐个处理测试图像 ==========
print('\n开始推理...')
for line in tqdm(test_lines, desc='Evaluating'):
    parts = line.split()
    img_path = parts[0]
    image_id = os.path.splitext(os.path.basename(img_path))[0]

    # --- 读取图像 ---
    image = Image.open(img_path)
    image = cvtColor(image)
    image_shape = np.array(np.shape(image)[0:2])

    # --- 预处理 ---
    resized = resize_image(image, [input_shape[1], input_shape[0]], LETTERBOX)
    img_data = np.expand_dims(
        np.transpose(preprocess_input(np.array(resized, dtype='float32')), (2, 0, 1)), 0
    )

    # --- 推理 ---
    with torch.no_grad():
        images_t = torch.from_numpy(img_data).to(DEVICE)
        outputs = model(images_t)
        decoded = decoder.decode_box(outputs)
        results = decoder.non_max_suppression(
            decoded, nc, input_shape, image_shape, LETTERBOX,
            conf_thres=CONFIDENCE, nms_thres=NMS_IOU
        )

    # --- 写入检测结果 ---
    dr_path = os.path.join(dr_dir, f'{image_id}.txt')
    with open(dr_path, 'w', encoding='utf-8') as f:
        if results[0] is not None:
            top_label = np.array(results[0][:, 5], dtype='int32')
            top_conf = results[0][:, 4]
            top_boxes = results[0][:, :4]

            # 取 Top-K
            top_100 = np.argsort(top_conf)[::-1][:MAX_BOXES]
            for i in top_100:
                c = top_label[i]
                predicted_class = class_names[int(c)]
                box = top_boxes[i]
                score = top_conf[i]
                # NMS 输出坐标为 [top, left, bottom, right] = [y1, x1, y2, x2]
                # get_map 期望 [left, top, right, bottom] = [x1, y1, x2, y2]
                top, left, bottom, right = box
                f.write(f'{predicted_class} {score:.6f} {int(left)} {int(top)} {int(right)} {int(bottom)}\n')

    # --- 写入 Ground Truth ---
    gt_path = os.path.join(gt_dir, f'{image_id}.txt')
    with open(gt_path, 'w', encoding='utf-8') as f:
        for box_str in parts[1:]:
            coords = list(map(int, box_str.split(',')))
            left, top, right, bottom, cls_id = coords
            cls_name = class_names[cls_id]
            f.write(f'{cls_name} {left} {top} {right} {bottom}\n')

print('推理完成，开始计算 mAP 及 per-class 指标...')

# ========== 调用 get_map 计算指标 ==========
mAP = get_map(
    MINOVERLAP=MINOVERLAP,
    draw_plot=False,
    score_threhold=SCORE_THRESH,
    path=OUT_DIR
)

# ========== 读取 results.txt 获取完整指标 ==========
results_file = os.path.join(OUT_DIR, 'results', 'results.txt')
if os.path.exists(results_file):
    print('\n' + '='*70)
    print('完整评估结果')
    print('='*70)
    with open(results_file, 'r', encoding='utf-8') as f:
        content = f.read()
    print(content)

# ========== 打印汇总 ==========
print('\n' + '='*70)
print('PER-CLASS METRICS 摘要 (score_threshold=0.5, IoU=0.5)')
print('='*70)
print(f'{"Class":<20} {"AP":>8} {"Precision":>10} {"Recall":>8} {"F1":>8}')
print('-'*70)

# 从 results.txt 解析 per-class 指标
if os.path.exists(results_file):
    with open(results_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if '=' in line and 'AP' in line:
                parts = line.split('=')
                ap_val = parts[0].strip()
                class_name = parts[1].strip().rsplit(' AP', 1)[0].strip()
                # 查找对应的 Precision/Recall/F1 行
                # 格式: "XX.XX% = class_name AP"
                ap_str = ap_val
                print(f'{class_name:<20} {ap_str:>8}', end='')
            elif 'Precision' in line and '=' in line:
                # 格式: "XX.XX% = class_name Precision"
                pass
            elif 'Recall' in line and '=' in line:
                pass
            elif 'F1' in line and '=' in line:
                pass

# 同时从控制台输出中捕获（get_map 会在控制台打印 per-class 指标）
print('\n' + '='*70)
print('上述 mAP 计算过程中已打印每个类别的 AP / F1 / Recall / Precision')
print('='*70)

# 清理临时文件
# shutil.rmtree(OUT_DIR)  # 保留以便查看
print(f'\n中间结果保存在: {OUT_DIR}')
print('评估完成!')