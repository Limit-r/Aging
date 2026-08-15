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

*最后更新：2026-08-14 — 方案确认，进入 UI 设计阶段*