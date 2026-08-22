# 数据中心（Data Center）设计方案

> 文档版本：v1  ·  2026-08-14  ·  待审阅
> 状态：方案已确认，进入 UI 设计阶段

---

## 0. 目标

把 `app/ui/pages/data_page.py` 从占位页升级为功能完整的数据中心，
在原有「历史 / 趋势 / 导出 / 报表」之外，新增**数据标注 + 类别管理 + 训练连通**组成标注闭环。

---

## 1. 范围与决策（已与用户确认）

| 决策项 | 结论 |
|--------|------|
| 交付顺序 | **先做标注闭环**，历史/趋势/导出后续再补 |
| 数据标注形态 | **内置画框标注器**（替代/补充 labelImg） |
| 类别管理粒度 | **动态类别注册表**（集中管理，下游自动跟随） |
| 与 led_pipeline 打通 | **连通训练**（转换 + 训练子进程） |
| 依赖加载时机 | **懒加载**（切到标注/训练页签才 import led_pipeline） |
| 训练触发方式 | **subprocess 子进程**（GUI 不卡，日志回显） |

---

## 2. 标注闭环 · 三层交付

### Phase A — 类别注册表（地基）

- 新增 `led_pipeline/annotation_registry.py`：类别注册表模块
- 新增 `led_pipeline/datasets/categories.json`：动态类别数据源
- 改造 `prepare_data.py` / `gen_5class_xmls.py` / `gen_fp_txt.py`：从注册表读类别，删掉写死的集合

注册表 JSON 核心结构：

```json
{
  "series": ["FP"],
  "categories": [
    {"name": "FP_SIG_area", "kind": "area", "hl": false},
    {"name": "FP_PWR_area", "kind": "area", "hl": false},
    {"name": "FP_VPL", "kind": "led", "hl": true},
    {"name": "FP_CPL", "kind": "led", "hl": true},
    {"name": "FP_PWR", "kind": "led", "hl": true}
  ]
}
```

- `hl=true` 类别在标注时自动展开为 `_H`/`_L`；YOLO 5 类映射自动去掉 H/L；TinyConv ROI 自动取 H/L。

### Phase B — 画框标注器（GUI 核心）

- 新增 `led_pipeline/annotation_widget.py`：QGraphicsView 画框标注器 + VOC XML 读写
- 图片列表导航（上一张/下一张/跳转）、画框、选类别、保存 XML
- 关联 `datasets/FP/JPEGImages/` + `Annotations/`

### Phase C — 转换 + 训练子进程（闭环收口）

- 新增 `led_pipeline/training_runner.py`：subprocess 封装 gen/prepare/train
- `data_page.py` 懒加载，新增「数据标注」「训练」页签接入上述模块
- 日志从子进程回显到 GUI

---

## 3. 数据中心 UI 结构（本阶段重点）

```
DataCenterPage (app/ui/pages/data_page.py)
   ├─ 顶部工具条：标题 + 页签切换
   ├─ Tab1 历史/趋势/导出   ← HistoryBuffer + CellController（轻量，后续补）
   ├─ Tab2 数据标注          ← 懒加载 led_pipeline/annotation
   │     ├─ 顶栏：类别注册表管理（增删改类别）
   │     ├─ 左：图片列表导航
   │     ├─ 中：QGraphicsView 画框标注画布
   │     └─ 下：当前图片标注对象列表 + 保存
   └─ Tab3 训练/转换         ← 懒加载，subprocess 触发
         ├─ 数据集汇总（各类别统计）
         ├─ 一键 gen_5class / prepare_data / gen_fp_txt
         └─ 模型训练 / 评估（日志回显）
```

---

## 4. 关键约束（贯穿全程）

1. **懒加载**：`data_page.py` 顶部不 import led_pipeline；只有切到标注/训练页签才加载，Main.py 启动保持轻量不碰 torch。
2. **依赖单向**：标注/训练逻辑全部放 `led_pipeline/`，`app/ui` 只做编排调用，不反向污染 app 分层。
3. **不动已有旧数据**：遵循 `ANNOTATION_SCHEME.md`，不原地改 `Annotations/`，H/L 信息保留。
4. **工程规范**：文案走 `labels.py`、视觉量走 `tokens.py`、通道号走 `format_cid`、QSS 集中、日志用 `narrative.event()`。

---

## 5. 变更清单（实现时维护）

