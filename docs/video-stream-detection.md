# 视频流检测模块 — 设计与二次开发说明

> 本文档是**视频流检测**（又称"视频检测"，Video Detection）模块的**唯一权威说明**。
> 修改该模块的任何代码前，先更新本文档，再改代码。

- 适用范围：老化检测系统控制台中的**实时视频流 LED 亮灭检测与闪烁统计**。
- 关键目标：**逐帧检测不抽帧**、**模型常驻预加载复用**、**按统一位置分组的亮灭方波图 + 闪烁统计**。
- 关联文件：见文末《文件清单》。

---

## 1. 能做什么（功能总览）

把一段现场录制的视频（多路 LED 位点）导入系统，对**每一帧**做检测：

1. **目标检测**（YOLO，9 类）：定位画面中的各 LED 位点（如 `FP_VPL`、`FP_PWR_area`、`A_CLIP` …）。
2. **亮灭分类**（TinyConv）：对每个位点判定 **H（亮）/ L（灭）**。
3. **逐帧推进**：不抽帧、按视频帧率匀速**真实速度**播放检测，不漏掉一次 LED 闪烁。
4. **闪烁统计**：以"完整亮暗事件"计闪烁次数（帧级去抖，抑制抖动/微闪）。
5. **结果呈现**：左侧实时预览画面；右侧按**统一位置分组**的亮灭方波图（最多 4 张表）+ 每组闪烁/时长。

UI 分两级进入：**总览页（只标记位点）→ 双击某位点 → 单通道视频流检测页**。

---

## 2. 总体架构（两层进程）

```
┌──────────────────────────── GUI 进程 app/ui ─────────────────────────────┐
│  VideoOverviewPage (总览，只标记位点)                                      │
│       双击 open_stream_requested(cid) → HomePage 路由到                    │
│  VideoStreamPage (单通道：导入视频 + 开始/停止)                             │
│        └─ 全局单例 VisionWorkerManager (app/ui/vision_worker.py)          │
│             │  stdin 写 JSON 命令 / stdout 读 JSON 事件（信号驱动）         │
└───────────────────────────────┬───────────────────────────────────────────┘
                                 │ QProcess (独立进程)
┌───────────────────────────────▼───────────────────────────────────────────┐
│  ml/vision/worker.py  常驻检测服务（独立子进程）                             │
│   ├─ 启动即预加载 YOLO(9类) + TinyConv(H/L) → ready 事件                   │
│   └─ **单一帧批处理调度线程**：把多路流的"到点帧"打包成 batch 一次前向      │
│       YOLO → 逐流 H/L 分类/闪烁统计 → sample/done/error                    │
│       └─ ml/vision/engine.py  DetectionEngine（detect / detect_batch /    │
│                                                  classify）               │
└───────────────────────────────────────────────────────────────────────────┘
```

**为什么用常驻子进程？**
- 模型只在 worker 进程启动时加载一次，之后给任意通道检测都直接复用，GUI 不会因加载模型卡顿。
- worker 是独立 `QProcess`，**GUI 进程不 import torch**（保持 `Main.py` 轻启动），符合"`app/ui` 不依赖 torch"的约束。

---

## 3. 交互流程（GUI 侧）

### 3.1 总览页 `VideoOverviewPage`（`app/ui/pages/video_page.py`）
- 以 9×8 网格展示全部检测位点 `CH-01 … CH-72`，**只标记位置，不显示检测结果**。
- **双击**任意位点 → 发出 `open_stream_requested(cid)`，由 `HomePage` 路由到单通道 `VideoStreamPage.set_channel(cid)`。

### 3.2 单通道页 `VideoStreamPage`（`app/ui/pages/video_stream_page.py`）
1. **导入视频**：`QFileDialog` 选择本地视频（`VIDEO_IMPORT_FILTER`）。
2. **开始**：向 worker 发送 `{"cmd":"detect", ...}`，同时启动 `QTimer`（`VIDEO_REFRESH_MS=300ms`）周期刷新实时画面缩略图。
3. **实时画面**：读 `outdir/cell_{cid}.jpg`，等比缩放后显示；预览窗口按**输入视频分辨率**缩放（最大 `VIDEO_PREVIEW_MAX_W×H`，居中）。
4. **结果面板 `VsResultPanel`**：见第 6 节。

