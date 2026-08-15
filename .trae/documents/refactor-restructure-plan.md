# 项目结构重构方案（d:\Aging → GitHub 管理）

> 状态：草案（待两轮批判性分析后定稿）
> 生成日期：2026-08-15
> 目标仓库：`https://github.com/Limit-r/Aging`（已创建，当前为空，仅 README）

---

## 0. 用户决策（已确认）

| 决策项 | 选择 |
|---|---|
| 数据集是否纳入 Git | ✅ 全部纳入（约 358MB） |
| 重构深度 | ✅ 深度重构 `led_pipeline` |
| 元文件 | ✅ README.md + MIT LICENSE |

---

## 1. 现状盘点

### 1.1 磁盘占用分布

| 路径 | 磁盘占用 | 将被 git 跟踪 | 说明 |
|---|---|---|---|
| `led_pipeline/` | **8.1 GB** | 326 MB / 17927 文件 | 权重+数据集+消融结果+输出 |
| `datasets/`（根） | 32 MB | 32 MB / 692 文件 | A 系列图片+标注 |
| `app/` | 0.28 MB | 规整 | PyQt5 控制台，无需改动 |
| `Video/` | 11.9 MB | 0（*.mp4 已忽略） | 测试视频 |
| `weights/`（根） | 4.9 MB | 0（*.ttf 仅 9MB 被跟） | pretrained 字体 |
| `logs/` | 0.96 MB | 0（*.log 已忽略） | 运行时日志 |
| 根目录散落文件 | <1 MB | 少量 | 见 §1.3 |

**git 将跟踪总量 ≈ 360 MB / 约 1.8 万文件**（权重 .pth/.onnx/.pt 与 mp4 已被 .gitignore 排除，安全）。

### 1.2 `led_pipeline` 内部结构问题

```
led_pipeline/                          # 8.1 GB 巨型单体
├── train/weights/A                    # 1.0 GB  ← A 数据集 YOLO 权重
├── weights/ pretrained 854MB / FP_v2 / FP_v3_5classes{,_v2,_v3,_v4}  # 多处权重
├── merge_test/weights                 # 687 MB
├── ablation/results/                  # ~4 GB 消融结果权重
├── datasets/A, datasets/FP            # 数据集
├── classifier/data/train/L,H          # 二分类 ROI 数据
├── detect/outputs, merge_test/outputs # 推理输出
├── esp32cam/                          # ESP32-CAM 固件（与根目录固件分散）
└── annotation_io.py / annotation_widget.py / extract_*.py  # 标注工具散在根
```

**核心问题**：
- **权重无版本收敛**：同一模型的多代权重（FP_v2 / v3 / v3_5classes / _v2/_v3/_v4）全部保留，且散布在 `train/weights/`、`weights/`、`merge_test/weights/`、`ablation/results/` 四处。
- **数据集双份**：根目录 `datasets/`（A 系列 692 文件）与 `led_pipeline/datasets/A/` 疑似同源重复。
- **标注工具与训练根脚本混放**：`annotation_io.py`、`annotation_widget.py`、`extract_frames_A.py`、`extract_video_frames.py`、`get_map.py`、`_inspect_fp.py` 都堆在 `led_pipeline/` 根。
- **ESP32 固件分裂**：根目录 `esp32_adc_oled/`、`esp32_adc_oled_wifi/`、`esp32_i2c_scanner.ino` 与 `led_pipeline/esp32cam/` 各自为政。

### 1.3 根目录散落文件

`blink_results.json` / `_before` / `_after`、`led_positions.json`、`_smoke_annotate.py`、`esp32_i2c_scanner.ino`、`Video/`、`weights/`。

### 1.4 代码导入结构（关键约束）

`led_pipeline` 代码是**扁平命名空间**，近 50 处导入点直接引顶层模块：

```
from model import YOLOV8            # detect/ infer/ train/ 等大量脚本
from utils import ...               # 同上
from train import ...               # ablation/merge_test/setup
from classifier import ...          # detect/merge_test
from config import ...              # train.py
from led_pipeline import ...        # classifier/infer.py
```

`config.py` 使用相对 CWD 的路径：`datasets\FP\label.txt`、`weights/FP`。
**结论：代码目录不宜重排，否则大面积破坏导入；本次重构聚焦"产物层"（权重/数据集/输出/固件），代码层仅做归位，不做深改。**

