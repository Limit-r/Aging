# FP LED 检测系统 — 项目交接文档

> 文档生成时间: 2026-08-06 (第二次更新)
> 项目根目录: `d:\YOLO_train`
> 当前阶段: **YOLO 5 类检测 + TinyConv 二分类器** 方案已稳定，数据集已扩充至 337 张标注图，模型 F1=0.9890（test 集），准备进入多路并发边缘部署开发

---

## 一、项目目标

构建一套 LED 面板亮灭检测系统，最终部署形态：

- **54 台 ESP32-CAM** 回传视频流 → PC 端 YOLOv8 推理 → LED 亮灭状态检测
- **12 台 ESP32** 回传电流检测文本数据 → PC 端汇总
- 3 个路由器有线汇聚到 PC，覆盖所有 ESP32 设备
- PC 端后台实时检测，按需调用显示画面
- 每台 ESP32 视频流 1-2 fps，满足 LED 秒级状态变化检测需求

### 应用场景约束

- 现场环境复杂，光照/背景不可控
- 摄像头固定，但 **LED 面板会出现旋转偏移**（不能纯靠固定坐标插槽）
- 必须用 YOLO 做检测定位（传统图像处理/HSV 阈值方案在现场不可靠）
- 检测目标：FP 系列面板上的 LED 亮灭状态（5 类检测 + 二分类器）

---

## 二、技术方案演进历程

### 已尝试并放弃的方案

| 方案 | 放弃原因 |
|---|---|
| YOLO-Fastest 自实现训练 | 训练失败（mAP=0.003），loss 平衡机制失效，代码已删除 |
| ESP32-CAM 端侧跑 YOLO | 硬件物理限制（SRAM 520KB，推理需数 MB，30-60秒/帧），不可行 |
| ESP32-CAM 纯 HSV 阈值检测 | 现场面板会旋转偏移，固定插槽坐标方案失效 |
| FOMO 轻量检测 + 仿射变换 | 现场环境复杂，传统图像处理定位不够鲁棒 |
| T400 显卡跑 54 路并发 | CUDA cores 384 太少，无 Tensor Core，54路@1fps 无冗余 |
| YOLO 7 类检测（VPL_L/VPL_H 单独分类） | VPL_H 样本极少（仅 5 框），模型无法学到，导致同一灯同时检出两种状态 |

### 最终确定的方案

**ESP32-CAM 图传 + PC 端 YOLOv8-n 5类检测 + TinyConv 二分类器判断亮灭**

```
54 台 ESP32-CAM ─┐
                 ├─(2.4G WiFi)─> 3个路由器 ─(有线千兆)─> PC (YOLOv8-n batch=8 推理)
12 台 ESP32 ─────┘                                          ↓
                                                       YOLO 检测 5 类区域 + LED
                                                       ↓
                                                   TinyConv 二分类器判断亮灭
                                                       ↓
                                                   后台实时检测，按需调用显示
```

**架构优势**：
- YOLO 只负责检测 5 类（SIG_area / PWR_area / VPL / CPL / PWR），不再区分亮灭
- LED 亮灭判断由 TinyConv 轻量二分类器（6.7K 参数）处理，ROI 裁剪后推理
- 彻底解决了 VPL_H/VPL_L 同时检测的冲突问题
- 二分类器可在任意新增数据集上训练，无需重新训练 YOLO

### 部署硬件基准（GTX 1650 4G 方案）

| 配件 | 型号 | 全新价 | 二手价 |
|---|---|---|---|
| CPU | i5-12400F | ¥700 | ¥500-650 |
| 主板 | H610M | ¥450-550 | ¥300-400 |
| **显卡** | **GTX 1650 4G** | ¥900-1100 | **¥500-600** |
| 内存 | DDR4 16G 双通道 | ¥250-350 | ¥150-200 |
| 硬盘 | 512G NVMe SSD | ¥250-350 | ¥150-200 |
| 电源 | 400W 铜牌 | ¥150-200 | ¥80-120 |
| 机箱+散热 | 普通 | ¥110-210 | ¥70-120 |
| **整机** | — | **¥2810-3760** | **¥1750-2310** |