生命周期约定：
- `worker` 是全局单例，首次用到才启动（`ensure_started()`），应用退出时由 `HomePage` 统一调用 `shutdown()` 关闭（发送 `quit` → terminate → 超时 `kill`）。
- `VideoStreamPage.closeEvent` 只停止本通道检测，**不关闭 worker**。

---

## 4. 常驻 Worker（`ml/vision/worker.py`）

### 4.1 进程协议（stdin 命令 / stdout 事件，均为逐行 JSON）
**stdin 命令：**
```
{"cmd": "detect", "job": 1, "video": "a.mp4", "outdir": "tmp", "conf": 0.25, "nms": 0.45}
{"cmd": "stop",   "job": 1}
{"cmd": "quit"}
```

**stdout 事件（均含 `job`）：**
```
{"type": "ready",     "model": "yolo+tinyconv", "device": "cuda", "n_classes": 9}
{"type": "job_start", "job", "w", "h", "fps", "total"}      # 开流，视频元信息
{"type": "sample",    "job", "frame", "elapsed", "flashes", "states"}
{"type": "done",      "job", "frames", "elapsed"}
{"type": "error",     "job", "message"}
{"type": "fatal",     "message"}                              # 模型缺失等致命错误
```

协议关键语义：
- `detect` 对**相同 job** 只在 `thread.is_alive()` 时忽略；同一通道可反复重新检测。
- `stop` 通过 `threading.Event` 通知 job 线程结束；结束/异常/停止时 **job 必然从 `_jobs` 移除**，保证下次可再次调度。
- 用 `sys.stdout.reconfigure(encoding="utf-8")` 强制 UTF-8，避免 Windows GBK 中文/符号崩溃。
- 逐帧写缩略图 `outdir/cell_{job}.jpg`（`THUMB_WIDTH=420`，隔帧写，JPEG 质量 80）。

### 4.2 检测引擎 `DetectionEngine`（`ml/vision/engine.py`）
- 从 `ml/deploy/` 读取统一部署产物：`yolo_best_deploy.pt`（9 类）+ `tinyconv_best.pth` + `label_merged.txt`（`deployed_paths()`）。
- 推理参数：`phi="n"`、`input_shape=(512,512)`、默认 `conf=0.25`、`nms=0.45`。
- `detect(frame_bgr)`：YOLO letterbox 推理，返回 `[{x1,y1,x2,y2,score,cid,name}, …]`。
- `classify(frame_bgr, dets)`：对**非背景**检测框逐个 ROI 送入 TinyConv 做 H/L 二分类，返回 `{det索引: (label, conf)}`。

### 4.3 背景 / 信号灯的判定 `is_background_class()`（关键特例）
```
普通 *_area（FP_SIG_area、A_area） → 背景，排除，不计入统计。
*_PWR_area（功率灯）                → 视为信号灯，纳入统计。
```
原因：部署模型中**功率灯以 `*_PWR_area` 表达**（如 `FP_PWR_area`），它识别到的就是功率信号灯本体，必须纳入；而其余 `*_area` 是电路板背景区域，应排除。

---

## 5. LED 身份与闪烁统计（worker 侧）

### 5.1 LED ID 分配 `_assign_led_ids(dets, hl)`
按**基础类 + 槽位**生成 `samples`（每帧的每 LED 最新 H/L）：
```
{base}_{slot}: "H"/"L"
```
- 同基础类的多个目标按**中心 x 排序**，依次编号槽位（`slot`）。
- `*_PWR_area` 会**剥离 `_area` 后缀**，以 `FP_PWR_0` 形式进入统计（避免显示成 `pwr_area`）。
- 其余 `*_area`（背景）在 `is_background_class` 阶段已被排除。

### 5.2 闪烁去抖 `FlashTracker`（本次新逻辑重点）
- 语义：**一次闪烁 = 一次"完整亮暗事件"**。
- 计数规则：某 LED 只有**先连续 OFF ≥ `FLASH_DEBOUNCE_FRAMES` 帧**、随后变 on，才累计一次闪烁。
- 作用：把单帧检测抖动/微闪（`H-L-H` 快速跳变）**合并进同一次物理闪烁**，避免把一次物理闪烁数成多次。
- 参数：`FLASH_DEBOUNCE_FRAMES = 8`（约 0.2s，见 worker.py）。偏大易把快速真实闪烁合并掉，偏小无法抑制抖动，按视频帧率权衡。