---

## 2. 目标结构（初稿）

```
d:\Aging\
├── Main.py                       # 应用入口（不动）
├── README.md                     # 新增：项目总览
├── LICENSE                       # 新增：MIT
├── environment.yml               # 不动
├── ARCHITECTURE.md               # 不动
├── .gitignore                    # 修订：数据集策略
├── app/                          # PyQt5 控制台（不动）
├── led_pipeline/                 # ML 检测 pipeline（重构）
│   ├── README.md                 # 新增：pipeline 说明
│   ├── config.py                 # 不动（保持相对 CWD 约定）
│   ├── train.py                  # 不动
│   ├── model/  utils/            # 不动（扁平导入依赖）
│   ├── train/                    # 训练脚本（不动）
│   ├── detect/                   # 推理脚本（不动）
│   ├── classifier/               # TinyConv（不动）
│   ├── ablation/                 # 只保留 scripts+configs，results 归档
│   ├── annotation/               # 新增：标注工具归位
│   │   ├── annotation_io.py
│   │   ├── annotation_widget.py
│   │   └── extract_*.py
│   ├── datasets/                 # 统一数据集
│   │   ├── FP/                   # 现有不动
│   │   └── A/                    # 现有不动
│   ├── weights/                  # 只保留当前最佳，历史权重归档
│   └── outputs/                  # 统一推理输出
├── datasets/                     # 根级数据集（判定去留，见 §5-Q1）
├── firmware/                     # 新增：全项目固件统一
│   ├── esp32_adc_oled/
│   ├── esp32_adc_oled_wifi/
│   ├── esp32_i2c_scanner/
│   └── esp32cam/                 # 从 led_pipeline/esp32cam 迁入
├── video/                        # 测试视频（git 忽略）
├── archive/                      # 新增：历史权重/消融结果/诊断输出归档
└── tools/                        # 不动
```

---

## 3. 迁移映射表

| 现状 | 目标 | 动作 |
|---|---|---|
| 根 `blink_results*.json` `led_positions.json` `_smoke_annotate.py` | `archive/` 或删除 | 移入归档 |
| 根 `Video/` | `video/` | 重命名（git 忽略） |
| 根 `weights/pretrained` | 与 `led_pipeline/weights/pretrained` 合并 | 合并去重 |
| 根 `esp32_*.ino` / `esp32_adc_oled*/` | `firmware/` | 归位 |
| `led_pipeline/esp32cam/` | `firmware/esp32cam/` | 迁入 |
| `led_pipeline/annotation_io.py` 等 | `led_pipeline/annotation/` | 归位 |
| `led_pipeline/train/weights/A` 等历史权重 | `archive/` | 移入归档 |
| `led_pipeline/ablation/results/` | `archive/`（脚本保留） | 移入归档 |
| `led_pipeline/detect/outputs` `merge_test/outputs` | `led_pipeline/outputs/` | 归位 |
| 根 `datasets/` | 判定：并入 `led_pipeline/datasets/A` 或保留 | **待确认 Q1** |

---

## 4. 破坏面分析（风险前置）

| 风险 | 等级 | 缓解 |
|---|---|---|
| 移动 `annotation_io.py` 等 → 破坏 `data_page.py` 的 lazy import | 中 | 同步改 `app/ui/pages/data_page.py` 导入路径 |
| 移动权重/输出 → `config.py`、各脚本硬编码相对路径失效 | 中 | 保持 `led_pipeline` 内相对 CWD 约定不变；仅移动**代码外**产物，脚本内路径同步更新 |
| 移动 `esp32cam` → 破坏其 README 内相对路径 | 低 | 改 README 引用 |
| 358MB 数据集推送 → GitHub 仓库臃肿 | 低 | 用户已确认纳入；推送前确认 <1GB 上限 |
| 合并 `weights/pretrained` → 若被脚本引用会失效 | 低 | 检索引用后决定 |

---

## 5. 待确认问题

- **Q1**：根目录 `datasets/`（A 系列 692 文件）与 `led_pipeline/datasets/A` 是否同源？决定并入 or 保留。
- **Q2**：历史权重（FP_v2/v3 等约 7GB）与消融 results（4GB）→ 归档到 `archive/`（不推送）还是删除？建议归档。
- **Q3**：`led_pipeline` 代码层是否接受"只归位、不改 import"（保持扁平结构）？

