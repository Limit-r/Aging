# Aging — LED 老化检测系统

基于 **PyQt5 3D 控制台 + YOLOv8/TinyConv 检测流水线**的 LED 面板老化检测系统。

## 项目组成

本仓库包含两个相对独立的子项目：

| 目录 | 说明 |
|---|---|
| [app/](app/) | PyQt5 桌面控制台：72 通道 3D 机柜全屏 + 电流检测 + 视频检测 + 数据中心 + 系统设置 |
| [ml/](ml/) | 模型管理：YOLOv8 5 类检测 + TinyConv 亮灭二分类 + 标注工具 + 训练/推理脚本 |
| [detect/](detect/) | 检测模块：视频/图片/ESP32-CAM 流推理入口 |
| [datasets/](datasets/) | 根级 A 系列数据集（原始标注 + 图片） |
| [firmware/](firmware/) | ESP32 固件（ADC/OLED/视频流采集） |
| [archive/](archive/) | 历史权重/消融结果/生成输出（**本地归档，不纳入 Git**） |

## 整体架构

```
                          ┌─────────────────────────────┐
    ESP32-CAM 视频流 ─────▶│   ml (YOLO+分类器)          │
                          └─────────────┬───────────────┘
                                        ▼
                          ┌─────────────────────────────┐
    72 通道电流 / 温度 ───▶│   app/ (PyQt5 3D 控制台)     │
                          └─────────────────────────────┘
```

- **app/**：PyQt5 5.15 + pyqtgraph 0.14，分层架构（core←data←services←observability←styles←widgets←ui），详见 [ARCHITECTURE.md](ARCHITECTURE.md)。
- **ml/**：两阶段检测 —— YOLOv8 检测 5 类位置（SIG_area/PWR_area/VPL/CPL/PWR），TinyConv 对 LED ROI 做亮灭（H/L）二分类。标注规范见 [ml/ANNOTATION_SCHEME.md](ml/ANNOTATION_SCHEME.md)。

## 环境要求

- Python 3.10（Conda 环境 `Aging`）
- PyTorch 2.7+ / CUDA 12.8（RTX 5060 Ti Blackwell）
- opencv-python 4.10.0.84（勿升级 4.11+，避免 ffmpeg DLL 冲突）
- 完整依赖见 [environment.yml](environment.yml)

```powershell
conda env create -f environment.yml
conda activate Aging
```

## 启动

```powershell
# PyQt5 控制台（须从仓库根目录运行）
python Main.py
```

## 训练与检测脚本使用

> **重要约定**：`ml/` 下的训练脚本须**以 `ml/` 为工作目录**运行（`config.py` 使用相对路径）；`detect/` 下的检测脚本从仓库根运行即可（内部自动定位 `ml/`）。

```powershell
# ---- 统一 9 类训练/检测链路 ----
# 1. 合并 ROI 样本（FP 源在 archive/classifier_data，A 源在 ml/classifier/data_a）
cd ml
python classifier\prepare_data_merged.py

# 2. 训练统一 YOLO（9 类）
python train\train_merged.py

# 3. 训练统一 TinyConv 亮灭二分类
python classifier\train_merged.py

# 4. 视频 / LED 检测：启动老化检测 GUI（视频流：逐帧 + 闪烁统计）从仓库根
cd ..
python Main.py

# 5. 实时 ESP32-CAM MJPEG 流检测
python detect\pc_yolo_detect.py --url http://<esp32cam-ip>/stream
```

## 目录规范

- `ml/` 代码为**扁平命名空间**（`from model import YOLOV8` 等），数据集与权重统一位于 `ml/datasets/`、`ml/weights/`。
- 历史权重、消融结果、生成输出统一归档至 `archive/`（本地保留，不入库）。
- 详细目录与依赖方向见 [ARCHITECTURE.md](ARCHITECTURE.md)。

## License

MIT — 见 [LICENSE](LICENSE)。