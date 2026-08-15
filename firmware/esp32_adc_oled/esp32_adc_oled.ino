/*
 * ESP32-WROOM 四路 ADC 检测 + OLED 显示
 *
 * 引脚配置：
 *   - ADC 检测：GPIO14, GPIO27, GPIO26, GPIO25（均为 ADC1 通道，Wi-Fi 运行时可用）
 *   - OLED I2C：SDA = GPIO23，SCL = GPIO21
 *
 * 依赖库（Arduino IDE 库管理器安装）：
 *   - Adafruit GFX Library
 *   - Adafruit SSD1306
 *
 * OLED 型号：SSD1306 0.96" 128x64 I2C（地址一般为 0x3C，部分模块为 0x3D）
 */

#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

// ---------------- 引脚与参数定义 ----------------

// ADC 检测引脚
static const uint8_t ADC_PINS[]  = {14, 27, 26, 25};
static const uint8_t ADC_COUNT   = sizeof(ADC_PINS) / sizeof(ADC_PINS[0]);

// OLED I2C 引脚
static const uint8_t OLED_SDA    = 22;
static const uint8_t OLED_SCL    = 21;

// OLED 显示参数
static const uint16_t SCREEN_W   = 128;
static const uint16_t SCREEN_H   = 64;
static const uint8_t  OLED_ADDR  = 0x3C;   // 如显示不出改为 0x3D

// ESP32 ADC 默认 12 位（0-4095），参考电压约 3.3V
static const float    ADC_VREF   = 3.3f;
static const uint16_t ADC_MAX    = 4095;

// 刷新间隔（毫秒），避免 OLED 闪烁过快
static const uint32_t SAMPLE_INTERVAL_MS = 300;

// ---------------- OLED 对象 ----------------
Adafruit_SSD1306 display(SCREEN_W, SCREEN_H, &Wire, -1);

// ---------------- 初始化 ----------------
void setup() {
  Serial.begin(115200);
  delay(200);

  // 初始化 I2C，指定 SDA / SCL 引脚
  Wire.begin(OLED_SDA, OLED_SCL);

  // 初始化 OLED
  if (!display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR)) {
    Serial.println(F("[OLED] 未找到 SSD1306 屏，请检查接线与地址"));
    while (true) {
      delay(1000);  // 停在这里，避免后续逻辑空跑
    }
  }

  // 显示启动画面
  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);
  display.setTextSize(1);
  display.setCursor(20, 0);
  display.println(F("ESP32 ADC OLED"));
  display.setCursor(10, 16);
  display.println(F("ADC: 14 27 26 25"));
  display.setCursor(10, 28);
  display.println(F("SDA:23  SCL:21"));
  display.setCursor(10, 48);
  display.println(F("Starting..."));
  display.display();
  delay(1000);
}

// ---------------- 主循环 ----------------
void loop() {
  static uint32_t lastTick = 0;
  uint32_t now = millis();
  if (now - lastTick < SAMPLE_INTERVAL_MS) {
    return;
  }
  lastTick = now;

  // 逐路读取 ADC 并换算电压
  uint16_t values[ADC_COUNT];
  float    volts[ADC_COUNT];
  for (uint8_t i = 0; i < ADC_COUNT; i++) {
    values[i] = analogRead(ADC_PINS[i]);
    volts[i]  = (float)values[i] / ADC_MAX * ADC_VREF;
  }

  // 刷新 OLED
  display.clearDisplay();

  // 标题
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(0, 0);
  display.println(F("ADC Monitor"));
  display.drawLine(0, 9, SCREEN_W, 9, SSD1306_WHITE);

  // 四路数据，每行一个 GPIO
  for (uint8_t i = 0; i < ADC_COUNT; i++) {
    // 行高 13px，从 y=14 开始，最后一行（i=3）到 y=53
    int y = 14 + i * 13;
    display.setCursor(0, y);
    display.printf("GPIO%2d", ADC_PINS[i]);

    display.setCursor(45, y);
    display.printf("%4u", values[i]);

    display.setCursor(80, y);
    display.printf("%5.2fV", volts[i]);
  }

  display.display();

  // 串口同步输出，方便调试
  for (uint8_t i = 0; i < ADC_COUNT; i++) {
    Serial.printf("GPIO%2u=%4u (%.2fV)  ", ADC_PINS[i], values[i], volts[i]);
  }
  Serial.println();
}
