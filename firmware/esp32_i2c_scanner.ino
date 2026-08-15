/*
 * I2C 扫描：用于查找 OLED 实际地址
 * SDA = GPIO23, SCL = GPIO21
 */
#include <Wire.h>

void setup() {
  Serial.begin(115200);
  delay(200);
  Wire.begin(23, 21);   // SDA, SCL
  Serial.println(F("\n[I2C] 正在扫描..."));
}

void loop() {
  byte count = 0;
  Serial.println(F("[I2C] 开始扫描"));
  for (byte addr = 1; addr < 127; addr++) {
    Wire.beginTransmission(addr);
    byte err = Wire.endTransmission();
    if (err == 0) {
      Serial.printf("[I2C] 发现设备: 0x%02X\n", addr);
      count++;
    }
  }
  if (count == 0) {
    Serial.println(F("[I2C] 未发现任何设备"));
  } else {
    Serial.printf("[I2C] 共发现 %u 个设备\n", count);
  }
  delay(3000);
}
