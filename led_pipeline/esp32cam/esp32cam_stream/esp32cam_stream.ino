/*
 * ESP32-CAM LED 检测图传节点
 *
 * 功能:
 *   1. 连接手机热点 (SSID: QH, PASSWORD: 123456789)
 *   2. 初始化 AI-Thinker 摄像头
 *   3. 启动 HTTP MJPEG 流服务器, 供 PC 端拉流跑 YOLO 推理
 *
 * 硬件: ESP32-CAM (AI-Thinker 模块, OV2640 摄像头)
 * 烧录: Arduino IDE, 开发板选 "AI Thinker ESP32-CAM", PSRAM 开启
 *
 * 接口:
 *   http://<ESP_IP>:80/stream   —— MJPEG 视频流 (浏览器可直接打开)
 *   http://<ESP_IP>:80/         —— 简单状态页 (显示 IP/帧率)
 *
 * 串口波特率 115200, 上电后会打印分配到的 IP 地址。
 */
#include "esp_camera.h"
#include <WiFi.h>

// ==================== 用户配置 ====================
const char* WIFI_SSID     = "QH";
const char* WIFI_PASSWORD = "123456789";
// ==================== 用户配置结束 =================

// AI-Thinker ESP32-CAM 引脚定义
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

// 全局状态
WiFiServer server(80);
String     clientIP = "未连接";
uint32_t   frameCount = 0;
uint32_t   lastFpsTs = 0;
uint32_t   fps = 0;

// 当前 JPEG 帧缓冲 (双缓冲, 避免采集与发送冲突)
camera_fb_t* fbCurrent = nullptr;
portMUX_TYPE fbLock = portMUX_INITIALIZER_UNLOCKED;

// ==================== 摄像头初始化 ====================
bool setupCamera() {
  camera_config_t config;
  config.ledc_channel  = LEDC_CHANNEL_0;
  config.ledc_timer    = LEDC_TIMER_0;
  config.pin_d0        = Y2_GPIO_NUM;
  config.pin_d1        = Y3_GPIO_NUM;
  config.pin_d2        = Y4_GPIO_NUM;
  config.pin_d3        = Y5_GPIO_NUM;
  config.pin_d4        = Y6_GPIO_NUM;
  config.pin_d5        = Y7_GPIO_NUM;
  config.pin_d6        = Y8_GPIO_NUM;
  config.pin_d7        = Y9_GPIO_NUM;
  config.pin_xclk      = XCLK_GPIO_NUM;
  config.pin_pclk      = PCLK_GPIO_NUM;
  config.pin_vsync     = VSYNC_GPIO_NUM;
  config.pin_href      = HREF_GPIO_NUM;
  config.pin_sccb_sda  = SIOD_GPIO_NUM;
  config.pin_sccb_scl  = SIOC_GPIO_NUM;
  config.pin_pwdn      = PWDN_GPIO_NUM;
  config.pin_reset     = RESET_GPIO_NUM;
  config.xclk_freq_hz  = 20000000;
  // 帧格式: JPEG, 分辨率 SVGA(800x600) 兼顾画质与带宽
  // 若带宽不足可改 FRAMESIZE_QVGA(320x240) 或 CIF(400x296)
  config.frame_size    = FRAMESIZE_SVGA;
  config.pixel_format  = PIXFORMAT_JPEG;
  config.grab_mode     = CAMERA_GRAB_LATEST;
  config.fb_count      = 2;
  config.jpeg_quality  = 12;   // 0-63, 越小画质越高

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("[ERR] 摄像头初始化失败: 0x%x\n", err);
    return false;
  }

  // 默认参数微调 (亮度/对比度/饱和度, 可按现场调整)
  sensor_t* s = esp_camera_sensor_get();
  if (s) {
    s->set_brightness(s, 0);    // -2..2
    s->set_contrast(s, 0);      // -2..2
    s->set_saturation(s, 0);    // -2..2
    s->set_whitebal(s, 1);      // AWB 开
    s->set_ae_level(s, 0);      // 自动曝光
    s->set_aec_value(s, 300);   // 曝光上限
  }
  return true;
}

// ==================== WiFi 连接 ====================
bool connectWiFi() {
  Serial.printf("[INFO] 正在连接 WiFi: %s\n", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);          // 关闭省电, 提高吞吐稳定性
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  uint32_t t0 = millis();
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
    if (millis() - t0 > 30000) {  // 30s 超时
      Serial.println("\n[ERR] WiFi 连接超时, 请检查热点是否开启");
      return false;
    }
  }
  Serial.println("");
  Serial.println("[OK] WiFi 已连接");
  Serial.print("[INFO] IP 地址: ");
  Serial.println(WiFi.localIP());
  Serial.print("[INFO] 信号强度(RSSI): ");
  Serial.print(WiFi.RSSI());
  Serial.println(" dBm");
  return true;
}

