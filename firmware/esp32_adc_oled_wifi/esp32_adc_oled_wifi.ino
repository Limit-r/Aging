/*
 * ESP32-WROOM 四路 ADC 检测 + OLED 显示 + WiFi 网页监控
 *
 * 功能：
 *   1. 四路 ADC 检测（GPIO14, 27, 26, 25）
 *   2. OLED 本地显示
 *   3. WiFi 连接手机热点，通过浏览器查看实时数据
 *
 * 引脚配置：
 *   - ADC 检测：GPIO14, GPIO27, GPIO26, GPIO25（ADC2 通道）
 *     ⚠ 使用 adc2_get_raw() 代替 analogRead() 与 WiFi 共享 ADC2 硬件
 *   - OLED I2C：SDA = GPIO22，SCL = GPIO21
 *
 * 使用方法：
 *   1. 修改下方 WIFI_SSID 和 WIFI_PASS 为手机热点名称和密码
 *   2. 上传代码到 ESP32
 *   3. 打开串口监视器（115200），查看分配到的 IP 地址
 *   4. 手机浏览器访问该 IP 地址即可查看实时数据
 *
 * 依赖库（Arduino IDE 库管理器安装）：
 *   - Adafruit GFX Library
 *   - Adafruit SSD1306
 *
 * OLED 型号：SSD1306 0.96" 128x64 I2C（地址一般为 0x3C）
 */

#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <WiFi.h>
#include <WebServer.h>

// ADC2 底层操作需要直接包含 ESP-IDF 驱动头文件
#include "driver/adc.h"

// ==================== WiFi 配置 ====================
// 修改为你的手机热点名称和密码
static const char *WIFI_SSID     = "QH";
static const char *WIFI_PASS     = "123456789";

// WiFi 连接超时（毫秒）
static const uint32_t WIFI_TIMEOUT_MS = 15000;

// ==================== 引脚与参数定义 ====================

// ADC 检测引脚（均为 ADC2 通道，使用 adc2_get_raw() 绕开 WiFi 冲突）
static const uint8_t ADC_PINS[]  = {14, 27, 26, 25};
static const uint8_t ADC_COUNT   = sizeof(ADC_PINS) / sizeof(ADC_PINS[0]);

// OLED I2C 引脚
static const uint8_t OLED_SDA    = 22;
static const uint8_t OLED_SCL    = 21;

// OLED 显示参数
static const uint16_t SCREEN_W   = 128;
static const uint16_t SCREEN_H   = 64;
static const uint8_t  OLED_ADDR  = 0x3C;

// ESP32 ADC 默认 12 位（0-4095），参考电压约 3.3V
static const float    ADC_VREF   = 3.3f;
static const uint16_t ADC_MAX    = 4095;

// ==================== ADC2 通道映射（WiFi 下需用底层 API） ====================

// GPIO 编号 → ADC2 内部通道号（ESP32 硬件定义值）
//   GPIO14=6, GPIO27=7, GPIO26=9, GPIO25=8
static const uint8_t ADC2_CH_MAP[] = {6, 7, 9, 8};

// ADC2 是否已初始化成功
static bool g_adc2_ready = false;

/**
 * 配置 ADC2 通道衰减（11dB，可测 0~3.6V）
 * 必须在 WiFi 连接之前调用，否则 ADC2 可能被 WiFi 驱动锁定
 */
static void configADC2() {
    bool allOk = true;
    for (uint8_t i = 0; i < ADC_COUNT; i++) {
        esp_err_t err = adc2_config_channel_atten(
            (adc2_channel_t)ADC2_CH_MAP[i], ADC_ATTEN_DB_11
        );
        if (err != ESP_OK) {
            Serial.printf("[ADC2] ch%d 配置失败 err=%d\n", ADC2_CH_MAP[i], err);
            allOk = false;
        } else {
            Serial.printf("[ADC2] ch%d (GPIO%d) 配置成功\n", ADC2_CH_MAP[i], ADC_PINS[i]);
        }
    }
    g_adc2_ready = allOk;
    Serial.printf("[ADC2] 初始化状态: %s\n", g_adc2_ready ? "OK" : "部分失败");
}

/**
 * 读取 ADC2 引脚（替代 analogRead，兼容 WiFi 运行）
 *
 * 原理：ESP32 ADC2 与 WiFi 共享硬件 SAR ADC。WiFi 驱动在 TX/RX 期间
 * 持有 ADC2 锁，但帧间隙会释放。本函数通过大量重试等待 WiFi 释放锁。
 *
 * 策略：
 *   1. 尝试 adc2_get_raw()，快速重试 50 次（每次 1ms）
 *   2. 若仍超时，慢速重试 200 次（每次 5ms），等待 WiFi 帧间隙
 *   3. 回退到 analogRead()（某些内核版本可用）
 *   4. 仍失败则返回上次有效值
 */
