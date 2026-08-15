# LED Pipeline 数据集标注规范

## 概述

本项目采用**两阶段检测架构**：
- **YOLO**：检测 5 类位置（FP_SIG_area / FP_PWR_area / FP_VPL / FP_CPL / FP_PWR）
- **TinyConv**：对 FP_VPL/FP_CPL/FP_PWR 的 ROI 做亮灭二分类（H/L）

因此数据集标注需要同时服务于两个模型。本规范定义了标注方式和转换流程，确保 H/L 信息在原始标注中保留，不会丢失。

---

## 1. 标注类别定义

### 1.1 系列前缀约定

每个面板系列使用独立的前缀，方便后续分类和管理：

| 系列 | 前缀 | 示例类别名 |
|------|------|-----------|
| FP 系列 | `FP_` | `FP_VPL_H`, `FP_SIG_area` |
| 后续系列 | 待定 | 如 `X_VPL_H`, `X_SIG_area` |

**原则**：同一系列内所有类别名共享统一前缀，不同系列的数据集完全隔离（独立的目录和标注文件）。

### 1.2 完整 7 类标注（labelImg 中使用）

| 类别名 | 说明 | 用于 |
|--------|------|------|
| `FP_SIG_area` | 信号区域框（大框，包含 VPL/CPL） | YOLO |
| `FP_PWR_area` | 电源区域框（大框，包含 PWR LED） | YOLO |
| `FP_VPL_H` | VPL LED 亮 | YOLO + 分类器 |
| `FP_VPL_L` | VPL LED 灭 | YOLO + 分类器 |
| `FP_CPL_H` | CPL LED 亮 | YOLO + 分类器 |
| `FP_CPL_L` | CPL LED 灭 | YOLO + 分类器 |
| `FP_PWR_H` | PWR LED 亮 | YOLO + 分类器 |
| `FP_PWR_L` | PWR LED 灭 | YOLO + 分类器 |

**标注原则**：
- 所有 LED 必须标注 H/L 属性，不能只标 `FP_VPL` 不带亮灭
- 区域框（FP_SIG_area / FP_PWR_area）仅标注位置，不参与亮灭分类
- 使用 labelImg 标注，保存为 VOC XML 格式

### 1.3 YOLO 5 类映射（训练时使用）

| 7 类原始标注 | 5 类映射 |
|-------------|---------|
| `FP_VPL_H` / `FP_VPL_L` | `FP_VPL` |
| `FP_CPL_H` / `FP_CPL_L` | `FP_CPL` |
| `FP_PWR_H` / `FP_PWR_L` | `FP_PWR` |
| `FP_SIG_area` | `FP_SIG_area` |
| `FP_PWR_area` | `FP_PWR_area` |

---

## 2. 目录结构

```
led_pipeline/datasets/FP/
├── Annotations/              # 原始 7 类标注（labelImg 输出目录）
│   ├── fp02_000000.xml
│   ├── fp02_000005.xml
│   └── ...
├── Annotations_5class/       # 5 类标注副本（由 gen_5class_xmls.py 生成）
│   ├── fp02_000000.xml
│   ├── fp02_000005.xml
│   └── ...
├── JPEGImages/               # 原始图片
│   ├── fp02_000000.jpg
│   ├── fp02_000005.jpg
│   └── ...
├── classifier_data/          # 二分类数据集备份（由 prepare_data.py 生成）
│   ├── train/L/
│   ├── train/H/
│   ├── val/L/
│   ├── val/H/
│   ├── test/L/
│   └── test/H/
├── 2025_train.txt
├── 2025_val.txt
└── 2025_test.txt
```

---

## 3. 标注流程

### 3.1 新增数据标注

```
第 1 步：用 labelImg 打开图片，按 7 类标注 → 保存到 Annotations/
第 2 步：运行 gen_5class_xmls.py → 生成 Annotations_5class/ 的 5 类副本
第 3 步：确认 2025_train.txt / 2025_val.txt / 2025_test.txt 包含新图片
第 4 步：运行 prepare_data.py → 更新 classifier/data/ 的 L/H ROI 数据集
```

### 3.2 工具脚本

| 脚本 | 作用 | 运行时机 |
|------|------|---------|
| `led_pipeline/train/gen_5class_xmls.py` | 从 `Annotations/` 生成 5 类副本到 `Annotations_5class/` | 每次新增/修改标注后 |
| `led_pipeline/classifier/prepare_data.py` | 从 `Annotations/` 的 7 类标注裁剪 L/H ROI 到 `classifier/data/` | 新增标注或需要重新生成分类器数据集时 |
| `led_pipeline/train/gen_fp_txt.py` | 生成 train/val/test 文件列表 | 新增图片后 |

---

## 4. YOLO 训练配置

训练 YOLO 时，将标注目录指向 `Annotations_5class/`：

```python
# 数据集路径配置
ANNOT_DIR = 'datasets/FP/Annotations_5class'
# 类别文件 label.txt 保持 5 类:
#   FP_SIG_area
#   FP_PWR_area
#   FP_VPL
#   FP_CPL
#   FP_PWR
```

---

## 5. 分类器训练

### 5.1 数据集生成

`prepare_data.py` 直接从 `Annotations/` 的 7 类标注名提取 H/L 标签：

```python
L_CLASSES = {'FP_VPL_L', 'FP_CPL_L', 'FP_PWR_L'}
H_CLASSES = {'FP_VPL_H', 'FP_PWR_H'}
```

### 5.2 训练

```bash
python led_pipeline/classifier/train.py
```

### 5.3 数据集备份

`classifier/data/` 中的 L/H ROI 图片已备份到 `datasets/classifier_data/`，如需重置可从此处恢复。

---

## 6. 已有数据说明

当前 `Annotations/` 中的 XML 文件为 5 类标注（已运行过 `update_xml_to_5classes.py`，H/L 信息已丢失）。

对于这批旧数据：
- 二分类数据集已从 `D:\YOLO_train` 迁移并验证正确（train: L=1085 / H=187）
- 分类器权重 `best_tinyconv.pth` 已使用正确数据训练
- 新增图片时请按 7 类标注，不要再使用 `update_xml_to_5classes.py`

---

## 7. 注意事项

1. **永远不要原地修改 `Annotations/` 的标注**，如需 5 类版本请使用 `gen_5class_xmls.py` 生成副本
2. **`update_xml_to_5classes.py` 已废弃**，它会破坏 H/L 信息且不可逆
3. 新增类别（如 `FP_CPL_H`）时，同步更新 `prepare_data.py` 中的 `H_CLASSES`
4. 二分类数据集的数量不平衡（L 远多于 H）是正常现象，训练时 `train.py` 会自动计算类别权重