> 设计说明：闪烁计数是**逐帧**精度并去抖；而折线方波图是**1 秒采样**上报（见 6.3）。因此极端快闪下两者仍可能有细微差异，这是有意的精度取舍。

### 5.3 逐帧检测 + 真实速度节流 + 多流批处理（调度器 `_tick`）
- **不抽帧**：每流每帧都检测；多路流的"到点帧"合成一个 batch 一次性 `detect_batch` 前向 YOLO，再逐流 `classify` + 统计（见 §7 多流并发）。
- **真实速度**：每流按**自身 `1/fps` 独立节流**（`next_t` 逐帧推进），一段 16s 视频约用 16s 处理完；推理慢于实时时以实际速度运行（只快不慢）。
- 图表/统计按 `this_sec != last_sec`（1Hz）上报 `sample`；实时缩略图按 `THUMB_FPS≈4` 写盘，互不阻塞。

---

## 6. 结果呈现（GUI 侧 `VsResultPanel`）

### 6.1 布局
- 顶部小标题（`VIDEO_STATS_TITLE`）。
- 滚动区（`QScrollArea`）内纵向排列**分组表**，每一张表 = 标题 + `pyqtgraph.PlotWidget` 方波图 + 一行 `闪烁 N 次 ｜ 时长 T s` 统计。
- 无检测结果时显示占位文案，不显示空白图。

### 6.2 系列判定（仅标题，不参与过滤）
- 从当前帧检测到的 LED 基础类前缀（`FP` / `A` / 其他）按多数**自动判定系列**，仅在标题标注（`VIDEO_SERIES_TITLE_TEMPLATE`）。
- **所有信号灯（含 pwr）一律纳入统计**，不按系列丢弃。

### 6.3 按统一位置分组多表
- 把该通道信号灯按**槽位**（LED 名末位 `_N`）分组；**同一槽位**的 LED（如 `pwr0 / vpl0`）编排在**同一张表**内相邻（满足"统一分布位置"）。
- 最多 `MAX_TABLES = 4` 张表；组表按槽位数值排序，显示稳定。
- 每张表 Y 轴 = 组内 LED 位点行，X 轴 = 检测时间(s)；亮(H)/灭(L) 以**方波折线**（`stepMode="left"`）表达。
- `setYRange` 正确含顶部行 inset，**顶部那行（可能是 pwr）无需缩放即可见**。

### 6.4 每表统计
- `tb["flashes"] = sum(flashes.get(led,0) for led in tb["leds"])` —— 组内**累计闪烁求和**。
- 表下方：`闪烁 {flashes} 次 ｜ 时长 {elapsed} s`。

### 6.5 关键配置（`app/core/tokens.py::Sizing` / `app/core/labels.py`）
| 用途 | token / label |
|---|---|
| 刷新间隔 | `VIDEO_REFRESH_MS = 300` |
| 每表高度 | `VIDEO_CHART_BLOCK_H = 130` |
| 每行高 | `VIDEO_WAVE_LANE_H = 56` |
| 亮/灭行内位置 | `VIDEO_WAVE_HIGH_INSET = 0.80` / `VIDEO_WAVE_LOW_INSET = 0.20` |
| 波形配色 | `VIDEO_WAVE_COLORS`（调色板） |
| 预览最大尺寸 | `VIDEO_PREVIEW_MAX_W = 520` / `VIDEO_PREVIEW_MAX_H = 360` |
| 文案 | `VIDEO_SERIES_TITLE_TEMPLATE`、`VIDEO_CH_TABLE_TITLE_TEMPLATE`、`VIDEO_SERIES_SUMMARY_TEMPLATE`、`VIDEO_STATS_NONE` 等 |

---

## 7. 多视频流并发与性能优化

### 7.1 并发模型：帧批处理调度
worker 不再是"每 job 一个线程 + 全局锁串行推理"，而是**单一调度线程**（`scheduler_loop → _tick`）：
- 每轮把各活动流的"到点帧"打包成 batch，`detect_batch` 一次前向 YOLO。
- `decode_box` 是 batch 感知的、一次完成；`non_max_suppression` 对**每路**用其自身 `image_shape` 逐路执行（NMS 内部 image_shape 是单一值，无法跨分辨率 batch 生效）。
- 每流按自身 `next_t` 独立节流，互不拖慢。
- H/L 分类跨流聚合：`classify_batch` 把多路 ROI 合成一次 TinyConv 前向，摊薄小 batch 启动开销。
- **读帧与调度解耦**：每流独立后台读帧线程把 `cap.read()` 预取进有界缓冲（`READ_BUF_SIZE=2`），调度线程取帧不阻塞——为将来 RTSP/网络流准备。
- 并发上限：`MAX_CONCURRENT_STREAMS`（worker.py，默认 `2`）。到达上限后新的 `detect` 会被拒绝并返回 `error` 事件（"并发检测已达上限…"）。