static uint16_t readADC2(uint8_t idx) {
    static uint16_t lastVal[ADC_COUNT] = {0};
    int raw = 0;

    // 阶段一：快速重试 50 次（1ms 间隔，适合短时 WiFi 空闲）
    for (int retry = 0; retry < 50; retry++) {
        esp_err_t err = adc2_get_raw(
            (adc2_channel_t)ADC2_CH_MAP[idx],
            ADC_WIDTH_BIT_12,
            &raw
        );
        if (err == ESP_OK && raw >= 0) {
            lastVal[idx] = (uint16_t)raw;
            return lastVal[idx];
        }
        delay(1);
    }

    // 阶段二：慢速重试 200 次（5ms 间隔，等待 WiFi 帧间隙释放 ADC2）
    for (int retry = 0; retry < 200; retry++) {
        esp_err_t err = adc2_get_raw(
            (adc2_channel_t)ADC2_CH_MAP[idx],
            ADC_WIDTH_BIT_12,
            &raw
        );
        if (err == ESP_OK && raw >= 0) {
            lastVal[idx] = (uint16_t)raw;
            return lastVal[idx];
        }
        delay(5);
    }

    // 阶段三：adc2_get_raw 始终超时，尝试 analogRead 回退
    int val = analogRead(ADC_PINS[idx]);
    if (val > 0) {
        lastVal[idx] = (uint16_t)val;
        return lastVal[idx];
    }

    // 全部失败，返回上次有效值
    return lastVal[idx];
}

// 采样与网页刷新间隔（毫秒）
static const uint32_t SAMPLE_INTERVAL_MS = 300;
static const uint32_t WEB_REFRESH_MS     = 300;

// ==================== 全局对象 ====================

Adafruit_SSD1306 display(SCREEN_W, SCREEN_H, &Wire, -1);
WebServer server(80);

// 全局数据缓存，供 Web 页面和 OLED 共用
static uint16_t g_values[ADC_COUNT] = {0};
static float    g_volts[ADC_COUNT]  = {0.0f};
static bool     g_wifi_connected    = false;
static char     g_ip_str[16]        = "0.0.0.0";

// ==================== HTML 页面（嵌入到程序闪存） ====================

