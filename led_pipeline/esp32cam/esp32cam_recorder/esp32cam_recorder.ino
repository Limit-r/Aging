/*
 * ESP32-CAM 无线录像机（手机端录制）
 * ==================================
 * 功能:
 *   1. 连接手机热点 QH / 123456789
 *   2. 实时 MJPEG 视频流预览
 *   3. 点击"开始录制"→ 手机浏览器用 Canvas 录制视频流
 *   4. 点击"停止录制"→ 视频直接下载到手机（无需 SD 卡）
 *
 * 硬件: AI-Thinker ESP32-CAM 模块
 * 使用: 浏览器访问 http://esp32-ip
 */

#include "esp_camera.h"
#include <WiFi.h>
#include <WebServer.h>
#include "soc/soc.h"
#include "soc/rtc_cntl_reg.h"

// ========== WiFi 配置 ==========
const char* ssid     = "QH";
const char* password = "123456789";

// ========== AI-Thinker ESP32-CAM 引脚 ==========
#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27
#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22

// ========== 全局变量 ==========
WebServer server(80);

// ========== 摄像头初始化（支持 OV2640 / OV3660）==========
void initCamera() {
  struct CamTrial {
    framesize_t frameSize;
    pixformat_t pixelFormat;
    int xclkFreq;
    int fbCount;
    int jpegQuality;
    const char* label;
  };

  CamTrial trials[] = {
    { FRAMESIZE_VGA,  PIXFORMAT_JPEG, 20000000, 2, 12, "VGA/JPEG/fb2" },
    { FRAMESIZE_VGA,  PIXFORMAT_JPEG, 20000000, 1, 12, "VGA/JPEG/fb1" },
    { FRAMESIZE_SVGA, PIXFORMAT_JPEG, 20000000, 1, 12, "SVGA/JPEG/fb1" },
    { FRAMESIZE_VGA,  PIXFORMAT_JPEG, 10000000, 1, 15, "VGA/JPEG/10M" },
    { FRAMESIZE_VGA,  PIXFORMAT_GRAYSCALE, 20000000, 1, 0, "VGA/GRAY/fb1" },
  };

  esp_err_t err = ESP_FAIL;
  int trialIdx = 0;

  for (int i = 0; i < 5; i++) {
    camera_config_t config;
    config.ledc_channel = LEDC_CHANNEL_0;
    config.ledc_timer   = LEDC_TIMER_0;
    config.pin_d0       = Y2_GPIO_NUM;
    config.pin_d1       = Y3_GPIO_NUM;
    config.pin_d2       = Y4_GPIO_NUM;
    config.pin_d3       = Y5_GPIO_NUM;
    config.pin_d4       = Y6_GPIO_NUM;
    config.pin_d5       = Y7_GPIO_NUM;
    config.pin_d6       = Y8_GPIO_NUM;
    config.pin_d7       = Y9_GPIO_NUM;
    config.pin_xclk     = XCLK_GPIO_NUM;
    config.pin_pclk     = PCLK_GPIO_NUM;
    config.pin_vsync    = VSYNC_GPIO_NUM;
    config.pin_href     = HREF_GPIO_NUM;
    config.pin_sscb_sda = SIOD_GPIO_NUM;
    config.pin_sscb_scl = SIOC_GPIO_NUM;
    config.pin_pwdn     = PWDN_GPIO_NUM;
    config.pin_reset    = RESET_GPIO_NUM;
    config.xclk_freq_hz = trials[i].xclkFreq;
    config.pixel_format = trials[i].pixelFormat;
    config.frame_size   = trials[i].frameSize;
    config.jpeg_quality = trials[i].jpegQuality;
    config.fb_count     = trials[i].fbCount;

    Serial.printf("[CAM] 尝试方案 %d: %s\n", i + 1, trials[i].label);
    err = esp_camera_init(&config);
    if (err == ESP_OK) {
      trialIdx = i;
      Serial.printf("[CAM] 方案 %d 成功: %s\n", i + 1, trials[i].label);
      break;
    }
    Serial.printf("[CAM] 方案 %d 失败 (0x%x)\n", i + 1, err);
    delay(100);
  }

  if (err != ESP_OK) {
    Serial.println("[ERR] 所有摄像头初始化方案均失败, 进入死循环");
    while (1) { delay(1000); }
  }

  sensor_t *s = esp_camera_sensor_get();
  if (trials[trialIdx].pixelFormat == PIXFORMAT_GRAYSCALE) {
    s->set_framesize(s, FRAMESIZE_QQVGA);
  } else {
    s->set_framesize(s, trials[trialIdx].frameSize);
  }
  s->set_quality(s, trials[trialIdx].jpegQuality);
  s->set_brightness(s, 0);
  s->set_contrast(s, 0);
  s->set_saturation(s, 0);
  Serial.println("[CAM] 摄像头初始化成功");
}