### 7.2 其它性能优化（已落地）
- **FP16 autocast**：`detect` / `detect_batch` / `classify` 在 CUDA 下用 `torch.amp.autocast(float16)` 包裹前向，输出递归回 FP32 解码，保 NMS 精度。
- **批量预处理**：`_preprocess_batch` 在 CPU 上把整批帧构造成一个连续 `[B,3,H,W] uint8` 数组，一次性 `to(device, non_blocking)`，在 GPU 侧 `/255` 归一化——替代逐帧 `cvtColor/resize/.to` 的多份拷贝。
- **cv2 letterbox**：以 cv2 resize + 灰边填充取代 PIL `Image.new`，省每帧 CPU 开销。
- **缩略图降频**：`THUMB_FPS≈4`，按帧间隔写盘而非逐帧，降低磁盘 I/O（GUI 300ms 刷新足够）。

### 7.3 实测吞吐与并发上限（RTX 5060 Ti / 8GB / 6核12线程，512×512 输入 FP16）
| batch(B) | 单轮累耗(ms) | 整批吞吐 | 均到每路 |
|---|---|---|---|
| 1 | 11.1 | 90 帧/s | 90 帧/s |
| 2 | 15.9 | 63 帧/s | **31 帧/s** |
| 4 | 24.0 | 42 帧/s | 10 帧/s |

- 测的是随机噪声帧（NMS 最坏情况），真实画面目标更少、NMS 更省，实测会更快。
- **瓶颈是 GPU 计算吞吐，不是显存**：8GB 显存跑 B=4 富余，但均到每路只有 ~10 帧/s，无法维持 30fps 实时。
- **结论**：默认 `MAX_CONCURRENT_STREAMS=2` 恰能扛 30fps 实时（B=2 → 31帧/s）；B=3 时若视频 ≤25fps 可尝试；B=4 只能跑 ≤10fps 的低帧率视频。
- 若需更高并发（>3 路 30fps），应从**降低输入分辨率**（512→384/320，需验证 LED 小目标召回）或 **TensorRT/`torch.compile`** 入手，而非单纯放宽并发上限。
- 显存估算沿用 §7.3 旧表：2 路 `~2–3GB` 舒适，4 路 `~4–6GB` 偏紧。<br>CPU：读帧/预处理随路数并行，建议 ≥8 逻辑核；RAM <2GB/路。

### 7.4 54 路静默集中监控（monitor / silent）
交互式逐帧检测受单线程后处理限制只适合 ≤4 路 **点来看**。若只是**后台静默监控**（不看画面、看 LED 亮灭/闪烁聚合），可一次跑最多 **54 路**，每路默认 **4fps**：

- **命令协议**（独立于交互 `detect`，与 `snapshot` 轮询配套）：
  ```
  {"cmd":"monitor", "fps":4.0, "jobs":[{"job":1,"video":"a.mp4"}, ...]}   # ≤54 路
  {"cmd":"snapshot"}      # 返回聚合快照
  {"cmd":"monitor_stop"}
  ```
  事件：`monitor_start`（count/fps/input）→ 轮询间 `snapshot`（每路：job/w/h/fps/frame/total/elapsed/flashes/states/status）→ `monitor_finished`。
- **为何能到 54 路**：测得的瓶颈是**单线程 Python 后处理（NMS 等，占 70%~90%）而非 GPU**。静态监视用
  - `DetectionEngine(input_shape=(320,320))` 低输入；
  - `detect_batch_parallel`：一次 GPU batch 前向（`_decode_batch`），NMS 按图丢进 `ThreadPoolExecutor`（`MONITOR_WORKERS≈12`）并行；
  - 无预览/缩略图/逐帧上报，只在内存聚合。