static const char PAGE_HTML[] PROGMEM = R"rawliteral(
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
<title>ESP32 ADC 监控</title>
<style>
  *{margin:0;padding:0;box-sizing:border-box}
  body{
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
    background:#0f1923;color:#e0e0e0;min-height:100vh;padding:16px
  }
  .header{
    text-align:center;padding:16px 0 20px;
    border-bottom:1px solid #1e2d3d;margin-bottom:20px
  }
  .header h1{font-size:22px;font-weight:600;color:#00d4ff;letter-spacing:1px}
  .header .sub{font-size:13px;color:#8899aa;margin-top:6px}
  .header .sub .status-dot{
    display:inline-block;width:8px;height:8px;border-radius:50%;
    background:#00e676;margin-right:6px;vertical-align:middle
  }
  .status-bar{
    display:flex;justify-content:space-between;align-items:center;
    background:#1a2a3a;border-radius:10px;padding:10px 14px;margin-bottom:18px;
    font-size:13px;color:#aabbcc
  }
  .status-bar .ip{color:#00d4ff;font-weight:600}
  .status-bar .time{color:#8899aa}
  .grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
  .card{
    background:#1a2a3a;border-radius:12px;padding:16px;
    border:1px solid #253545;transition:border-color .3s
  }
  .card .pin-label{font-size:12px;color:#8899aa;margin-bottom:4px}
  .card .value-row{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:6px}
  .card .raw-value{font-size:28px;font-weight:700;font-variant-numeric:tabular-nums}
  .card .volt-value{font-size:16px;color:#00d4ff;font-weight:600}
  .card .bar-wrap{
    height:6px;background:#0d1a26;border-radius:3px;overflow:hidden;margin-top:8px
  }
  .card .bar-fill{
    height:100%;border-radius:3px;transition:width .3s ease,background .3s ease
  }
  .card.ch0 .raw-value{color:#ff5252}
  .card.ch0 .bar-fill{background:#ff5252}
  .card.ch1 .raw-value{color:#ffd740}
  .card.ch1 .bar-fill{background:#ffd740}
  .card.ch2 .raw-value{color:#69f0ae}
  .card.ch2 .bar-fill{background:#69f0ae}
  .card.ch3 .raw-value{color:#448aff}
  .card.ch3 .bar-fill{background:#448aff}
  .footer{text-align:center;font-size:11px;color:#556677;margin-top:20px;padding-top:16px;border-top:1px solid #1e2d3d}
  @media(max-width:400px){.grid{grid-template-columns:1fr}.header h1{font-size:19px}}
  .refresh-indicator{display:inline-block;width:12px;height:12px;border:2px solid #00d4ff;border-top-color:transparent;border-radius:50%;animation:spin .8s linear infinite;vertical-align:middle;margin-right:6px}
  @keyframes spin{to{transform:rotate(360deg)}}
</style>
</head>
<body>
<div class="header">
  <h1>⚡ ADC 实时监控</h1>
  <div class="sub"><span class="status-dot"></span>ESP32 四通道数据采集</div>
</div>

<div class="status-bar">
  <span><span class="refresh-indicator" id="refreshIcon"></span>实时更新中</span>
  <span class="ip" id="ipDisplay">--</span>
  <span class="time" id="timeDisplay">--:--:--</span>
</div>

<div class="grid" id="cardGrid">
  <div class="card ch0"><div class="pin-label">GPIO14</div><div class="value-row"><span class="raw-value" id="val0">--</span><span class="volt-value" id="volt0">-- V</span></div><div class="bar-wrap"><div class="bar-fill" id="bar0" style="width:0%"></div></div></div>
  <div class="card ch1"><div class="pin-label">GPIO27</div><div class="value-row"><span class="raw-value" id="val1">--</span><span class="volt-value" id="volt1">-- V</span></div><div class="bar-wrap"><div class="bar-fill" id="bar1" style="width:0%"></div></div></div>
  <div class="card ch2"><div class="pin-label">GPIO26</div><div class="value-row"><span class="raw-value" id="val2">--</span><span class="volt-value" id="volt2">-- V</span></div><div class="bar-wrap"><div class="bar-fill" id="bar2" style="width:0%"></div></div></div>
  <div class="card ch3"><div class="pin-label">GPIO25</div><div class="value-row"><span class="raw-value" id="val3">--</span><span class="volt-value" id="volt3">-- V</span></div><div class="bar-wrap"><div class="bar-fill" id="bar3" style="width:0%"></div></div></div>
</div>

<div class="footer">ESP32 ADC Monitor &middot; 数据每 300ms 刷新</div>

<script>
const CH_NAMES = ["GPIO14","GPIO27","GPIO26","GPIO25"];
function fmtTime(){
  const d=new Date();
  return d.getHours().toString().padStart(2,'0')+":"+
         d.getMinutes().toString().padStart(2,'0')+":"+
         d.getSeconds().toString().padStart(2,'0');
}
function updateDisplay(){
  fetch("/api/data").then(r=>r.json()).then(d=>{
    if(d.ip){document.getElementById("ipDisplay").textContent=d.ip}
    document.getElementById("timeDisplay").textContent=fmtTime();
    for(let i=0;i<4;i++){
      const v=d.values[i],vo=d.volts[i];
      const pct=(v/4095*100).toFixed(1);
      document.getElementById("val"+i).textContent=v;
      document.getElementById("volt"+i).textContent=vo.toFixed(3)+" V";
      document.getElementById("bar"+i).style.width=pct+"%";
    }
    document.getElementById("refreshIcon").style.borderTopColor="transparent";
  }).catch(()=>{
    document.getElementById("refreshIcon").style.borderTopColor="#ff5252";
  });
}
updateDisplay();
setInterval(updateDisplay,300);
</script>
</body>
</html>
)rawliteral";

// ==================== Web 路由处理 ====================

/** 根路径：返回 HTML 页面 */
static void handleRoot() {
  server.send_P(200, "text/html; charset=utf-8", PAGE_HTML);
}

/** /api/data：返回 JSON 格式的 ADC 数据 */
static void handleApiData() {
  String json = "{";
  json += "\"ip\":\"" + String(g_ip_str) + "\",";
  json += "\"values\":[";
  for (uint8_t i = 0; i < ADC_COUNT; i++) {
    if (i > 0) json += ",";
    json += String(g_values[i]);
  }
  json += "],\"volts\":[";
  for (uint8_t i = 0; i < ADC_COUNT; i++) {
    if (i > 0) json += ",";
    json += String(g_volts[i], 3);
  }
  json += "]}";
  server.send(200, "application/json; charset=utf-8", json);
}

/** 404 处理 */
static void handleNotFound() {
  server.send(404, "text/plain; charset=utf-8", "404 - 未找到");
}

// ==================== WiFi 连接 ====================

static void connectWiFi() {
  Serial.print(F("\n[WiFi] 正在连接热点: "));
  Serial.println(WIFI_SSID);

  display.clearDisplay();
  display.setCursor(0, 0);
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.println(F("WiFi Connecting..."));
  display.setCursor(0, 16);
  display.println(WIFI_SSID);
  display.display();

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);

  uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
    // 超时处理
    if (millis() - start > WIFI_TIMEOUT_MS) {
      Serial.println(F("\n[WiFi] 连接超时！请检查 SSID 和密码"));
      g_wifi_connected = false;
      return;
    }
  }

  g_wifi_connected = true;
  WiFi.setAutoReconnect(true);
  WiFi.persistent(true);

  IPAddress ip = WiFi.localIP();
  sprintf(g_ip_str, "%d.%d.%d.%d", ip[0], ip[1], ip[2], ip[3]);

  Serial.println(F("\n[WiFi] 连接成功！"));
  Serial.print(F("[WiFi] IP 地址: "));
  Serial.println(g_ip_str);
  Serial.println(F("[WiFi] 手机浏览器打开上述 IP 即可查看数据"));
}

// ==================== 初始化 ====================

void setup() {
  Serial.begin(115200);
  delay(200);

  // 初始化 I2C
  Wire.begin(OLED_SDA, OLED_SCL);

  // 初始化 OLED
  if (!display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR)) {
    Serial.println(F("[OLED] 未找到 SSD1306 屏，请检查接线与地址"));
    while (true) delay(1000);
  }

  // 启动画面
  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);
  display.setTextSize(1);
  display.setCursor(20, 0);
  display.println(F("ESP32 ADC OLED"));
  display.setCursor(10, 16);
  display.println(F("+WiFi Web Monitor"));
  display.setCursor(10, 40);
  display.println(F("Connecting WiFi..."));
  display.display();
  delay(500);

  // 先配置 ADC2，再连 WiFi（避免 WiFi 驱动锁定 ADC2 后配置失败）
  configADC2();

  // 连接 WiFi
  connectWiFi();

  // 配置 Web 路由
  server.on("/", handleRoot);
  server.on("/api/data", handleApiData);
  server.onNotFound(handleNotFound);
  server.begin();
  Serial.println(F("[Web] HTTP 服务器已启动"));

  // 显示启动完成
  display.clearDisplay();
  display.setCursor(0, 0);
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.println(F("ADC Monitor Ready"));
  display.drawLine(0, 9, SCREEN_W, 9, SSD1306_WHITE);
  display.setCursor(0, 14);
  display.printf("IP: %s", g_ip_str);
  display.display();
  delay(1500);
}

// ==================== 主循环 ====================

void loop() {
  static uint32_t lastTick = 0;
  uint32_t now = millis();

  // 处理 Web 请求（非阻塞）
  server.handleClient();

  // 定时采样
  if (now - lastTick < SAMPLE_INTERVAL_MS) {
    return;
  }
  lastTick = now;

  // 逐路读取 ADC 并换算电压
  for (uint8_t i = 0; i < ADC_COUNT; i++) {
    g_values[i] = readADC2(i);
    g_volts[i]  = (float)g_values[i] / ADC_MAX * ADC_VREF;
  }

  // ---- 刷新 OLED ----
  display.clearDisplay();

  // 标题栏 + WiFi 状态
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(0, 0);
  display.print(F("ADC Monitor"));
  if (g_wifi_connected) {
    display.setCursor(80, 0);
    display.print(F("[WiFi]"));
  } else {
    display.setCursor(80, 0);
    display.print(F("[NoWiFi]"));
  }
  display.drawLine(0, 9, SCREEN_W, 9, SSD1306_WHITE);

  // 四路数据
  for (uint8_t i = 0; i < ADC_COUNT; i++) {
    int y = 14 + i * 13;
    display.setCursor(0, y);
    display.printf("GPIO%2d", ADC_PINS[i]);
    display.setCursor(45, y);
    display.printf("%4u", g_values[i]);
    display.setCursor(80, y);
    display.printf("%5.2fV", g_volts[i]);
  }

  display.display();

  // 串口输出（调试用）
  for (uint8_t i = 0; i < ADC_COUNT; i++) {
    Serial.printf("GPIO%2u=%4u (%.2fV)  ", ADC_PINS[i], g_values[i], g_volts[i]);
  }
  Serial.printf(" | adc2_ready=%d (配置 %s)\n", g_adc2_ready, g_adc2_ready ? "成功" : "失败");
}