# ESP32-CAM 部署说明

## 架构说明

```
┌─────────────────┐    WiFi (热点 QH)    ┌──────────────────┐
│   ESP32-CAM     │ ───────────────────> │        PC        │
│  (图像采集+图传) │   HTTP MJPEG 流      │  (YOLO 推理+显示) │
│  esp32cam_stream│   http://IP/stream    │  pc_yolo_detect  │
└─────────────────┘                       └──────────────────┘
```

**为什么 ESP32-CAM 不直接跑 YOLO?**

ESP32-CAM 硬件 (Xtensa LX6 双核 240MHz, SRAM 520KB, PSRAM 4MB) 无法运行当前 YOLOv8 模型
(权重 2-4MB, 推理需数 MB 内存, 单帧推理需数十秒)。因此采用"ESP32-CAM 采集+图传, PC 本地推理"
的方案。"离线"指不依赖云端/外网, YOLO 推理在 PC 本地完成, 无网络延迟依赖。

## 文件清单

| 文件 | 说明 |
|---|---|
| `esp32cam_stream/esp32cam_stream.ino` | ESP32-CAM 基础固件 (WiFi+摄像头+MJPEG 流服务器，用于 PC 端 YOLO 推理) |
| `esp32cam_recorder/esp32cam_recorder.ino` | ESP32-CAM 录像固件 (手机端浏览器录制视频，无需 SD 卡，用于采集标注数据) |
| `pc_yolo_detect.py` | PC 端 YOLO 推理脚本 (拉流+检测+显示) |

## 部署步骤

### 1. ESP32-CAM 烧录（通用）

**硬件**: ESP32-CAM (AI-Thinker 模块, OV2640/OV3660 摄像头) + USB-TTL 串口模块

**接线** (USB-TTL ↔ ESP32-CAM):
```
USB-TTL 5V  -> ESP32-CAM 5V
USB-TTL GND -> ESP32-CAM GND
USB-TTL TX  -> ESP32-CAM U0R (RX)
USB-TTL RX  -> ESP32-CAM U0T (TX)
```
烧录时需将 IO0 接 GND (进入下载模式), 烧录完毕断开 IO0 接地复位运行。

**Arduino IDE 配置**:
1. 安装 ESP32 板支持包 (boards manager 搜索 `esp32`, 安装 `ESP32 by Espressif Systems`)
2. 开发板选择: `AI Thinker ESP32-CAM`
3. PSRAM: `Enabled`
4. 端口选择对应 COM 口, 点击上传

### 2. 两种固件选择

#### 方案 A: 视频流采集 + PC 端 YOLO 推理（生产部署）

烧录 `esp32cam_stream.ino`，用于 PC 端拉流做实时 LED 检测。

**PC 端运行**:
```powershell
python detect\pc_yolo_detect.py --url http://<ESP_IP>/stream
```

#### 方案 B: 手机端录制视频 + 采集标注数据

烧录 `esp32cam_recorder.ino`，手机浏览器访问 ESP32-CAM IP 地址，
点击"开始录制"即可在浏览器端录制视频，停止后自动下载到手机。

**用途**: 采集现场视频用于后期抽帧、标注、扩充数据集。

**录制格式**: 优先 MP4 (手机支持时)，降级为 WebM。

**抽帧命令** (PC 端):
```powershell
# MP4 格式
ffmpeg -i recording.mp4 -q:v 2 frame_%04d.jpg

# WebM 格式
ffmpeg -i recording.webm -q:v 2 frame_%04d.jpg
```

## 检测类别与颜色

| 类别 | 含义 | 框颜色 |
|---|---|---|
| SIG_area | 信号区 | 绿 |
| PWR_area | 电源区 | 橙 |
| VPL_L | VPL 灯灭 | 红 |
| VPL_H | VPL 灯亮 | 浅红 |
| CPL_L | CPL 灯灭 | 蓝 |
| PWR_H | PWR 灯亮 | 黄 |
| PWR_L | PWR 灯灭 | 棕 |

画面右上角显示当前帧 LED 亮/灭统计 (ON/OFF 计数, area 类不计入)。

## 常见问题

**Q: ESP32-CAM 串口无 IP 输出?**
- 检查热点 QH 是否开启, 密码是否为 123456789
- 检查 ESP32-CAM 天线是否接好
- 信号弱时尝试靠近手机

**Q: PC 连不上 MJPEG 流?**
- 确认 PC 与 ESP32-CAM 在同一热点下
- 浏览器直接访问 `http://<IP>/` 看状态页是否正常
- 防火墙拦截时, 放行 Python 或 80 端口

**Q: 画面卡顿/帧率低?**
- ESP32-CAM 端降低分辨率: 改 `FRAMESIZE_SVGA` 为 `FRAMESIZE_VGA` 或 `FRAMESIZE_QVGA`
- 降低 JPEG 画质: `jpeg_quality` 调大 (如 20)
- 网络带宽不足时增大 `delay()` 值

**Q: 检测框位置偏移?**
- ESP32-CAM 摄像头视角与训练数据不同时, 需补充标注重训
- 用录制固件采集现场视频, 抽帧标注后扩充数据集

## 完全离线方案 (备选)

若必须完全不依赖 PC, 可改用"固定插槽+HSV 阈值"方案:
- ESP32-CAM 用预设的 LED 插槽坐标
- HSV V 通道 95 分位判定亮灭
- 不依赖 YOLO, 真正离线, 可达 10-15fps
- 该方案需另写 ESP32-CAM 端 HSV 判定代码, 当前未实现