| 文件 | 动作 |
|------|------|
| `led_pipeline/datasets/categories.json` | 新增 |
| `led_pipeline/annotation_registry.py` | 新增 |
| `led_pipeline/annotation_widget.py` | 新增（Phase B）|
| `led_pipeline/training_runner.py` | 新增（Phase C）|
| `led_pipeline/classifier/prepare_data.py` | 改造：读注册表 |
| `led_pipeline/train/gen_5class_xmls.py` | 改造：读注册表 |
| `led_pipeline/train/gen_fp_txt.py` | 改造：读注册表 |
| `app/ui/pages/data_page.py` | 重写：页签 + 懒加载 |
| `app/core/labels.py` | 新增数据中心文案 |
| `app/core/tokens.py` | 新增 UI 视觉量（如需）|
| `app/styles/templates.py` + `stylesheet.py` | 新增数据中心 QSS |

---

*最后更新：2026-08-22 — 数据中心功能优化 + 主页浮窗联动 + 部署→检测闭环打通*

---

## 6. 本期功能开发（2026-08-22）

### 6.1 数据标注页 · 视频导入抽帧
- 新增 `ml/datasets_extract.py`：视频探测 + 按间隔抽帧 + 系列关联写入
  - A 系列 → `datasets/A/JPEGImages/`（aNN 批次前缀，偶数编号）
  - FP 系列 → `datasets/FP/JPEGImages/`（frame 前缀，连续编号）
- 标注页新增「⇪ 导入视频」按钮 → `VideoImportDialog`：
  - 选择视频自动探测分辨率 / fps / 总帧数
  - 选择目标系列（A / FP）+ 抽帧间隔（默认 5，范围 1~600）
  - 后台线程抽取（QThread），进度条实时回显
  - 完成后自动加载目标系列图片列表到标注页

### 6.2 数据标注页 · 筛选 + 统计
- 图片列表顶部新增筛选下拉：全部 / 已标注 / 未标注
- 新增统计标签：`共 N · 已标注 M · 未标注 K`
- 逻辑：保留 `_all_entries` 全量主列表，`_entries` 为筛选后视图

### 6.3 训练 / 转换页 · 一键流程 + 自动部署
- 一键完整流程：DATA → YOLO → ROI → CLS 串行（点击一次完成）
- 新增 `ml/train/deploy_models.py`：训练结束自动部署
  - 复制 `weights/MERGED/model_best_precision_deploy.pt` → `ml/deploy/yolo_best_deploy.pt`
  - 复制 `weights/MERGED/best_epoch_weights.pth` → `ml/deploy/yolo_best_epoch_weights.pth`
  - 复制 `classifier/weights/best_tinyconv_merged.pth` → `ml/deploy/tinyconv_best.pth`
  - 复制 `datasets/merged/label_merged.txt` → `ml/deploy/label_merged.txt`
  - 生成 `ml/deploy/latest.json` 部署清单（时间 / 来源 / 路径 / 分类器）
- `_on_all_done()` 训练全部完成后自动触发部署，日志回显

### 6.4 主页 · 浮窗联动优化
- `HomeDashboard.set_led_from_visual()` 联动三处：
  - 3D 机柜 LED（已有）
  - 右侧 LED 状态矩阵浮窗（`_led_strip`，本次接通真实数据）
  - 右上告警浮窗（`_right`，本次接通真实数据）
- 告警逻辑：anomaly → 加入告警列表；online / offline → 移除

### 6.5 部署→检测闭环打通（2026-08-22 追加）
- **统一部署产物**：`ml/deploy/` 现为检测 / 推理程序的唯一模型加载目录
  - `yolo_best_deploy.pt` 统一 9 类 YOLO（部署格式，含 model key）
  - `yolo_best_epoch_weights.pth` 最佳 epoch 权重
  - `tinyconv_best.pth` 统一 TinyConv 亮灭二分类器
  - `label_merged.txt` 统一 9 类类别表
- **检测 / 推理程序默认路径改指 `ml/deploy/`**：
  - `detect/infer_fp.py` → `deploy/yolo_best_deploy.pt` + `deploy/label_merged.txt`
  - `detect/infer_a.py` → `deploy/yolo_best_deploy.pt` + `deploy/label_merged.txt`
  - `detect/detect_fp_video.py` → YOLO + `deploy/tinyconv_best.pth`
  - `detect/detect_a_video.py` → YOLO + `deploy/tinyconv_best.pth`
  - `detect/pc_yolo_detect.py` → 保留 FP_v2 旧路径（历史 MJPEG 流演示，未纳入统一部署）
- **端到端已验证**：
  - 重新部署生成 `tinyconv_best.pth`
  - `infer_fp.py` 从 `ml/deploy/` 加载 9 类模型，单图检出 10 目标
  - `infer_a.py` 从 `ml/deploy/` 加载，单图检出 16 目标
  - `detect_fp_video.py` YOLO + TinyConv 双模型从 `ml/deploy/` 加载，逐帧检测 VPL/CPL 亮灭正常