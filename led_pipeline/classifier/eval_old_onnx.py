"""
评估旧的 ONNX 模型在测试集上的准确率。
旧 ONNX 模型来自 2026-08-06 19:37 的训练 (99.5% 准确率)。
"""
import sys
from pathlib import Path
import numpy as np
import cv2
import onnxruntime as ort

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from classifier.train import LEDDataset, DATA_DIR, INPUT_SIZE

# 加载旧 ONNX 模型
onnx_path = PROJECT_ROOT / 'classifier' / 'weights' / 'best_tinyconv.onnx'
print(f'ONNX 模型: {onnx_path}')
print(f'文件大小: {onnx_path.stat().st_size} 字节')
print(f'修改时间: {onnx_path.stat().st_mtime}')

session = ort.InferenceSession(str(onnx_path))
input_name = session.get_inputs()[0].name
output_name = session.get_outputs()[0].name

# 评估测试集
test_dataset = LEDDataset(DATA_DIR, 'test', augment=False)

correct = 0
total = 0
cm = [[0, 0], [0, 0]]

for i in range(len(test_dataset)):
    img_tensor, label = test_dataset[i]
    # img_tensor: 3x32x32, 需要转成 HWC 再转 BGR 给 ONNX
    img_np = img_tensor.numpy()
    img_np = np.transpose(img_np, (1, 2, 0))  # CHW -> HWC
    img_np = (img_np * 255).astype(np.uint8)
    img_np = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
    
    # ONNX 期望: NCHW, float32, [0,1]
    input_tensor = img_np.astype(np.float32) / 255.0
    input_tensor = np.transpose(input_tensor, (2, 0, 1))[None, :, :, :]
    
    outputs = session.run([output_name], {input_name: input_tensor})
    pred = np.argmax(outputs[0][0])
    
    cm[label][pred] += 1
    correct += (pred == label)
    total += 1

acc = correct / total
print(f'\n旧 ONNX 模型在测试集上的准确率: {acc*100:.2f}% ({correct}/{total})')
print(f'混淆矩阵:')
print(f'             预测 L    预测 H')
print(f'  真实 L:    {cm[0][0]:6d}    {cm[0][1]:6d}')
print(f'  真实 H:    {cm[1][0]:6d}    {cm[1][1]:6d}')

# 新模型准确率对比
print(f'\n新旧模型对比:')
print(f'  旧模型 (ONNX, 2026-08-06): {acc*100:.2f}%')
print(f'  新模型 (PyTorch, 2026-08-07): 96.07%')