---

## 6. 执行阶段

1. **阶段 0**：确认 Q1-Q3 → 微调目标结构
2. **阶段 1**：根目录清理 + `firmware/` 归位 + `video/` 重命名
3. **阶段 2**：`led_pipeline` 产物层重构（weights 收敛 / outputs 归位 / annotation 归位 / ablation results 归档）
4. **阶段 3**：改 `data_page.py` 等受影响导入；全项目 `py_compile` + 硬编码自检
5. **阶段 4**：补 README + LICENSE + 修订 .gitignore
6. **阶段 5**：git 本地提交 → 关联远程 → 推送 GitHub

---

## 7. 第一轮批判性分析（自攻击初稿）

对初稿逐条攻击，发现 6 处缺陷：

**C1（假设错误）— 根 `datasets/` 与 `led_pipeline/datasets/A` 并非同源**
实测：根 `datasets/JPEGImages`（frame_*.jpg，313 张）与 `led_pipeline/datasets/A/JPEGImages`（a01_*.jpg，386 张）**重叠 0**。初稿 §5-Q1 的"并入"建议不成立，两套数据都应保留。

**C2（低估反向依赖）— `app` 直接导入 `led_pipeline`**
`app/ui/pages/data_page.py` 用 `from led_pipeline.annotation_io import ...`、`from led_pipeline.annotation_widget import ...`（懒加载）。**移动 `annotation_io.py`/`annotation_widget.py` 会直接破坏数据中心页**。初稿把它们"归位到 annotation/"是错误决策。

**C3（"权重可自由归档"错误）**
实测被代码/配置引用的权重：`weights/FP`、`weights/FP_v3_5classes_v4`、`weights/pretrained`（含 simhei.ttf）、`weights/A`。初稿说"只保留最佳、全归档"会破坏 `model/*.py`、`detect/*.py` 的加载。**只能归档未被引用的历史权重**：`FP_v2`、`FP_v3_5classes`、`_v2`、`_v3`（约 1.7GB）。

**C4（数据纳入策略自相矛盾）**
用户选"全部纳入 358MB"，但同时要"深度重构"。数据集图片 + 生成型 ROI 数据（`classifier/data`、`merge_test/clf_data`）都是可再生成产物，全推会放大仓库。初稿未区分"原始标注数据"与"生成数据"。

**C5（CWD 约定未处理）**
`config.py` 用 `datasets\FP\label.txt`、`weights/FP` 相对路径，脚本必须**以 `led_pipeline/` 为 CWD** 运行。重构后从 `d:\Aging` 根直接跑会失败。初稿未明确运行入口约定。

**C6（`merge_test` 去留未定）**
HANDOVER.md 未提及 `merge_test/`（687MB 权重 + 输出），是实验遗留。初稿遗漏。

---

## 8. 第二轮批判性分析（对修订方向再攻击）

**R1 — "那深度重构到底重构什么？"**
若代码不能移动（C2/C3），是否等于放弃深度重构？→ 答：**否**。批判后明确：`led_pipeline` 代码结构已被 HANDOVER.md 定义且自洽（train/detect/classifier/ablation/model/utils 是逻辑划分），**真正可安全重构的是"产物层"**（权重收敛、输出归位、生成数据剔除）+ 固件 + 根目录卫生。深度重构≠重排代码，而是**让仓库只含"代码+原始标注"，剔除可再生成的大产物**。这比"重排 import"更有价值且零破坏。

**R2 — 全部纳入 358MB 是否仍需坚持？**
→ 保留原始标注（XML+JPEGImages）以复现训练，但**剔除生成型数据**（`classifier/data`、`merge_test/clf_data`、`ablation/results`、`detect/outputs`、`merge_test/outputs`），这些可由脚本重新生成。这样既满足"纳入数据集"，又将仓库收敛到合理体积。

**R3 — 固件归位是否安全？**
`led_pipeline/esp32cam/` 内部有相对路径与 README，迁移有风险。→ 修订为：**只归位根目录固件**（`esp32_adc_oled*`、`esp32_i2c_scanner.ino` → `firmware/`），`led_pipeline/esp32cam` 保持原位并在 README 注明。

**R4 — 归档目录会不会被误推送？**
→ 修订 .gitignore 显式排除 `archive/` 内大权重（`archive/**/*.pth` 等），确保归档只留本地。

---