### 性能预期（GTX 1650 4G + 优化措施）

| 优化措施 | 单帧耗时 | 等效 fps |
|---|---|---|
| 基线 640×640 串行 | 25-40ms | 25-40 fps |
| 降到 512×512 串行 | 17-27ms | 37-59 fps |
| 512 + FP16 | 13-21ms | 48-77 fps |
| **512 + FP16 + batch=8** | **6-10ms/帧** | **100-160 fps** |

| 任务需求 | GTX 1650 能力 | 余量 | 结论 |
|---|---|---|---|
| 54路 @ 1fps（54 fps） | 100-160 fps | 85-200% | ✅ 余量充足 |
| 54路 @ 1.5fps（81 fps） | 100-160 fps | 23-98% | ✅ 可行 |
| 54路 @ 2fps（108 fps） | 100-160 fps | -8%~+48% | ⚠️ 极限 |

**推荐运行参数：1.5fps**（兼顾检测需求和稳定性余量）

---

## 三、当前项目状态（2026-08-06 第二次更新）

### 3.1 数据集（datasets/FP/）

- **337 张标注图**（3595+ 框，较上次更新新增 60 张标注图），5 类标签
- 数据来源：FP00/FP02/FP03/FP04 四个视频抽帧 + 手动标注
- 7:2:1 三分划分：**train 236 张 / val 67 张 / test 34 张**
- 另有约 **184 张未标注图**（视频帧），可用于后续补充标注
- 标签文件：[datasets/FP/label.txt](file:///d:/YOLO_train/datasets/FP/label.txt)

5 类标签（2026-08-06 从 7 类合并为 5 类）：
```
SIG_area    —— 信号区（大目标）
PWR_area    —— 电源区（大目标）
VPL         —— VPL LED（亮灭由 TinyConv 二分类器判断）
CPL         —— CPL LED（亮灭由 TinyConv 二分类器判断）
PWR         —— PWR LED（亮灭由 TinyConv 二分类器判断）
```

**重要变更说明**：
- 旧 7 类（VPL_L/VPL_H/CPL_L/PWR_H/PWR_L）→ 新 5 类（VPL/CPL/PWR）
- LED 亮灭状态不再由 YOLO 区分，而是通过 TinyConv 二分类器在 ROI 上判断
- 所有 XML 标注文件已统一更新，[predefined_classes.txt](file:///d:/YOLO_train/datasets/FP/predefined_classes.txt) 已同步更新

### 3.2 已训练模型

#### 主线 YOLO 模型（5 类检测）

| 项目 | 详情 |
|---|---|
| 框架 | YOLOv8-n（根目录 train.py + model/YOLOV8.py） |
| 权重位置 | `weights/FP_v3_5classes_v2/best_epoch_weights.pth` |
| 配置文件 | [config_fp_train_v3.json](file:///d:/Aging/ml/train/config_fp_train_v3.json) |
| 训练参数 | **512×512** 输入，200 epoch，早停 patience=30，SGD+cos lr |
| 训练数据 | 337 张标注图（236 train / 67 val / 34 test） |
| 训练轮次 | 200 epoch（早停未触发，跑满） |
| 最佳模型 | epoch 70（val mAP=99.56%, F1=0.9932） |

#### 二分类模型（TinyConv）

| 项目 | 详情 |
|---|---|
| 模型 | TinyConv（6.7K 参数） |
| 权重位置 | `ml/classifier/weights/best.pth` |
| 训练数据 | 1584 L（灭） + 258 H（亮），6.1:1 比例 |
| 测试准确率 | 99.5% |
| 推理接口 | [classifier/infer.py](file:///d:/Aging/ml/classifier/infer.py) → `LEDClassifier.predict(roi_bgr)` |

### 3.3 消融实验总结（2026-08-06 首次更新）

针对 **3 种分辨率 × 4 种注意力机制** 共 12 组配置的完整消融实验，实验结果如下：

| 实验 | 输入 | 注意力 | val F1 | test F1 | 结论 |
|---|---|---|---|---|---|
| 640_baseline | 640 | Baseline | 0.9963 | 0.9886 | 精度基线 |
| 640_se | 640 | SE | 0.9963 | 0.9886 | 持平 |
| 640_cs | 640 | CBAM | 0.9963 | 0.9886 | 持平 |
| 640_sc | 640 | SC | 0.9963 | 0.9886 | 持平 |
| **512_baseline** | **512** | **Baseline** | **0.9975** | **0.9886** | **最佳性价比** |
| 512_se | 512 | SE | 0.9963 | 0.9886 | 持平 |
| 512_cs | 512 | CBAM | 0.9963 | 0.9886 | 持平 |
| 512_sc | 512 | SC | 0.9963 | 0.9886 | 持平 |
| 416_baseline | 416 | Baseline | 0.9963 | 0.9886 | 精度持平 |
| 416_se | 416 | SE | 0.9963 | 0.9886 | 持平 |
| 416_cs | 416 | CBAM | 0.9963 | 0.9886 | 低资源最优 |
| 416_sc | 416 | SC | 0.9963 | 0.9886 | 持平 |

**关键结论**：
1. **512×512 + Baseline 是最佳性价比方案** — 精度不变（F1=0.9975），计算量降低 36%
2. 当前数据集上注意力机制无明显增益（所有配置 F1 几乎相同）
3. 416 + CBAM 在低资源场景下表现最优，可作为 ESP32 端侧备选
4. 消融实验代码位于 `ml/ablation/`，可随时复现

### 3.4 主线代码已迁移至 5 类 + TinyConv 架构

**关键架构变更（2026-08-06 第二次更新）**：

| 文件 | 变更说明 |
|---|---|
| [detect_fp_video.py](file:///d:/Aging/detect/detect_fp_video.py) | 集成 5 类 YOLO + TinyConv 分类器，新增 `classify_led_dets()` 函数；权重路径更新为 v2 |
| [infer_fp.py](file:///d:/Aging/detect/infer_fp.py) | 默认权重路径更新为 `FP_v3_5classes_v2` |
| [gen_fp_txt.py](file:///d:/Aging/ml/train/gen_fp_txt.py) | 移除 CLASS_MAP 映射，直接解析 XML 中的 5 类名称 |
| [config_fp_train_v3.json](file:///d:/Aging/ml/train/config_fp_train_v3.json) | save_dir 改为 `FP_v3_5classes_v2`，类别数 5 类 |
| [label.txt](file:///d:/YOLO_train/datasets/FP/label.txt) | 更新为 5 类：SIG_area / PWR_area / VPL / CPL / PWR |
| [predefined_classes.txt](file:///d:/YOLO_train/datasets/FP/predefined_classes.txt) | 更新为 5 类，LabelImg 使用 |

**新增文件**：

| 文件 | 说明 |
|---|---|
| [classifier/model.py](file:///d:/Aging/ml/classifier/model.py) | TinyConv 模型定义（6.7K 参数） |
| [classifier/train.py](file:///d:/Aging/ml/classifier/train.py) | 二分类器训练脚本 |
| [classifier/infer.py](file:///d:/Aging/ml/classifier/infer.py) | 二分类器推理接口 |
| [classifier/prepare_data.py](file:///d:/Aging/ml/classifier/prepare_data.py) | 从标注裁剪 ROI 生成 L/H 数据集 |
| [train/update_xml_to_5classes.py](file:///d:/Aging/ml/train/update_xml_to_5classes.py) | 批量将 XML 从 7 类更新为 5 类 |

### 3.5 验证集/测试集推理结果（第二次更新，5 类模型 + 337 张标注图）

**val 集（67 张图，662 个 GT，512×512 模型）：F1 = 0.9970**

| 类别 | GT | Det | TP | Recall | Precision |
|---|---|---|---|---|---|
| SIG_area | 176 | 176 | 175 | 0.99 | 0.99 |
| PWR_area | 66 | 67 | 66 | 1.00 | 0.99 |
| VPL | 176 | 176 | 176 | 1.00 | 1.00 |
| CPL | 177 | 176 | 176 | 0.99 | 1.00 |
| PWR | 67 | 67 | 67 | 1.00 | 1.00 |
| **TOTAL** | **662** | **662** | **660** | **1.00** | **1.00** |

**test 集（34 张图，362 个 GT，512×512 模型）：F1 = 0.9890**

| 类别 | GT | Det | TP | Recall | Precision |
|---|---|---|---|---|---|
| SIG_area | 97 | 98 | 97 | 1.00 | 0.99 |
| PWR_area | 36 | 34 | 34 | 0.94 | 1.00 |
| VPL | 98 | 98 | 97 | 0.99 | 0.99 |
| CPL | 97 | 98 | 97 | 1.00 | 0.99 |
| PWR | 34 | 34 | 33 | 0.97 | 0.97 |
| **TOTAL** | **362** | **362** | **358** | **0.99** | **0.99** |

**结论**：VPL_H 样本不足问题已通过架构变更解决，所有 5 类检测均达到 0.97+ 精度。

### 3.6 ESP32-CAM 数据采集工具

开发了 ESP32-CAM 录制固件，用于采集现场视频数据，便于后期标注扩充数据集。

**文件位置**：`firmware/esp32cam_recorder/esp32cam_recorder.ino`（原 `led_pipeline/esp32cam/`，已迁移至 `firmware/`）

**核心特性**：
- 连接手机热点 `QH` / `123456789`
- 实时 MJPEG 视频流预览（手机浏览器）
- **无需 SD 卡** — 手机浏览器端用 Canvas + MediaRecorder 录制
- 点击"开始录制" → 浏览器端 Canvas 逐帧抓取视频流
- 点击"停止录制" → 自动打包为 **MP4/WebM** 下载到手机
- 自动检测浏览器支持的视频格式，优先 MP4
- 支持 OV2640 / OV3660 两种摄像头传感器（自动多方案降级初始化）
- 非阻塞 MJPEG 流处理（每 50ms 轮询其他 HTTP 请求）

**使用方法**：
1. Arduino IDE 烧录，选择 `AI Thinker ESP32-CAM`，PSRAM 开启
2. 手机浏览器访问 `http://<ESP_IP>/`
3. 点击"开始录制"→ "停止录制"→ 视频自动下载到手机
4. PC 端用 ffmpeg 抽帧：`ffmpeg -i video.mp4 -q:v 2 frame_%04d.jpg`

---

## 四、代码结构

### 主线路径：`ml/`（原 `led_pipeline/`）

```
ml/
├── HANDOVER.md                      # 本交接文档
│
├── train/                           # 训练相关
│   ├── config_fp_train_v3.json      # 当前主配置（5类，512输入，200epoch）
│   ├── config_fp_train.json         # 旧4类配置（历史保留）
│   ├── gen_fp_txt.py                # 三分划分生成 train/val/test txt
│   ├── train_fp.py                  # 训练入口（调用 train.py 的 train）
│   └── update_xml_to_5classes.py    # 批量将 XML 从 7 类更新为 5 类
│
├── classifier/                      # LED 二分类器（2026-08-06 新增）
│   ├── model.py                     # TinyConv 模型定义（6.7K参数）
│   ├── train.py                     # 训练脚本
│   ├── infer.py                     # 推理接口（LEDClassifier class）
│   ├── prepare_data.py              # 从标注裁剪 ROI 生成 L/H 数据集
│   └── weights/
│       └── best.pth                 # 训练好的二分类权重
│
├── ablation/                        # 消融实验（可随时复现）
│   ├── configs/                     # 12 组实验配置文件
│   ├── results/                     # 各实验的训练权重 + 推理结果
│   └── scripts/                     # 消融实验脚本
│       ├── gen_configs.py
│       ├── train_ablation.py
│       ├── infer_ablation.py
│       └── run_ablation.py
│
├── datasets/                        # 数据集（FP/A 系列）
│   ├── FP/                          # FP 系列（Annotations + 5类副本 + JPEGImages + txt）
│   └── A/                           # A 系列
│
├── weights/                         # 模型权重（仅保留被代码引用的当前版本）
│   ├── FP_v3_5classes_v4/           # 当前 5 类 YOLO 权重
│   └── pretrained/                  # COCO 预训练 + simhei.ttf
│
├── annotation_io.py                 # 标注数据读写（被 app/data_page 懒加载引用）
├── annotation_widget.py             # 标注画布（被 app/data_page 懒加载引用）
├── config.py                        # 集中配置（数据集定义 + 训练参数）
├── train.py                         # 通用训练入口
└── ANNOTATION_SCHEME.md             # 标注规范
```

### 检测模块：`detect/`（仓库根，原 `led_pipeline/detect/` + `esp32cam/`）

```
detect/
├── infer_fp.py                  # 验证集/测试集批量推理评估（默认512×512）
├── infer_a.py                   # A 系列推理验证
├── detect_fp_video.py           # 单路视频检测（5类YOLO + TinyConv二分类器）
├── detect_a_video.py            # A 系列视频检测
├── fp_cascade_pipeline.py       # 三级递进检测 pipeline（历史保留）
├── pc_yolo_detect.py            # PC 端 ESP32-CAM 拉流 + YOLO 推理
├── README_esp32cam.md           # ESP32-CAM 部署说明
└── outputs/                     # 推理输出（vis_*.jpg, det_*.mp4）
```

### 通用框架（根目录，非 ml 专属）

- `ml/train.py` —— 通用训练入口
- `ml/config.py` —— 数据集配置（含 FP 的 label_list，`input_shape` 已改为 `[512,512]`）
- `model/YOLOV8.py` —— YOLOv8 模型定义
- `model/SE_YOLO.py` —— 带 SE 注意力机制的 YOLO
- `model/C_S_YOLO.py` —— 带 CBAM 注意力机制的 YOLO
- `model/S_C_YOLO.py` —— 带 SC 注意力机制的 YOLO
- `utils/` —— 工具函数（bbox decode、训练循环、评估等）

### 权重文件目录

```
weights/
├── FP_v3_5classes_v2/          ← 当前最新（5 类，337 张标注图，当前使用）
│   ├── best_epoch_weights.pth  ← 最佳 YOLO 权重
│   ├── model_best_precision_deploy.pt  ← 部署格式
│   └── loss_2026_08_06_20_30_58/  ← 训练日志
├── FP_v3_5classes/             ← 旧 5 类（277 张标注图，历史备份）
├── FP_v2/                      ← 旧 7 类（512×512，历史备份）
├── FP_LED/                     ← 更早的 7 类（历史备份）
├── FP/                         ← 最早 7 类（640×640，历史备份）
└── pretrained/                 ← COCO 预训练权重
```

### 关键约束（来自项目记忆，必须遵守）

1. **坐标解包顺序**：推理脚本必须按 `(top, left, bottom, right)` 即 `(y1, x1, y2, x2)` 解包，否则所有框会塌陷成竖条
2. **FP03 视角不同**：FP03 与 FP00 训练视角不同，已通过补充 FP03 标注解决
3. **VPL/CPL 类混淆**：VPL/CPL 白色方块外观相同，YOLO 难可靠区分，生产环境可用位置聚类消除
4. **输入分辨率 512×512**：已确认可接受，计算量降低 36%，实测帧率提升约 50%
5. **消融实验结论**：当前数据集上注意力机制无明显增益，建议在数据集扩充后重新评估
6. **LED 亮灭由 TinyConv 判断**：YOLO 不再区分 VPL_H/VPL_L，彻底解决冲突问题
7. **XML 标注为 5 类**：所有 XML 已通过 `update_xml_to_5classes.py` 统一更新，LabelImg 可正常显示

---

## 五、近期完成的工作（2026-08-06 会话）

### 5.1 第一次更新（上午-下午）

- 消融实验（12 组完整实验）：3 种分辨率 × 4 种注意力机制
- 主线代码迁移到 512×512 输入
- 数据集扩充：277 张标注图 + 重训 + 推理验证
- ESP32-CAM 录制工具开发（手机端浏览器录制，无需 SD 卡）
- 闪烁统计功能开发（FlashTracker 类，基于 SIG_area 区域定位）
- 检测框平滑处理（DetectionSmoother 类，EMA 算法）

### 5.2 第二次更新（晚上）

- **架构重构**：YOLO 从 7 类改为 5 类，LED 亮灭由 TinyConv 二分类器判断
- **二分类器开发**：TinyConv 模型（6.7K 参数，99.5% 准确率）
- **XML 统一更新**：批量将 327 个 XML 从 7 类更新为 5 类
- **数据集再次扩充**：新增 60 张标注图，总量从 277 增至 337 张
- **模型重训**：5 类 YOLO 重训 200 epoch，val mAP=99.56%，F1=0.9932
- **推理验证**：val F1=0.9970，test F1=0.9890，所有 5 类均达 0.97+
- **视频流验证**：FP04 视频 32.5fps，VPL0/VPL2 闪烁统计正确，VPL1/VPL3 稳定

---

## 六、下一步开发计划

### 阶段 1：多路并发推理系统开发

**目标**：PC 端支撑 54 路 ESP32-CAM 视频流并发 YOLO 推理

1. **ESP32-CAM 降帧固件改造**
   - 当前 `esp32cam_stream.ino` 已实现 MJPEG 流服务器
   - 需改造：降帧到 1.5fps（`delay(30)` → `delay(666)`），支持设备 ID 配置

2. **PC 端多路拉流 + batch 推理**
   - 当前 `pc_yolo_detect.py` 只支持单路
   - 需开发：多线程拉流池（54 路）+ batch=8 GPU 推理 + 按需显示
   - 架构：拉流线程池 → 帧队列 → batch 推理调度 → 结果字典 → 按需显示线程

3. **电流数据接收模块**（12 路 ESP32）
   - 待开发：独立线程接收 12 路电流文本数据
   - **需用户确认**：数据格式（TCP/MQTT/HTTP？字段定义？）

4. **结果输出模块**
   - **需用户确认**：CSV 日志 / MQTT 上报 / 数据库 / 仅内存查询

### 阶段 2：数据扩充（按需）

**目标**：进一步提升模型泛化能力

1. **用 ESP32-CAM 录制现场视频**
   - 烧录 `esp32cam_recorder.ino` 到 ESP32-CAM
   - 手机浏览器访问控制，录制不同角度/光照条件视频

2. **抽帧 + 标注**
   - 用 ffmpeg 抽帧：`ffmpeg -i video.mp4 -q:v 2 frame_%04d.jpg`
   - 约 184 张未标注图可继续标注

3. **重训模型**
   - 更新 `gen_fp_txt.py` 重新划分 7:2:1
   - 重新训练，评估性能

### 阶段 3：模型优化（按需）

1. **数据集扩充后重新评估注意力机制**（当前消融实验结论可能因数据量少而不显著）
2. **TensorRT 部署优化**（如需进一步加速）

### 阶段 4：部署测试

1. 实际 ESP32-CAM 硬件接入测试
2. 路由器汇聚网络部署
3. 长时间稳定性测试

---

## 七、关键运行命令

### 数据集划分

```powershell
# 重建三分 txt（新增标注后必须执行）
python ml\train\gen_fp_txt.py
```

### 训练

```powershell
# YOLO 训练（从 COCO 预训练起步）
cd ml
python train\train_fp.py

# 二分类器训练
cd ml
python classifier\train.py
```

### 推理验证

```powershell
# val 集评估（512×512，v2 权重）
python detect\infer_fp.py --split val --conf 0.25

# test 集评估
python detect\infer_fp.py --split test --conf 0.25

# 单路视频检测（512×512，5类YOLO + TinyConv二分类器）
python detect\detect_fp_video.py --video video\FP03.mp4 --conf 0.20
```

### ESP32-CAM 操作

```powershell
# 方案 A：PC 端拉流 YOLO 推理（烧录 firmware/esp32cam_stream/esp32cam_stream.ino）
python detect\pc_yolo_detect.py --url http://<ESP_IP>/stream

# 方案 B：手机端录制视频采集数据（烧录 firmware/esp32cam_recorder/esp32cam_recorder.ino）
# 手机浏览器访问 http://<ESP_IP>/ 即可操作
```

### XML 标注更新（新增标注后可能需要）

```powershell
# 将 XML 中的旧 7 类名称统一更新为 5 类
python ml\train\update_xml_to_5classes.py
```

### 消融实验复现

```powershell
# 一键运行所有 12 组实验
cd ml
python ablation\scripts\run_ablation.py
```

### 视频抽帧

```powershell
# MP4 格式
ffmpeg -i video.mp4 -q:v 2 frame_%04d.jpg

# WebM 格式
ffmpeg -i video.webm -q:v 2 frame_%04d.jpg
```

---

## 八、待用户确认的关键问题

在开发多路并发系统前，需确认以下 3 点：

### 1. 电流数据格式

12 台 ESP32 回传电流检测数据，需明确：
- 传输协议：TCP socket / MQTT / HTTP POST ？
- 数据字段：如 `device_id, current_ma, timestamp` ？
- 回传频率：1 Hz / 10 Hz ？

### 2. 开发优先级

- 先开发多路并发系统？
- 还是先用 ESP32-CAM 录制现场视频补充标注 → 再开发多路并发？

### 3. 结果输出方式

LED 状态检测结果怎么输出：
- CSV 日志文件（最简单）
- MQTT 上报（适合集成到其他系统）
- 数据库存储（便于查询）
- 仅内存 + 前端按需查询

---

## 九、风险清单

| 风险 | 概率 | 影响 | 缓解措施 |
|---|---|---|---|
| 二分类器 L/H 样本不均衡（6.1:1） | 中 | 亮灯状态误判为灭灯 | 训练时已使用类别权重平衡，准确率 99.5% |
| ESP32-CAM WiFi 信道竞争 | 中 | 多台并发时帧率不稳 | 3 路由器分信道（1/6/11） |
| GTX 1650 显存不足（batch=8） | 低 | OOM 崩溃 | 显存预估 1.5-2GB，4GB 够用 |
| 面板旋转偏移过大 | 中 | YOLO 检测失败 | 训练数据已含多视角，泛化良好（F1=0.989） |
| 注意力机制在数据扩充后可能有增益 | 低 | 当前消融结论可能变化 | 数据集扩充后重新评估，注意力模型代码已就绪 |

---

## 十、项目记忆关键信息

以下信息已记录在项目记忆中，新会话可自动读取：

- yolo_fastest 训练失败历史与删除清理
- FP 数据集 5 类标签与 7:2:1 划分
- VPL/CPL 类混淆问题与位置聚类方案
- FP03 视角差异导致 PWR UNCERTAIN 的修复
- ESP32-CAM 硬件限制与图传方案确定
- GTX 1650 4G 整机配置与性能评估
- **消融实验结论**（12 组完整实验，512×512 Baseline 最佳，注意力机制无显著增益）
- **ESP32-CAM 录制工具**（手机端浏览器录制，无需 SD 卡，优先 MP4）
- **输入分辨率已迁移至 512×512**（计算量降低 36%，帧率提升约 50%）
- **YOLO 5 类 + TinyConv 二分类器架构**（2026-08-06 晚上确定，彻底解决 VPL_H/L 冲突）
- **数据集已扩充至 337 张标注图**（5 类，train 236 / val 67 / test 34）
- **当前最佳权重**：`weights/FP_v3_5classes_v2/best_epoch_weights.pth`

---

## 十一、联系交接

- 本交接文件用于新会话续接开发
- 新会话开始时，AI 会自动读取项目记忆，无需重复说明背景
- **建议开发起点**：进入多路并发推理系统开发，或先用 ESP32-CAM 录制现场视频继续扩充数据集