// ==================== HTTP 处理 ====================

// MJPEG 流响应 —— 浏览器/PC拉流的核心接口
void handleStream(WiFiClient& client) {
  client.println("HTTP/1.1 200 OK");
  client.println("Content-Type: multipart/x-mixed-replace; boundary=frame");
  client.println("Connection: close");
  client.println();

  uint32_t streamStart = millis();
  uint32_t streamFrames = 0;

  while (client.connected()) {
    camera_fb_t* fb = esp_camera_fb_get();
    if (!fb) {
      Serial.println("[WARN] 取帧失败, 重试");
      delay(50);
      continue;
    }

    // 写一帧 JPEG
    client.printf("--frame\r\n");
    client.println("Content-Type: image/jpeg");
    client.printf("Content-Length: %u\r\n\r\n", fb->len);
    client.write(fb->buf, fb->len);
    client.println("\r\n");

    esp_camera_fb_return(fb);

    // 帧率统计
    streamFrames++;
    frameCount++;
    uint32_t now = millis();
    if (now - lastFpsTs >= 1000) {
      fps = streamFrames * 1000 / (now - lastFpsTs + 1);
      lastFpsTs = now;
      streamFrames = 0;
    }

    // 控制帧率 ~15fps, 避免占用过多带宽
    delay(30);
  }
  Serial.printf("[INFO] 流客户端断开, 累计发送 %u 帧, 耗时 %lu ms\n",
                frameCount, millis() - streamStart);
}

// 状态页 —— 浏览器访问根路径显示信息
void handleRoot(WiFiClient& client) {
  String html = String("HTTP/1.1 200 OK\r\n") +
    "Content-Type: text/html; charset=utf-8\r\n" +
    "Connection: close\r\n\r\n" +
    "<!DOCTYPE html><html><head><meta charset='utf-8'>" +
    "<title>ESP32-CAM LED 检测节点</title></head><body>" +
    "<h2>ESP32-CAM LED 检测图传节点</h2>" +
    "<p>WiFi: " + String(WIFI_SSID) + " (RSSI " + String(WiFi.RSSI()) + " dBm)</p>" +
    "<p>IP: " + WiFi.localIP().toString() + "</p>" +
    "<p>累计帧数: " + String(frameCount) + " | 当前 FPS: " + String(fps) + "</p>" +
    "<h3>视频流</h3>" +
    "<img src='/stream' style='width:640px;border:1px solid #ccc'><br>" +
    "<p>PC 端拉流地址: <code>http://" + WiFi.localIP().toString() + "/stream</code></p>" +
    "</body></html>\r\n";
  client.print(html);
}

// ==================== setup / loop ====================
void setup() {
  Serial.begin(115200);
  Serial.setDebugOutput(false);
  delay(500);
  Serial.println("\n========================");
  Serial.println("ESP32-CAM LED 检测图传节点");
  Serial.println("========================");

  // 关闭板载 LED (降低干扰, LED 在 GPIO4, 也可能是闪光灯 GPIO33)
  pinMode(4, OUTPUT);
  digitalWrite(4, LOW);

  if (!setupCamera()) {
    Serial.println("[ERR] 摄像头初始化失败, 进入死循环");
    while (true) { delay(1000); }
  }
  Serial.println("[OK] 摄像头初始化完成");

  if (!connectWiFi()) {
    Serial.println("[ERR] WiFi 连接失败, 5 秒后重启重试");
    delay(5000);
    ESP.restart();
  }

  server.begin();
  Serial.println("[OK] HTTP 服务器已启动 (端口 80)");
  Serial.println("========================");
  Serial.println("PC 端拉流命令:");
  Serial.printf("  python led_pipeline/esp32cam/pc_yolo_detect.py --url http://%s/stream\n",
                WiFi.localIP().toString().c_str());
  Serial.println("========================");
}

void loop() {
  WiFiClient client = server.available();
  if (!client) {
    delay(10);
    return;
  }
  clientIP = client.remoteIP().toString();
  Serial.printf("[INFO] 新连接: %s\n", clientIP.c_str());

  // 读 HTTP 请求第一行
  String req = client.readStringUntil('\n');
  client.readStringUntil('\n');  // 吃空行
  req.trim();
  Serial.printf("[INFO] 请求: %s\n", req.c_str());

  if (req.indexOf("GET /stream") >= 0) {
    handleStream(client);
  } else if (req.indexOf("GET / ") >= 0 || req.indexOf("GET /index") >= 0) {
    handleRoot(client);
  } else {
    // 其他路径返回 404
    client.println("HTTP/1.1 404 Not Found");
    client.println("Connection: close\r\n");
  }
  client.stop();
}