## 9. 定稿方案（修订版，取代 §2/§3/§5/§6）

### 9.1 原则
1. **代码零移动**：`led_pipeline` 内所有 `.py` 原位不动（扁平命名空间 + `app` 反向依赖），`annotation_io.py`/`annotation_widget.py` 留在根。
2. **产物层收敛**：只归档**未被代码引用**的历史权重与生成型输出到 `archive/`（不推送）。
3. **保留被引用权重**：`weights/FP`、`weights/FP_v3_5classes_v4`、`weights/pretrained`、`weights/A`。
4. **数据集全部纳入**（用户已确认），但剔除生成型 ROI 数据。
5. **固件只归位根目录** → `firmware/`。
6. **运行约定**：所有 `led_pipeline` 脚本以 `led_pipeline/` 为 CWD 运行，写入 README。

### 9.2 目标结构
```
d:\Aging\
├── Main.py / environment.yml / ARCHITECTURE.md   # 不动
├── README.md / LICENSE(MIT)                      # 新增
├── .gitignore                                    # 修订
├── app/                                          # 不动
├── led_pipeline/                                 # 代码零移动
│   ├── config.py train.py model/ utils/ train/ detect/
│   ├── classifier/  ablation/  merge_test/          # 保留代码，剔生成产物
│   ├── annotation_io.py annotation_widget.py extract_*.py  # 原位
│   ├── datasets/{FP,A}/                            # 原始标注+图片（纳入）
│   └── weights/{FP,FP_v3_5classes_v4,pretrained,...}  # 保留被引用
├── datasets/                                    # 根级 A 系列（保留，不同源）
├── firmware/                                    # 新增：根目录固件归位
│   ├── esp32_adc_oled/ esp32_adc_oled_wifi/ esp32_i2c_scanner/
├── video/                                       # 测试视频（git 忽略）
├── archive/                                     # 新增：历史权重/生成输出/消融结果（本地归档，不推送）
└── tools/                                       # 不动
```

### 9.3 迁移映射（修订）
| 来源 | 去向 | 说明 |
|---|---|---|
| `led_pipeline/weights/{FP_v2,FP_v3_5classes,FP_v3_5classes_v2,FP_v3_5classes_v3}`（~1.7GB） | `archive/` | 未被引用，归档不推 |
| `led_pipeline/merge_test/weights`（687MB） | `archive/` | 实验遗留 |
| `led_pipeline/ablation/results/`（~4GB） | `archive/` | 结果可复现，脚本保留 |
| `led_pipeline/{detect,merge_test}/outputs/` | `archive/` | 生成输出 |
| `led_pipeline/classifier/data/`、`merge_test/clf_data/` | `archive/` | 生成 ROI |
| 根 `Video/` | `video/` | git 忽略 |
| 根 `esp32_adc_oled*`、`esp32_i2c_scanner.ino` | `firmware/` | 归位 |
| 根 `blink_results*.json`、`led_positions.json`、`_smoke_annotate.py` | `archive/` | 诊断产物 |
| 根 `weights/pretrained`（4.9MB） | 并回 `led_pipeline/weights/pretrained` | 合并去重 |

### 9.4 受影响代码改动（最小集）
- `app/ui/pages/data_page.py`：**无改动**（标注文件原位）。
- 档案移动不触碰代码引用（被引用权重均保留）。
- 仅需：`led_pipeline/README.md` 记录新约定。

### 9.5 执行阶段（修订）
1. 阶段 0：确认定稿方案（本稿）
2. 阶段 1：根目录清理 + `firmware/` + `video/`
3. 阶段 2：`led_pipeline` 产物归档（§9.3 表）
4. 阶段 3：补 `led_pipeline/README.md`
5. 阶段 4：补根 README + LICENSE + 修订 .gitignore
6. 阶段 5：`py_compile` + 硬编码自检 → git 提交 → 关联远程 → 推送

### 9.6 风险收敛对照（修订后）
| 初稿风险 | 修订后 |
|---|---|
| 移动 annotation 破坏 data_page | ✅ 标注文件原位，无此风险 |
| 归档被引用权重破坏加载 | ✅ 仅归档未引用权重 |
| 358MB 全推 | ✅ 剔生成数据，收敛体积 |
| CWD 运行失败 | ✅ README 明确运行约定 |

---

*定稿方案完成。待用户批准后执行。*