- **每路节流**：`period=1/fps` 独立推进；`FLASH_DEBOUNCE_FRAMES` 按实际检测帧率折算（约 0.3s OFF）；`_area` 类除功率灯 `*_PWR_area` 外不纳入统计（与交互一致）。
- **GUI 集成**：`VideoOverviewPage` 新增"选择视频…/开始静默监控/停止监控"，选 ≤54 视频 → 按所选顺序映射到位点 `CH-01..CH-54`，QTimer（`MONITOR_POLL_MS=1000`）轮询 `snapshot`，在 9×8 网格单元显示 `闪 {n}` / `✓` / `✗` 聚合。
- **静默+点开看实时**：监控进行中**双击某一正在被监控的位点** → `open_stream_requested(cid, 该路视频路径)` → 实时页 `set_channel(cid, path)` **自动载入并直启** 30fps 逐帧检测（复用现有交互页，无需重新导入）；其余 53 路静默继续后台记录。交互 `detect`（job=cid，写 `cell_{cid}.jpg`）与 `monitor`（独立 `_mon`）互不冲突。
- **容量**：54 路 × 4fps = 216 帧/s 总检测率；GPU 前向富余 2 个量级，并行后处理可摊平，实测（§7.3）足够。要更高可降 320 → 256 或调 `fps`。

---

## 8. 工程约束（本模块必须遵守）

1. **GUI 进程不 import torch**：`app/ui/*` 只通过 `VisionWorkerManager` 与 worker 进程 JSON 通信；`ml/vision/engine.py` 由 worker 进程引入。
2. **依赖方向**：所有检测/模型逻辑在 `ml/`；`app/ui` 只编排调用。
3. **硬编码禁令**：`app/ui/` 与 `app/widgets/` 内的用户可见文本一律 `labels.X`，尺寸/颜色一律 `tokens.X`（见 ARCHITECTURE.md §5）。
4. **QProcess 信号驱动 I/O**：用 `readyReadStandardOutput` / `finished` 信号，`MergedChannels` 合并 stderr→stdout 防死锁；注入 `PYTHONIOENCODING=utf-8`、`PYTHONUNBUFFERED=1`。
5. **worker 全局单例**：`get_vision_worker()` 返回应用级唯一实例，进程只启动一次；应用退出由 `HomePage` 统一 `shutdown()`。
6. **视频预览 QLabel**：`setSizePolicy(Ignored, Ignored)` 防布局抖动；预览按输入分辨率等比缩放、居中，不撑大窗口。

---

## 9. 验证方式

```powershell
# 1) 语法编译（worker 属 ml/，单独编译）
& E:\MiniConda\envs\Aging\python.exe -m py_compile ml\vision\worker.py ml\vision\engine.py

# 2) 启动应用
& E:\MiniConda\envs\Aging\python.exe d:\Aging\Main.py

# 3) 手动验证流程
#    → 视频 总览页 → 双击某位点 → 导入视频 → 开始
#    预期：worker 首启时打印 "vision worker ready: cuda"；
#    左侧预览随视频真实速度推进；右侧按槽位分组方波图 + 闪烁/时长统计。
```

---

## 10. 文件清单

| 文件 | 角色 |
|---|---|
| `app/ui/pages/video_page.py` | 视频检测·总览页（位点标记网格 + 双击路由 + 54 路静默监控选择/启动/轮询聚合） |
| `app/ui/pages/video_stream_page.py` | 单通道视频流检测页 + `VsResultPanel` 结果面板 |
| `app/ui/vision_worker.py` | 全局单例 worker 编排（QProcess 启动/收发/关闭） |
| `ml/vision/worker.py` | 常驻检测服务（帧批处理调度器 + 去抖闪烁统计 + 多流并发上限 + 54 路静默集中监控 monitor/snapshot） |
| `ml/vision/engine.py` | 统一检测引擎（YOLO `detect`/`detect_batch`/`detect_batch_parallel` + TinyConv H/L 分类 + 背景判定 + FP16 + 批量预处理） |
| `ml/deploy/` | 统一部署产物：`yolo_best_deploy.pt` / `tinyconv_best.pth` / `label_merged.txt` |
| `app/core/tokens.py` | `VIDEO_*` 尺寸/颜色 DesignTokens |
| `app/core/labels.py` | `VIDEO_*` 用户可见文案 |
| `app/ui/home_page.py` | 页面路由 + 应用退出时统一关闭 worker |

---

*文档最后更新：2026-08-24 — 视频流检测模块（两页 UI + 常驻 worker + 逐帧真实速度 + 去抖闪烁统计 + 槽位分组方波图）。*