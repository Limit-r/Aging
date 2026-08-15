# ml — 模型管理（LED 检测 + 训练脚本）

LED 面板亮灭检测流水线：**YOLOv8 5 类位置检测 + TinyConv 亮灭二分类**。

## 目录结构

```
ml/
├── config.py            # 集中配置（数据集定义 + 训练参数）
├── train.py             # 通用训练入口
├── model/               # YOLOv8 模型族（含 SE/CBAM/SC 注意力变体）
├── utils/               # 数据加载 / 训练循环 / 评估 / bbox 工具
├── train/               # 训练脚本与配置（FP/A 数据集）
├── classifier/          # TinyConv 亮灭二分类器
├── ablation/            # 消融实验（脚本 + 配置，结果已归档）
├── annotation_io.py     # 标注数据读写（被 app/data_page 懒加载引用）
├── annotation_widget.py # 标注画布（被 app/data_page 懒加载引用）
├── datasets/
│   ├── FP/              # FP 系列数据集（原始标注 XML + 镜像 + txt 划分）
│   └── A/               # A 系列数据集
├── weights/             # 模型权重（仅保留被代码引用的当前版本）
└── ANNOTATION_SCHEME.md # 标注规范（7 类→5 类映射、流程）
```

## 运行约定（重要）

**训练脚本须以 `ml/` 为工作目录运行**（`config.py` 用相对路径 `datasets\FP\...`、`weights/...`）。
检测/推理脚本位于仓库根 `detect/`，内部自动定位 `ml/`，从仓库根运行即可。

```powershell
cd ml
python train\train_fp.py          # 训练 YOLO
python classifier\train.py        # 训练 TinyConv
cd ..
python detect\infer_fp.py --split val --conf 0.25
python detect\detect_fp_video.py --video video\FP00.mp4 --conf 0.20
```

> 视频抽帧已整合至根目录 `tools/extract_frames.py`（统一支持 A / FP 系列），
> 源视频统一存放于项目根 `video/`（`*.mp4` 已被 git 忽略）。

## 权重说明

`weights/` 仅保留被代码引用的当前模型：

- `weights/FP_v3_5classes_v4/` — 当前 5 类 YOLO 权重
- `weights/FP/` — 早期 5 类权重
- `weights/pretrained/` — COCO 预训练权重 + simhei.ttf
- `train/weights/A/` — A 数据集 YOLO 权重

历史权重（FP_v2 / FP_v3_5classes / _v2 / _v3）、消融结果、生成输出已归档至仓库根 `../archive/`（本地保留，不入 Git）。

## 标注类名

7 类原始标注 → 5 类 YOLO 映射，详见 [ANNOTATION_SCHEME.md](ANNOTATION_SCHEME.md)。

## 迁移历史

本目录由 `led_pipeline/` 迁移而来，交接文档见 [HANDOVER.md](HANDOVER.md)。