// ========== MJPEG 视频流（非阻塞版）==========
volatile bool inStream = false;

void handleStream() {
  if (inStream) return;
  inStream = true;

  WiFiClient client = server.client();
  client.setTimeout(3);

  String response = "HTTP/1.1 200 OK\r\n";
  response += "Content-Type: multipart/x-mixed-replace; boundary=frame\r\n";
  response += "Access-Control-Allow-Origin: *\r\n";
  response += "Cache-Control: no-cache\r\n";
  response += "Connection: close\r\n\r\n";
  server.sendContent(response);

  unsigned long lastClientHandle = 0;

  while (client.connected()) {
    unsigned long now = millis();
    if (now - lastClientHandle > 50) {
      server.handleClient();
      lastClientHandle = now;
    }

    camera_fb_t *fb = esp_camera_fb_get();
    if (!fb) {
      delay(1);
      continue;
    }

    String head = "--frame\r\n";
    head += "Content-Type: image/jpeg\r\n";
    head += "Content-Length: " + String(fb->len) + "\r\n\r\n";
    client.write((uint8_t*)head.c_str(), head.length());
    client.write(fb->buf, fb->len);
    client.write("\r\n", 2);

    esp_camera_fb_return(fb);
  }

  inStream = false;
}

// ========== 主页 HTML ==========
const char INDEX_HTML[] PROGMEM = R"rawliteral(
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>ESP32-CAM 录像机</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, 'Microsoft YaHei', sans-serif; background: #0f0f23; color: #fff; text-align: center; padding: 10px; }
h1 { font-size: 20px; color: #e94560; margin: 10px 0; }
#stream { width: 100%; max-width: 640px; border-radius: 8px; border: 2px solid #e94560; background: #000; }
.toolbar { margin: 12px 0; }
.btn { padding: 14px 36px; font-size: 18px; border: none; border-radius: 30px; cursor: pointer; font-weight: bold; transition: all 0.3s; }
.btn-record { background: #e94560; color: #fff; }
.btn-record.recording { background: #ff6b6b; animation: pulse 1.2s ease-in-out infinite; }
.btn-record:active { transform: scale(0.95); }
.btn-record:disabled { background: #555; cursor: not-allowed; }
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.5; } }
#status { margin: 8px; font-size: 14px; color: #aaa; }
#info { margin: 4px; font-size: 12px; color: #666; }
</style>
</head>
<body>
<h1>ESP32-CAM 录像机</h1>
<img id="stream" src="/stream" crossorigin="anonymous" />
<div class="toolbar">
  <button class="btn btn-record" id="recordBtn">开始录制</button>
</div>
<div id="status">就绪 — 点击"开始录制"录制 MP4 视频（直接保存到手机，可抽帧做数据集）</div>
<div id="info"></div>

<script>
let mediaRecorder = null;
let recordedChunks = [];
let animFrameId = null;
let recording = false;

const canvas = document.createElement('canvas');
const ctx = canvas.getContext('2d');
const img = document.getElementById('stream');
const btn = document.getElementById('recordBtn');
const st = document.getElementById('status');
const info = document.getElementById('info');

// 检测支持的视频格式（优先 MP4，方便后期抽帧做数据集）
function getSupportedMimeType() {
  const types = [
    'video/mp4',
    'video/mp4;codecs=h264',
    'video/mp4;codecs=avc1',
    'video/webm;codecs=vp9',
    'video/webm;codecs=vp8',
    'video/webm'
  ];
  for (const t of types) {
    if (MediaRecorder.isTypeSupported(t)) return t;
  }
  return 'video/webm';
}

btn.addEventListener('click', () => {
  if (recording) {
    stopRecording();
  } else {
    startRecording();
  }
});

function startRecording() {
  // 等待图片加载完成
  const w = img.naturalWidth || 640;
  const h = img.naturalHeight || 480;
  canvas.width = w;
  canvas.height = h;

  recordedChunks = [];
  const mimeType = getSupportedMimeType();
  info.textContent = '格式: ' + mimeType;

  // 创建 Canvas 流
  const stream = canvas.captureStream(10);
  mediaRecorder = new MediaRecorder(stream, { mimeType });

  mediaRecorder.ondataavailable = (e) => {
    if (e.data && e.data.size > 0) {
      recordedChunks.push(e.data);
    }
  };

  mediaRecorder.onstop = () => {
    if (recordedChunks.length === 0) {
      st.textContent = '录制失败：未采集到数据';
      recording = false;
      btn.textContent = '开始录制';
      btn.classList.remove('recording');
      btn.disabled = false;
      return;
    }

    const blob = new Blob(recordedChunks, { type: mimeType });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    const now = new Date();
    const ts = now.getFullYear() + ''
      + String(now.getMonth()+1).padStart(2,'0')
      + String(now.getDate()).padStart(2,'0') + '_'
      + String(now.getHours()).padStart(2,'0')
      + String(now.getMinutes()).padStart(2,'0')
      + String(now.getSeconds()).padStart(2,'0');
    const ext = mimeType.includes('mp4') ? 'mp4' : 'webm';
    a.download = 'ESP32_' + ts + '.' + ext;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 10000);

    const sizeKB = (blob.size / 1024).toFixed(1);
    st.textContent = '录制完成！已保存: ' + a.download + ' (' + sizeKB + ' KB' + ', ' + ext + ')';
    if (ext === 'webm') {
      info.textContent = '提示: 手机不支持MP4录制，已降级为WebM。可用 ffmpeg -i ' + a.download + ' -q:v 2 frame_%04d.jpg 抽帧';
    } else {
      info.textContent = 'MP4格式，可直接用 ffmpeg/OpenCV 抽帧制作数据集';
    }
    recording = false;
    btn.textContent = '开始录制';
    btn.classList.remove('recording');
    btn.disabled = false;
    recordedChunks = [];
  };

  mediaRecorder.onerror = () => {
    st.textContent = '录制出错，请重试';
    recording = false;
    btn.textContent = '开始录制';
    btn.classList.remove('recording');
    btn.disabled = false;
  };

  // 每 1 秒收集一次数据
  mediaRecorder.start(1000);
  recording = true;
  btn.textContent = '停止录制';
  btn.classList.add('recording');
  st.textContent = '正在录制... (Canvas ' + w + 'x' + h + ')';

  // 开始从 img 抓帧到 canvas
  function captureFrame() {
    if (!recording) return;
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    animFrameId = requestAnimationFrame(captureFrame);
  }
  captureFrame();
}

function stopRecording() {
  if (mediaRecorder && mediaRecorder.state === 'recording') {
    btn.disabled = true;
    btn.textContent = '打包中...';
    st.textContent = '正在生成视频文件...';
    mediaRecorder.stop();
    if (animFrameId) {
      cancelAnimationFrame(animFrameId);
      animFrameId = null;
    }
  }
}
</script>
</body>
</html>
)rawliteral";

void handleRoot() {
  server.send(200, "text/html; charset=utf-8", INDEX_HTML);
}

// ========== 设置 ==========
void setup() {
  WRITE_PERI_REG(RTC_CNTL_BROWN_OUT_REG, 0);
  Serial.begin(115200);
  Serial.println("\nESP32-CAM 录像机 (手机端录制)");

  initCamera();

  // 连接 WiFi
  WiFi.begin(ssid, password);
  Serial.print("连接 WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi 已连接");
  Serial.print("IP 地址: http://");
  Serial.println(WiFi.localIP());

  // 注册路由
  server.on("/",       handleRoot);
  server.on("/stream", handleStream);

  server.begin();
  Serial.println("Web 服务器已启动");
  Serial.println("手机浏览器访问 IP 地址即可预览和录制");
}

void loop() {
  server.handleClient();
}