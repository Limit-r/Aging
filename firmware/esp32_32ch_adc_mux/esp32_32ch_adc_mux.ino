/*
 * ESP32 + 双 CD74HCT4067  32路模拟采集（WiFi Web 版）
 *
 * 硬件连接（对照原理图）：
 *   ─────────────────────────────────────────────
 *   4067 地址线（两片并联，共用同一组选择信号）——按引脚放大截图丝印核对
 *     S0  → ESP32 GPIO18 (Pin24 D18)
 *     S1  → ESP32 GPIO19 (Pin25 D19)
 *     S2  → ESP32 GPIO21 (Pin26 D21)
 *     S3  → ESP32 GPIO22 (Pin29 D22)
 *     E#  → GND（两片均已接地，始终使能）
 *   ─────────────────────────────────────────────
 *   4067 公共输出 Z  →  分压 + RC滤波  →  ESP32 ADC（用户确认 PCB 实际为 GPIO33/32）
 *     U1（第1片，对应 CN6/CN7 连接器 I07~I15）
 *        Z(1脚)  → 分压抽头 → GPIO33 (ADC1_CH5)
 *     U2（第2片，对应 CN4/CN5 连接器 I07~I15）
 *        Z(1脚)  → 分压抽头 → GPIO32 (ADC1_CH4)
 *   ─────────────────────────────────────────────
 *   电流换算：直接引脚mV线性换算（0A零点、灵敏度由万用表实测标定，见代码参数区两步标定法）
 *
 * WiFi 配置：
 *   SSID : QH
 *   PASS : 123456789
 *
 * Web 接口（设备连上热点后串口会打印 IP）：
 *   GET /        → 手机友好的 HTML 页面，1 秒自动刷新，显示 32 路毫伏值
 *   GET /json    → JSON 格式：{"ch":[0,0,...,0]}  共 32 个数，单位 mV
 *   GET /csv     → 纯 CSV：CH00_mV,CH01_mV,...,CH31_mV  一行
 *
 * 说明：
 *   - GPIO32/33 属于 ADC1，与 WiFi 不冲突（只有 ADC2 会被 WiFi 占用）
 *   - 两片 4067 地址线并联，一次切换可同时读取两路（U1+U2）
 *   - 通道切换后加入延时，等待 RC 滤波电容充电稳定
 */

#include <WiFi.h>
#include <WebServer.h>

// ---------------- WiFi 配置 ----------------
static const char* WIFI_SSID = "QH";
static const char* WIFI_PASS = "123456789";
static const uint16_t HTTP_PORT = 80;
static const uint32_t WIFI_CONNECT_TIMEOUT_MS = 15000;   // 最多等 15 秒

WebServer server(HTTP_PORT);

// ---------------- 地址线动态映射 ----------------
//
// ——已按用户放大的 ESP32 引脚截图核对——
//   Pin24 D18 → S0(18)
//   Pin25 D19 → S1(19)
//   Pin26 D21 → S2(21)
//   Pin29 D22 → S3(22)
//   （D23 是 NC 空脚，S3 不在 D23）
//
// 通过 /diag 页面可以一键切换 24 种排列并即时生效，不用反复烧录。
// 找到正确映射后把 DEFAULT_ADDR_MAP_IDX 改成那个编号即可固化。

// 4 条真实接线的 GPIO 池：顺序无关（用于生成24种全排列），但默认映射下
// ADDR_GPIO_POOL[0..3] = [18,19,21,23] 不对，实际是 [18,19,21,22]。
static const uint8_t ADDR_GPIO_POOL[4] = {18, 19, 21, 22};
static uint8_t g_addrPinForS[4] = {18, 19, 21, 22};   // 运行时 S0~S3 实际 GPIO
static uint8_t g_addrMapIdx = 0;                      // 当前映射编号 0~23

/**
 * @brief 24 种排列（基于 ADDR_GPIO_POOL 的索引排列）
 *        生成：4 个元素的全排列。每一组 {a,b,c,d} 表示
 *          S0 → ADDR_GPIO_POOL[a], S1→[b], S2→[c], S3→[d]
 */
static const uint8_t ADDR_MAP_PERM[24][4] = {
  {0,1,2,3},{0,1,3,2},{0,2,1,3},{0,2,3,1},{0,3,1,2},{0,3,2,1},
  {1,0,2,3},{1,0,3,2},{1,2,0,3},{1,2,3,0},{1,3,0,2},{1,3,2,0},
  {2,0,1,3},{2,0,3,1},{2,1,0,3},{2,1,3,0},{2,3,0,1},{2,3,1,0},
  {3,0,1,2},{3,0,2,1},{3,1,0,2},{3,1,2,0},{3,2,0,1},{3,2,1,0}
};

/**
 * @brief 按映射索引设置 g_addrPinForS
 */
static void setAddrMap(uint8_t idx) {
  if (idx >= 24) return;
  for (uint8_t s = 0; s < 4; s++) {
    g_addrPinForS[s] = ADDR_GPIO_POOL[ ADDR_MAP_PERM[idx][s] ];
  }
  g_addrMapIdx = idx;
}

/**
 * @brief 把"按引脚号指定映射"转成 0~23 中的一个索引，找不到返回 255
 */
static uint8_t findMapIdxByPins(uint8_t s0, uint8_t s1, uint8_t s2, uint8_t s3) {
  for (uint8_t i = 0; i < 24; i++) {
    if (ADDR_GPIO_POOL[ADDR_MAP_PERM[i][0]] == s0 &&
        ADDR_GPIO_POOL[ADDR_MAP_PERM[i][1]] == s1 &&
        ADDR_GPIO_POOL[ADDR_MAP_PERM[i][2]] == s2 &&
        ADDR_GPIO_POOL[ADDR_MAP_PERM[i][3]] == s3) return i;
  }
  return 255;
}

// 默认映射：按截图丝印核对 S0=18, S1=19, S2=21, S3=22。
// ADDR_GPIO_POOL = [18,19,21,22]，permutation{0,1,2,3} = 映射 #0。
static const uint8_t DEFAULT_ADDR_MAP_IDX = 0;

// ---------------- 地址固定（Lock）调试支持 ----------------
//
// 用法：
//   GET /lock?addr=0   → 把 4067 地址固定在 0（只看 I00），U1/U2 都只会出这一路数据
//                         （sampleAllChannels 只执行一次 addr，其余通道不动缓存）
//   GET /lock?addr=3   → 固定地址 3（只看 I03）
//   GET /unlock        → 恢复 0~15 自动循环采样
// 目的：直接验证"4067 是否真的按地址切换"，排除地址毛刺、电荷残留、串扰等叠加因素。
//
static bool     g_addrLocked = false;
static uint8_t  g_lockAddr   = 0;

// ---------------- 引脚定义 ----------------

// 每片 4067 通道数（0~15）
static const uint8_t CHANNELS_PER_MUX = 16;
static const uint8_t TOTAL_CHANNELS    = 32;   // 两片合计

// ESP32 ADC 默认 12 位
static const uint16_t ADC_RAW_MAX  = 4095;
static const float    ADC_VREF_MV  = 3300.0f;   // 3.3V = 3300mV

// 两片 4067 各自对应的 ADC 输入引脚（用户确认 PCB 实际为 GPIO33 / 32）
//   U1(Z) → 分压抽头实际接到 → GPIO33 (ADC1_CH5)
//   U2(Z) → 分压抽头实际接到 → GPIO32 (ADC1_CH4)
//   GPIO33/32 都是 ADC1，WiFi 下可正常使用。
static const uint8_t ADC_PIN_U1 = 33;   // ADC1_CH5（U1 侧）
static const uint8_t ADC_PIN_U2 = 32;   // ADC1_CH4（U2 侧）

// ---------------- 参数定义 ----------------

// -------- ACS712 电流换算（★★★只基于用户万用表实测值，不套任何理论假设★★★）--------
//
//  【你的硬件是什么分压比、COM输出是不是正好2.5V、4067有没有拉偏——不管。
//   只看你万用表直接在 GPIO32/GPIO33 上测到的两个数值】。
//
//   公式：I(mA) = (pin_mv - ZERO_PIN_MV) * 10000 / SENS_PIN_MV_PER_A_X10
//   全程只有 1 次减法 + 1 次整数除法，误差最小。
//
// =========================================================================
//  ★★★ 两 步 标 定 法 （只改下面两个宏）★★★
// =========================================================================
//
//  步骤 1：标定 ZERO_PIN_MV（0A 零点）
//    ① 负载断电 → 确认 0A
//    ② 万用表打到"直流 mV 档"，直接测 ESP32 的 GPIO33（U1侧）或 GPIO32（U2侧）引脚对地电压
//    ③ 读 10 个数取中间值 → 填入 ZERO_PIN_MV
//    ④ 同时把这个值 ±40mV 分别填到 ZERO_WIN_PIN_LO_MV / ZERO_WIN_PIN_HI_MV
//
//  步骤 2：标定 SENS_PIN_MV_PER_A_X10（斜率，灵敏度 ×10）
//    方法 A（推荐·最准）：两点法
//      ① 先在 0A 时读一次引脚电压 → V0（=ZERO_PIN_MV）
//      ② 通一个你已知大小的真实电流（如 10A/15A，方向为正）→ I_know_A
//      ③ 稳定后再读引脚电压 → V1
//      ④ 灵敏度 SENS_mV_per_A = |V1 - V0| / I_know_A
//      ⑤ SENS_PIN_MV_PER_A_X10 = round(SENS_mV_per_A × 10)   ← 填入下方
//
//    方法 B（应急·不准）：按 ACS712 手册粗估
//      先测一下 COM 节点电压 Vcom@0A、GPIO 引脚电压 Vpin@0A，
//      真实分压比 K = Vcom / Vpin
//      SENS_mV_per_A = 66 / K    （66mV/A 是 ACS712 芯片本身灵敏度）
//      SENS_PIN_MV_PER_A_X10 = round(SENS_mV_per_A * 10)
//
//  ★后续每次改硬件/换板子，只要重复做一遍两步标定即可，其他参数不用动。
// =========================================================================

// ---------- ★★★ 你只需要改这里两个宏 + 窗口边界 ★★★ ----------
// 【当前硬件状态：ACS712 为 40A 版(灵敏度=50mV/A) → 4067 直通 → 1:2 分压(取2/3) → ESP32】
//   0A 实测 GPIO 引脚 ≈1510mV（约1505~1560 波动中心；对应 ACS712 实际 VCC≈4.5V、零点≈2.27V）
//   引脚侧灵敏度 = 芯片 50mV/A × 2/3 ≈ 33.3mV/A → ×10 = 333（★两点法可再精校）
//   ★注意：旧注释误按 30A版(66mV/A)或 1:3 分压推导，均已按真实 40A 版 + 2/3 分压更正。
static const int32_t  ACS712_ZERO_PIN_MV     = 1510;  // 【步骤1：改这里！0A时实测GPIO引脚电压(mV)】
static const int32_t  ACS712_SENS_PIN_MV_PER_A_X10 = 333; // 【步骤2：改这里！灵敏度(mV/A)×10】
// 0A 窗口：ZERO_PIN_MV ±40mV （按需自己调整）
static const int32_t  ACS712_ZERO_WIN_PIN_LO_MV = ACS712_ZERO_PIN_MV - 40;
static const int32_t  ACS712_ZERO_WIN_PIN_HI_MV = ACS712_ZERO_PIN_MV + 40;

// --- 以下参数不用改（固定是通用值）---

// 未接信号/浮空判定：引脚 <260mV 视为通道没接 ACS712 → 0A
static const int32_t  ACS712_MIN_SIGNAL_PIN_MV = 260;
// 有效信号保护带（引脚侧，直接用 ADC 范围）
static const int32_t  ACS712_VALID_PIN_LO_MV = 260;
static const int32_t  ACS712_VALID_PIN_HI_MV = 3300;
// EMA 滑动平均权重 0~100（%），50=约1秒收敛
static const uint8_t  ACS712_SMOOTH_ALPHA    = 50;

/**
 * @brief  ★直接用"GPIO引脚mV"换算成"电流mA"（全程整数，只有一次减法+一次除法）
 */
static inline int32_t pinMvToCurrentMa(int32_t pin_mv) {
  if (pin_mv < ACS712_MIN_SIGNAL_PIN_MV) return 0;                 // ① 未接信号
  if (pin_mv < ACS712_VALID_PIN_LO_MV || pin_mv > ACS712_VALID_PIN_HI_MV) return 0; // ② 保护带
  if (pin_mv >= ACS712_ZERO_WIN_PIN_LO_MV &&
      pin_mv <= ACS712_ZERO_WIN_PIN_HI_MV) return 0;               // ③ 0A 窗口
  int32_t delta = pin_mv - ACS712_ZERO_PIN_MV;                     // mV
  // 避免浮点：I(mA) = delta(mV) * 10000 / SENS_PIN_MV_PER_A_X10
  return (int32_t)( (int64_t)delta * 10000 / (int64_t)ACS712_SENS_PIN_MV_PER_A_X10 );
}

// 切换通道后第 1 阶段延时（ms）：
//   给 4067 模拟开关稳定 + 地址线毛刺消退 + RC 滤波电容初步充/放电。
//   空载通道只有 5kΩ 下拉对 100nF 放电，τ=5k*100n=500us，8τ≈4ms 才到 0.03% 残留，
//   取 8ms 给足够时间避免"前一通道电压串到后面浮空通道"。
static const uint32_t MUX_SETTLE_PHASE1_MS = 8;

// 丢首样后、正式过采样前的额外等待（ms）：
//   首样 dummy read 会把 ADC 内部采样保持电容刷新到当前通道电压，
//   再等 1ms 让内部 S/H 电容彻底充电，之后的采样才是真实的。
static const uint32_t MUX_SETTLE_PHASE2_MS = 1;

// dummy read 次数：切换后先丢几次再正式采，消除 4067 电荷注入残留。
//   4067 内部模拟开关切换时会向 Z 端注入电荷，必须被前端 100nF 电容吸收，
//   连续多次空读可以把 ESP32 ADC 内部 S/H 电容的旧电荷彻底冲掉。
static const uint8_t  MUX_DUMMY_READ_COUNT = 3;

// 每通道有效平均采样次数（不含丢首样）
static const uint8_t  OVERSAMPLE_COUNT = 4;

// 丢首样数：OVERSAMPLE 内部前 N 次丢弃，只平均后面的
static const uint8_t  OVERSAMPLE_DROP_FIRST = 1;

// 整轮采样间隔（ms）：32 路一轮的周期
//   每通道至少 8+1=9ms + (3+4)*1ms(采样) ≈ 16ms，16*16地址≈256ms，
//   取 500ms 留一半给 HTTP，避免网页卡顿。
static const uint32_t SAMPLE_INTERVAL_MS = 500;

// ---------------- 采样缓存 ----------------
static uint16_t g_raw[TOTAL_CHANNELS];   // 原始 ADC 值
static uint32_t g_mv [TOTAL_CHANNELS];   // 换算后毫伏（整数，避免浮点序列化开销）
static uint32_t g_mv_sm[TOTAL_CHANNELS]; // 换算后毫伏经 EMA 平滑，供电流计算用（抑制偶发尖峰）

/**
 * @brief  对 g_mv 做指数滑动平均(EMA)到 g_mv_sm
 *         首次调用以当前 g_mv 作为初始值，避免从 0 起步的拉偏。
 *         g_mv 保留瞬时值供诊断对比；g_mv_sm 只用于电流显示/输出。
 */
static void emaSmoothVoltage(void) {
  static bool inited = false;
  if (!inited) {
    for (uint8_t i = 0; i < TOTAL_CHANNELS; i++) g_mv_sm[i] = g_mv[i];
    inited = true;
  }
  const uint32_t wNew = ACS712_SMOOTH_ALPHA;
  const uint32_t wOld = (uint32_t)100 - ACS712_SMOOTH_ALPHA;
  for (uint8_t i = 0; i < TOTAL_CHANNELS; i++) {
    g_mv_sm[i] = (g_mv[i] * wNew + g_mv_sm[i] * wOld) / 100u;
  }
}

// ---------------- WiFi 辅助 ----------------

static bool wifiConnect(void) {
  Serial.printf("WiFi: 正在连接 SSID [%s] ...\r\n", WIFI_SSID);
  WiFi.begin(WIFI_SSID, WIFI_PASS);

  uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print('.');
    if (millis() - start > WIFI_CONNECT_TIMEOUT_MS) {
      Serial.println("\r\nWiFi: 连接超时，请检查热点名称/密码是否正确");
      return false;
    }
  }
  Serial.println();
  Serial.printf("WiFi: 已连接，信号强度 %d dBm\r\n", WiFi.RSSI());
  Serial.printf("WiFi: 设备 IP = %s\r\n", WiFi.localIP().toString().c_str());
  Serial.printf("WiFi: 打开手机浏览器访问 http://%s/ 即可查看数据\r\n", WiFi.localIP().toString().c_str());
  return true;
}

// ---------------- HTTP 处理 ----------------

/**
 * @brief  辅助：把 raw 转成"ADC 引脚直接 mV"
 *         直接用万用表对比 GPIO32/33 读数即可验证。
 *         ★ g_mv 就存这个值——不再做中间分压还原！
 */
static inline uint32_t rawToPinMv(uint16_t raw) {
  return (uint32_t)raw * (uint32_t)ADC_VREF_MV / ADC_RAW_MAX;
}

/**
 * @brief  诊断辅助：把 raw 按"×3 放大"显示（仅诊断用，不参与电流计算）
 *         对照用：如果硬件真的是 10k+5k 电阻 ÷3 分压，那么 0A 时这一列应≈ACS712 中点 2500mV，
 *         同时 gain1 列（引脚mV）≈833mV。如果不是这样，用顶部参数的"两步标定法"实测填入即可。
 */
static inline uint32_t rawToGain3Mv(uint16_t raw) {
  return (uint32_t)raw * (uint32_t)(ADC_VREF_MV * 3.0f) / ADC_RAW_MAX;
}

/**
 * @brief  GET /lock?addr=N   →  固定 4067 地址只采 N 通道 (N=0~15)
 *         用于直接验证"4067 是否真的按地址切换 + 只有一路该有值"
 */
static void handleLock(void) {
  if (server.hasArg("addr")) {
    long a = server.arg("addr").toInt();
    if (a >= 0 && a < CHANNELS_PER_MUX) {
      g_addrLocked = true;
      g_lockAddr   = (uint8_t)a;
      Serial.printf("LOCK: 地址固定到 0x%02X (CH%02u / CH%02u)\r\n",
                    g_lockAddr, g_lockAddr, g_lockAddr + CHANNELS_PER_MUX);
    }
  }
  server.sendHeader("Location","/diag",true);
  server.send(302,"text/plain","OK");
}

/**
 * @brief  GET /unlock  →  恢复 0~15 循环采样
 */
static void handleUnlock(void) {
  g_addrLocked = false;
  Serial.println("LOCK: 已解锁，恢复 0~15 循环采样");
  server.sendHeader("Location","/diag",true);
  server.send(302,"text/plain","OK");
}

/**
 * @brief  GET /setmap?idx=5  →  切换地址映射 0~23（重定向回 /diag）
 *         GET /setmap?s0=18&s1=19&s2=21&s3=22  →  按引脚号指定映射
 */
static void handleSetMap(void) {
  bool ok = false;
  if (server.hasArg("idx")) {
    long v = server.arg("idx").toInt();
    if (v >= 0 && v < 24) {
      setAddrMap((uint8_t)v);
      ok = true;
    }
  } else if (server.hasArg("s0") && server.hasArg("s1") && server.hasArg("s2") && server.hasArg("s3")) {
    long s0 = server.arg("s0").toInt();
    long s1 = server.arg("s1").toInt();
    long s2 = server.arg("s2").toInt();
    long s3 = server.arg("s3").toInt();
    uint8_t idx = findMapIdxByPins((uint8_t)s0,(uint8_t)s1,(uint8_t)s2,(uint8_t)s3);
    if (idx < 24) { setAddrMap(idx); ok = true; }
  }
  if (ok) {
    Serial.printf("MAP: 切换到映射 #%u (S0=%u,S1=%u,S2=%u,S3=%u)\r\n",
                  g_addrMapIdx, g_addrPinForS[0], g_addrPinForS[1], g_addrPinForS[2], g_addrPinForS[3]);
  }
  server.sendHeader("Location","/diag",true);
  server.send(302,"text/plain","OK");
}

/**
 * @brief  GET /diag  → 诊断页面
 *         - 顶部显示当前地址映射（S0/S1/S2/S3 → GPIO）
 *         - 24 种映射切换按钮（不用重烧，点一下就生效）
 *         - 每通道 4 列：raw / ADC引脚mV / 真实mV / 条形
 *         - 自检：S0~S3 期望电平 vs 实际读回电平（诊断是否真的驱动到了4067）
 */
static void handleDiag(void) {
  // 先做一次"地址线自检"：
  //   拉到 0x0F（S0~S3 全 1）等 2ms，读回每条；再拉到 0x00 等 2ms，读回。
  uint8_t hiActual[4] = {0};
  uint8_t loActual[4] = {0};

  muxSelectChannel(0x0F);
  delay(2);
  for (uint8_t s = 0; s < 4; s++) {
    pinMode(g_addrPinForS[s], INPUT);   // 暂时改成输入，读回
    hiActual[s] = digitalRead(g_addrPinForS[s]);
    pinMode(g_addrPinForS[s], OUTPUT);  // 恢复输出
  }

  muxSelectChannel(0x00);
  delay(2);
  for (uint8_t s = 0; s < 4; s++) {
    pinMode(g_addrPinForS[s], INPUT);
    loActual[s] = digitalRead(g_addrPinForS[s]);
    pinMode(g_addrPinForS[s], OUTPUT);
  }

  String html = F("<!DOCTYPE html><html lang='zh-CN'><head>"
                  "<meta charset='UTF-8'>"
                  "<meta name='viewport' content='width=device-width,initial-scale=1'>"
                  "<title>诊断 - 通道映射排查</title>"
                  "<style>"
                  "body{font-family:Arial,sans-serif;margin:8px;background:#111;color:#eee;font-size:12px;}"
                  "a.btn{display:inline-block;padding:4px 8px;margin:2px;background:#2a6;color:#fff;text-decoration:none;border-radius:4px;}"
                  "a.btn.cur{background:#e53;}"
                  "table{width:100%;border-collapse:collapse;font-size:11px;margin-top:6px;}"
                  "th,td{padding:3px 2px;text-align:center;border:1px solid #333;}"
                  "th{background:#222;color:#aaa;}"
                  ".ok{color:#7e7;} .bad{color:#e55;}"
                  ".bar{display:inline-block;height:6px;background:#4fc3f7;margin-right:2px;vertical-align:middle;}"
                  "h2{margin:6px 0;font-size:15px;}"
                  "h3{margin:10px 0 4px;font-size:13px;color:#4fc3f7;}"
                  ".row{display:flex;flex-wrap:wrap;}"
                  "</style></head><body>");

  html += "<h2>🔧 诊断页 · 地址线映射排查</h2>";
  html += "<div style='color:#aaa'>";
  html += "当前映射 #"+String(g_addrMapIdx)+"：";
  char tag[64];
  snprintf(tag,sizeof(tag),"S0=GPIO%u, S1=GPIO%u, S2=GPIO%u, S3=GPIO%u",
           g_addrPinForS[0],g_addrPinForS[1],g_addrPinForS[2],g_addrPinForS[3]);
  html += String(tag) + "</div>";

  // 自检结果
  html += "<h3>引脚驱动自检（S0~S3）</h3>";
  html += "<table><tr><th>位</th><th>GPIO</th><th>写1读回</th><th>写0读回</th><th>结论</th></tr>";
  for (uint8_t s = 0; s < 4; s++) {
    bool driveHiOk = (hiActual[s] == 1);
    bool driveLoOk = (loActual[s] == 0);
    const char* verdict = (driveHiOk && driveLoOk) ? "<span class='ok'>✓ 正常</span>"
                          : (driveHiOk ? "<span class='bad'>✗ 拉低失败</span>"
                                       : "<span class='bad'>✗ 拉高失败（可能悬空）</span>");
    html += "<tr><td>S" + String(s) + "</td><td>" + String(g_addrPinForS[s]) +
            "</td><td>" + String(hiActual[s]) +
            "</td><td>" + String(loActual[s]) +
            "</td><td>" + verdict + "</td></tr>";
  }
  html += "</table>";

  // ----- Lock 调试区：逐个地址固定采样 -----
  html += "<h3>🔒 固定地址采样（排查4067是否真的按地址切换）</h3>";
  if (g_addrLocked) {
    html += "<div style='background:#311;padding:6px;border-radius:4px;margin-bottom:4px;'>";
    html += "当前 <b>已锁定地址 " + String(g_lockAddr) + " (CH" + String(g_lockAddr<10?"0":"") + String(g_lockAddr)
          + " / CH" + String(g_lockAddr+CHANNELS_PER_MUX) + ")</b>　";
    html += "<a class='btn' href='/unlock' style='background:#e53;'>▶ 解锁恢复 0~15 循环</a>";
    html += "</div>";
  } else {
    html += "<div style='color:#aaa;margin-bottom:4px;'>当前：自动循环 0~15。点击下方任一按钮锁定单通道，只有 CH_N 和 CH_{N+16} 应该有值，其他通道必须显示 0。<br>";
    html += "<b>ACS712 实际接入的是地址 0~3 吧？那就逐个锁 0,1,2,3 验证。</b></div>";
  }
  html += "<div class='row'>";
  for (uint8_t a = 0; a < CHANNELS_PER_MUX; a++) {
    bool cur = g_addrLocked && (a == g_lockAddr);
    html += "<a class='btn " + String(cur ? "cur":"") + "' href='/lock?addr="+String(a)+"'>";
    html += "锁 CH" + String(a<10?"0":"") + String(a) + "</a>";
  }
  html += "</div>";

  // 24 个映射按钮
  html += "<h3>24 种地址映射切换（不用重烧，点击即生效）</h3>";
  html += "<div class='row'>";
  for (uint8_t i = 0; i < 24; i++) {
    uint8_t p[4] = {
      ADDR_GPIO_POOL[ADDR_MAP_PERM[i][0]],
      ADDR_GPIO_POOL[ADDR_MAP_PERM[i][1]],
      ADDR_GPIO_POOL[ADDR_MAP_PERM[i][2]],
      ADDR_GPIO_POOL[ADDR_MAP_PERM[i][3]]
    };
    bool cur = (i == g_addrMapIdx);
    char lbl[64];
    snprintf(lbl,sizeof(lbl),"#%u %u/%u/%u/%u%s", i, p[0],p[1],p[2],p[3], cur ? " ·当前":"");
    html += "<a class='btn " + String(cur ? "cur":"") + "' href='/setmap?idx=" + String(i) + "'>"+lbl+"</a>";
  }
  html += "</div>";

  // ----- 关键数据表：同时显示引脚mV + 两种分压假设 + 直接映射电流 -----
  html += "<h3>📐 U1 CH00~CH07 详细（电压 + 电流，★直接引脚mV换算）</h3>";
  html += "<div style='color:#aaa;font-size:11px;margin-bottom:4px;'>";
  html += "列说明：raw=ADC原始值；引脚mV=GPIO33直接电压(万用表对比，g_mv也存这个值)；gain1=引脚×1(就是实际GPIO电压)；gain3=引脚×3(若硬件真÷3分压，此列≈ACS712真实输出)；";
  html += "电流列=按代码顶部「实测零点=" + String((int)ACS712_ZERO_PIN_MV) + "mV + 实测灵敏度=" + String((int)(ACS712_SENS_PIN_MV_PER_A_X10/10)) + "." + String((int)(ACS712_SENS_PIN_MV_PER_A_X10%10)) + "mV/A」直接换算（两步标定法，见代码顶部说明）。接了I00~I03的4路0A应接近±0mA。";
  html += "</div>";
  html += "<table><tr>"
          "<th>CH</th><th>raw</th>"
          "<th>引脚mV<br>(=g_mv,万用表对比)</th>"
          "<th>gain1<br>(×1,引脚实际电压)</th>"
          "<th>gain3<br>(×3放大,判断是否÷3)</th>"
          "<th>电流<br>(引脚直接换算)</th><th>条形</th></tr>";
  for (uint8_t ch = 0; ch < 8; ch++) {
    uint16_t r = g_raw[ch];
    uint32_t cached_pin_mv = g_mv[ch];      // ★现就是引脚mV（不再做分压还原），可与pmv交叉验证一致性
    uint32_t pmv  = rawToPinMv(r);          // 引脚mV实时计算（和上面缓存应完全一致，差异=缓存逻辑问题）
    uint32_t g1mv = pmv;                    // gain1 = 引脚×1
    uint32_t g3mv = rawToGain3Mv(r);        // gain3 = 引脚×3（辅助诊断：硬件是否真÷3）
    int32_t  ma  = pinMvToCurrentMa((int32_t)g_mv_sm[ch]);   // ★直接基于引脚mV换算电流

    // 条形图：用真实电流 ±40A 显示
    int32_t biased = ma + 40000;
    if (biased < 0) biased = 0;
    if (biased > 80000) biased = 80000;
    uint8_t barW = (uint8_t)((uint32_t)biased * 40UL / 80000UL);

    // 电流格式 & 颜色
    int32_t absMa = (ma<0)?-ma:ma;
    const char* i_cls = (absMa<500)?"#888":(absMa<10000?"#fd5":"#e55");
    char sign = (ma>=0)?'+':'-';
    String i_str;
    if (absMa < 1000) i_str = String(sign)+String(absMa)+"mA";
    else {
      char b[16]; snprintf(b,sizeof(b),"%c%d.%02dA",sign,(int)(absMa/1000),(int)((absMa%1000)/10));
      i_str = String(b);
    }

    html += "<tr><td>CH" + String(ch<10?"0":"") + String(ch) + "</td>";
    html += "<td>" + String(r) + "</td>";
    html += "<td style='color:#fb0'>" + String(pmv) + "</td>";
    // 选最接近 ACS712 实际中点 (≈2500mV) 的那一列标绿
    int d1 = (int)g1mv - 2500;  if (d1<0) d1=-d1;
    int d3 = (int)g3mv - 2500;  if (d3<0) d3=-d3;
    html += "<td style='color:" + String(d1<d3 ? "#7e7" : "#888") + ";font-weight:" + String(d1<d3 ? "bold":"normal") + "'>" + String(g1mv) + "</td>";
    html += "<td style='color:" + String(d3<d1 ? "#7e7" : "#888") + ";font-weight:" + String(d3<d1 ? "bold":"normal") + "'>" + String(g3mv) + "</td>";
    html += "<td style='color:" + String(i_cls) + ";font-weight:bold'>" + i_str + "</td>";
    html += "<td><span class='bar' style='width:" + String(barW) + "px'></span></td></tr>";
  }
  html += "</table>";

  html += "<h3>U2 CH16~CH23 详细（判断U2是否也接了信号 —— 未接通道应被保护带屏蔽，显示≈0mA）</h3>";
  html += "<table><tr>"
          "<th>CH</th><th>raw</th>"
          "<th>引脚mV<br>(=g_mv,GPIO32实测)</th>"
          "<th>gain1<br>(×1,对照U1)</th>"
          "<th>gain3<br>(×3,诊断分压)</th>"
          "<th>电流<br>(引脚直接换算)</th><th>条形</th></tr>";
  for (uint8_t ch = 16; ch < 24; ch++) {
    uint16_t r = g_raw[ch];
    uint32_t pmv = rawToPinMv(r);           // 引脚mV实时计算
    uint32_t g1mv = pmv;                    // gain1 = 引脚×1
    uint32_t g3mv = rawToGain3Mv(r);        // gain3 = 引脚×3（同U1，用于诊断硬件分压）
    int32_t  ma  = pinMvToCurrentMa((int32_t)g_mv_sm[ch]);   // ★直接引脚换算
    int32_t biased = ma + 40000;
    if (biased < 0) biased = 0;
    if (biased > 80000) biased = 80000;
    uint8_t barW = (uint8_t)((uint32_t)biased * 40UL / 80000UL);
    int32_t absMa = (ma<0)?-ma:ma;
    const char* i_cls = (absMa<500)?"#888":(absMa<10000?"#fd5":"#e55");
    char sign = (ma>=0)?'+':'-';
    String i_str;
    if (absMa < 1000) i_str = String(sign)+String(absMa)+"mA";
    else {
      char b[16]; snprintf(b,sizeof(b),"%c%d.%02dA",sign,(int)(absMa/1000),(int)((absMa%1000)/10));
      i_str = String(b);
    }
    html += "<tr><td>CH" + String(ch) + "</td><td>" + String(r) + "</td>";
    html += "<td style='color:#fb0'>" + String(pmv) + "</td>";
    html += "<td>" + String(g1mv) + "</td>";
    html += "<td>" + String(g3mv) + "</td>";
    html += "<td style='color:" + String(i_cls) + ";font-weight:bold'>" + i_str + "</td>";
    html += "<td><span class='bar' style='width:" + String(barW) + "px'></span></td></tr>";
  }
  html += "</table>";

  html += "<h3>全 32 路 ADC 引脚 mV（热图）</h3>";
  html += "<table><tr>";
  for (uint8_t i = 0; i < TOTAL_CHANNELS; i++) {
    uint32_t pmv = rawToPinMv(g_raw[i]);
    if (i % 8 == 0 && i != 0) html += "</tr><tr>";
    const char* fg = pmv < 100 ? "#888" : pmv < 1500 ? "#fd5" : "#e55";
    const char* bg = pmv < 100 ? "#1a1a1a" : pmv < 1500 ? "#331" : "#311";
    char lbl[12];
    snprintf(lbl,sizeof(lbl),"CH%02u",i);
    html += "<td style='background:"+String(bg)+"'>"+String(lbl)+"<br><b style='color:"+String(fg)+"'>"+String(pmv)+"</b></td>";
  }
  html += "</tr></table>";

  html += "<div style='margin-top:10px;color:#aaa;'>";
  html += "<b>使用步骤：</b><br>";
  html += "① 先点「引脚驱动自检」4行都 <span class='ok'>✓ 正常</span>（不正常=那条S线没接到4067上，检查焊接）<br>";
  html += "② 逐个点「锁 CH00 / 锁 CH01 / 锁 CH02 / 锁 CH03」看：<br>";
  html += "　　• 锁到0时，只有 CH00 有值，其他必须为0 → 说明地址切换正确<br>";
  html += "　　• 如果锁 CH00 但 CH01 有值 → 说明 S0 被当成常 1，地址线还有问题<br>";
  html += "③ 【★两步标定法·校准零点和灵敏度】0A时（不接负载）看前4路电压：<br>";
  html += "　　• 0A 电压应落在「0A窗口 " + String((int)ACS712_ZERO_WIN_PIN_LO_MV) + "~" + String((int)ACS712_ZERO_WIN_PIN_HI_MV) + "mV」内 → 显示 0A<br>";
  html += "　　• 若0A显示不为0 → 把代码顶部 <b>ACS712_ZERO_PIN_MV</b> 改成 0A 时万用表实测的 GPIO 引脚 mV 值<br>";
  html += "　　• 灵敏度 <b>ACS712_SENS_PIN_MV_PER_A_X10</b> 用两点法标定：(V1-V0)/I_know_A × 10 填入<br>";
  html += "④ 如果U2(CH16+)也有非零值，说明屏蔽线/主PCB上 U1 和 U2 输入端有并联或走线接错。";
  html += "</div></body></html>";
  server.send(200, "text/html; charset=utf-8", html);
}

/**
 * @brief  GET /  → 手机浏览器用的 HTML 页面
 *         极简风格，32 路通道排成 4 列 × 8 行表格
 *         采用 AJAX(fetch /json) 局部刷新，约每 0.4 秒更新，不整页跳闪
 */
static void handleRoot(void) {
  String html = F("<!DOCTYPE html><html lang='zh-CN'><head>"
                  "<meta charset='UTF-8'>"
                  "<meta name='viewport' content='width=device-width,initial-scale=1'>"
                  "<title>ESP32 32CH 电流检测</title>"
                  "<style>"
                  "body{font-family:Arial,sans-serif;margin:8px;background:#111;color:#eee;}"
                  "h2{margin:8px 0;font-size:18px;}"
                  "h3{margin:12px 0 6px;font-size:15px;color:#4fc3f7;}"
                  "table{width:100%;border-collapse:collapse;font-size:13px;}"
                  "th,td{padding:5px 3px;text-align:center;border:1px solid #333;}"
                  "th{background:#222;color:#aaa;}"
                  "td.mv{font-variant-numeric:tabular-nums;}"
                  "tr:nth-child(even) td{background:#1a1a1a;}"
                  "span.lo{color:#888;}"
                  "span.mi{color:#ffd54f;}"
                  "span.hi{color:#ff6b6b;}"
                  ".bar{display:inline-block;height:6px;background:#4fc3f7;margin-right:3px;vertical-align:middle;}"
                  ".ip{color:#aaa;font-size:12px;}"
                  ".gray{color:#666;font-size:11px;}"
                  "</style></head><body>");

  html += "<h2>ESP32 32路采集（ACS712 40A 电流检测）</h2>";
  {
    char buf[120];
    // 全部改为实测参数（电压列 = GPIO引用mV，0A实测零点）
    snprintf(buf,sizeof(buf),
             "引脚0A窗口=%d~%dmV｜实测灵敏度=%d.%dmV/A｜0A实测零点 %dmV",
             (int)ACS712_ZERO_WIN_PIN_LO_MV, (int)ACS712_ZERO_WIN_PIN_HI_MV,
             (int)(ACS712_SENS_PIN_MV_PER_A_X10/10), (int)(ACS712_SENS_PIN_MV_PER_A_X10%10),
             (int)ACS712_ZERO_PIN_MV);
    html += "<div class='ip'>IP: " + WiFi.localIP().toString() + " | 上次刷新 <span id='ts'>-</span> | " + String(buf) + "</div>";
    html += "<div class='gray'>(★电压列=GPIO引脚mV（直接万用表对比）。0A窗口/灵敏度请用「两步标定法」实测填入，约每0.4秒 AJAX 刷新)</div>";
  }

  // 分两片输出：U1 (CH00~15) 和 U2 (CH16~31)
  for (uint8_t mux = 0; mux < 2; mux++) {
    html += String(mux == 0 ? "<h3>U1 - CN6/CN7 (CH00~CH15)</h3>"
                            : "<h3>U2 - CN4/CN5 (CH16~CH31)</h3>");
    html += "<table><tr>"
            "<th>通道</th><th>电压(mV)</th><th>电流</th><th>条形</th>"
            "<th>通道</th><th>电压(mV)</th><th>电流</th><th>条形</th>"
            "</tr>";
    uint8_t base = mux * CHANNELS_PER_MUX;
    for (uint8_t row = 0; row < 8; row++) {   // 8 行 × 2 列 = 16 通道
      html += "<tr>";
      for (uint8_t col = 0; col < 2; col++) {
        uint8_t ch = base + row + col * 8;   // 第1列: row+0, 第2列: row+8
        uint32_t mv = g_mv[ch];
        int32_t  ma = pinMvToCurrentMa((int32_t)g_mv_sm[ch]);

        // ★引脚侧电压颜色分级（直接用 GPIO32/33 读数）：
        //   <260mV 灰（浮空/没接）；<ZERO_PIN_MV 黄（负电流/零点以下）；≥ZERO_PIN_MV 红（正电流）
        const char* v_cls = (mv < ACS712_MIN_SIGNAL_PIN_MV) ? "lo" : (mv < ACS712_ZERO_PIN_MV) ? "mi" : "hi";

        // 电流分级：|i|<500mA 灰，±500mA~±10A 黄，±>10A 红
        int32_t absMa = (ma < 0) ? -ma : ma;
        const char* i_cls = (absMa < 500) ? "lo" : (absMa < 10000) ? "mi" : "hi";
        char sign = (ma >= 0) ? '+' : '-';
        int32_t disp_abs = absMa;
        // 显示格式：<1A → "±X mA"，>=1A → "±X.XX A"
        String i_str;
        if (disp_abs < 1000) {
          i_str = String(sign) + String(disp_abs) + "mA";
        } else {
          int a = disp_abs / 1000;
          int frac = (disp_abs % 1000) / 10;   // 保留 2 位小数
          char b[16];
          snprintf(b,sizeof(b),"%c%d.%02dA",sign,a,frac);
          i_str = String(b);
        }

        // 条形：按 ±40A → 0~80A 满量程折算到 0~40px
        //   先偏置 +40A → 0~80A 区间，按比例
        int32_t current_ma_biased = ma + 40000;   // -40A~+40A → 0~80000
        if (current_ma_biased < 0) current_ma_biased = 0;
        if (current_ma_biased > 80000) current_ma_biased = 80000;
        uint8_t barW = (uint8_t)((uint32_t)current_ma_biased * 40UL / 80000UL);

        char chBuf[8];
        snprintf(chBuf, sizeof(chBuf), "CH%02u", ch);

        html += "<td>" + String(chBuf) + "</td>";
        html += "<td class='mv'><span id='v" + String(ch) + "' class='" + String(v_cls) + "'>" + String(mv) + "</span></td>";
        html += "<td class='mv'><span id='i" + String(ch) + "' class='" + String(i_cls) + "'>" + i_str + "</span></td>";
        html += "<td><span class='bar' id='b" + String(ch) + "' style='width:" + String(barW) + "px'></span></td>";
      }
      html += "</tr>";
    }
    html += "</table>";
  }

  html += "<script>"
          "function fmtA(ma){var s=ma>=0?'+':'-';var a=Math.abs(ma);"
          "if(a<1000)return s+a+'mA';"
          "var A=Math.floor(a/1000);var d=Math.floor((a%1000)/10);d=(d<10?'0':'')+d;"
          "return s+A+'.'+d+'A';}"
          "function upd(){"
          "fetch('/json').then(function(r){return r.json();}).then(function(j){"
          "for(var i=0;i<32;i++){"
          "var mv=j.ch[i],ma=j.i_ma[i];"
          "var ve=document.getElementById('v'+i);if(ve){ve.textContent=mv;"
          "ve.className=(mv<260)?'lo':(mv<"+String((int)ACS712_ZERO_PIN_MV)+")?'mi':'hi';}"
          "var ie=document.getElementById('i'+i);if(ie){ie.textContent=fmtA(ma);"
          "ie.className=(Math.abs(ma)<500)?'lo':(Math.abs(ma)<10000)?'mi':'hi';}"
          "var be=document.getElementById('b'+i);if(be){"
          "var w=Math.max(0,Math.min(40,(ma+40000)*40/80000));be.style.width=w+'px';}"
          "}"
          "var t=document.getElementById('ts');if(t){t.textContent=new Date().toLocaleTimeString();}"
          "}).catch(function(){});}"
          "setInterval(upd,400);upd();"
          "</script>";
  html += "</body></html>";
  server.send(200, "text/html; charset=utf-8", html);
}

/**
 * @brief  GET /json  → 简洁 JSON，方便脚本解析
 *         {"ch":[mv0,mv1,...,mv31],"ts":123456}
 */
static void handleJson(void) {
  String out = "{\"ch\":[";
  // ch[] = GPIO 引脚 mV（不再做分压还原，直接和万用表对比）
  for (uint8_t i = 0; i < TOTAL_CHANNELS; i++) {
    if (i != 0) out += ',';
    out += String(g_mv[i]);
  }
  out += "],\"i_ma\":[";
  // i_ma[] = 直接引脚 mV 换算出的电流 mA
  for (uint8_t i = 0; i < TOTAL_CHANNELS; i++) {
    if (i != 0) out += ',';
    out += String(pinMvToCurrentMa((int32_t)g_mv_sm[i]));
  }
  out += "],\"v_zero_pin\":";
  out += String(ACS712_ZERO_PIN_MV);
  out += ",\"sens_pin_mv_per_a_x10\":";
  out += String(ACS712_SENS_PIN_MV_PER_A_X10);
  out += ",\"note\":\"v=引脚mV; i=ACS712源灵敏度66mV/A被÷分压比后直接换算; 全程直接映射\"";
  out += ",\"ts\":";
  out += String(millis());
  out += "}";
  server.send(200, "application/json", out);
}

/**
 * @brief  GET /csv  → 纯 CSV 一行（与串口 CSV 格式一致）
 *         mv0,mv1,...,mv31
 */
static void handleCsv(void) {
  String out;
  out.reserve(256);
  for (uint8_t i = 0; i < TOTAL_CHANNELS; i++) {
    if (i != 0) out += ',';
    out += String(g_mv[i]);
  }
  out += "\r\n";
  server.send(200, "text/plain", out);
}

// ---------------- 采样辅助 ----------------

/**
 * @brief  设置 4067 的通道地址
 * @param  ch  通道号 0~15
 * @note   运行时读取 g_addrPinForS[S0..S3]，可被 /diag 动态切换不用重烧
 */
static void muxSelectChannel(uint8_t ch) {
  for (uint8_t s = 0; s < 4; s++) {
    digitalWrite(g_addrPinForS[s], (ch >> s) & 0x01);
  }
}

/**
 * @brief  对指定 ADC 引脚做过采样取平均
 *         内部会先丢 OVERSAMPLE_DROP_FIRST 次，只用后序采样做平均
 */
static uint16_t adcReadOversampled(uint8_t pin) {
  uint32_t sum = 0;
  uint8_t  cnt = 0;
  for (uint8_t i = 0; i < OVERSAMPLE_DROP_FIRST + OVERSAMPLE_COUNT; i++) {
    uint16_t v = analogRead(pin);
    if (i >= OVERSAMPLE_DROP_FIRST) {   // 前 N 次丢掉
      sum += v;
      cnt++;
    }
  }
  return (uint16_t)(sum / cnt);
}

/**
 * @brief  切完通道后做"丢首样"，刷掉 4067 电荷注入和 ADC S/H 旧值
 *         对两路 ADC 都各执行 MUX_DUMMY_READ_COUNT 次空读并丢弃
 */
static void adcDummyFlush(void) {
  for (uint8_t i = 0; i < MUX_DUMMY_READ_COUNT; i++) {
    (void)analogRead(ADC_PIN_U1);
    (void)analogRead(ADC_PIN_U2);
  }
}

/**
 * @brief  单次读取 32 路全部通道
 *         依次切换 0~15 地址，每次地址读取 U1 + U2 各一次
 *         每通道 3 级时序：[阶段1 RC稳定] → [丢首样] → [阶段2 S/H稳定] → [正式采样]
 */
/**
 * @brief  按单地址执行一次采样并写入 g_raw/g_mv（被 sampleAllChannels 调用）
 *         抽出来便于 lock 模式只采 1 个地址
 */
static void sampleOneAddr(uint8_t addr) {
  muxSelectChannel(addr);
  delay(MUX_SETTLE_PHASE1_MS);
  adcDummyFlush();
  delay(MUX_SETTLE_PHASE2_MS);

  uint8_t idx_u1 = addr;
  uint8_t idx_u2 = addr + CHANNELS_PER_MUX;

  g_raw[idx_u1] = adcReadOversampled(ADC_PIN_U1);
  g_raw[idx_u2] = adcReadOversampled(ADC_PIN_U2);

  // ★用户纠正：直接存 GPIO 引脚 mV（不再做分压还原）——电流计算也直接基于此值
  //   少一次换算 = 少一份舍入误差，量程由 ADC 0~3300mV 天然决定，不会被人为卡窄。
  g_mv[idx_u1] = rawToPinMv(g_raw[idx_u1]);
  g_mv[idx_u2] = rawToPinMv(g_raw[idx_u2]);
}

static void sampleAllChannels(void) {
  if (g_addrLocked) {
    // Lock 模式：只采样锁定的那个地址，给更长的 settle 避免电荷残留影响判断
    // 同时把其他通道缓存先清零，方便一眼看出「只有这一路该有值、其他必须是 0」
    for (uint8_t i = 0; i < TOTAL_CHANNELS; i++) {
      g_raw[i] = 0;
      g_mv[i]  = 0;
    }
    // 连续采 3 次强制刷新：避免切到锁定地址前 100nF 上还带着别的通道电压
    for (uint8_t k = 0; k < 3; k++) {
      sampleOneAddr(g_lockAddr);
    }
    return;
  }

  for (uint8_t addr = 0; addr < CHANNELS_PER_MUX; addr++) {
    sampleOneAddr(addr);
  }
}

/**
 * @brief  串口输出 CSV 帧（每通道=电压mV,电流mA交替，格式 mv0,ma0,...,mv31,ma31）
 *         每 20 帧在 CSV 前插入 `#` 开头的 raw 对照行（前4通道最关键），
 *         用于手动验算：电压mV 应该 = raw × 3300 / 4095，且 ≈ 万用表实测 GPIO 引脚电压。
 *         若两者差别大 → 要么 ADC 引脚/万用表点不对，要么 ADC_ATTEN 衰减设置不一致
 *         （ESP32 analogRead 默认 11dB → 满量程 3.3V，对应我们公式里的 ADC_VREF_MV=3300）。
 */
static uint32_t g_csvFrameCounter = 0;
static void printCsvFrame(void) {
  // 每 20 帧（≈每10秒）在 CSV 前打一行带 # 的 raw 对照（只打前 4 通道最关键的）
  if ((g_csvFrameCounter % 20) == 0) {
    Serial.printf("# [raw对照] CH00 raw=%4u mV=%5lu  |  CH01 raw=%4u mV=%5lu  |  CH02 raw=%4u mV=%5lu  |  CH03 raw=%4u mV=%5lu\r\n",
                  (unsigned)g_raw[0], (unsigned long)g_mv[0],
                  (unsigned)g_raw[1], (unsigned long)g_mv[1],
                  (unsigned)g_raw[2], (unsigned long)g_mv[2],
                  (unsigned)g_raw[3], (unsigned long)g_mv[3]);
    Serial.printf("#     验算: mV = raw × 3300 ÷ 4095     (如: raw=1034 → 1034*3300/4095≈%lumV)\r\n",
                  (unsigned long)(1034UL * 3300UL / 4095UL));
  }
  g_csvFrameCounter++;

  for (uint8_t i = 0; i < TOTAL_CHANNELS; i++) {
    if (i != 0) Serial.print(',');
    Serial.print(g_mv[i]);          // 电压 mV
    Serial.print(',');
    Serial.print(pinMvToCurrentMa((int32_t)g_mv_sm[i]));   // 电流 mA（带符号，直接引脚mV换算）
  }
  Serial.println();
}

/**
 * @brief  调试模式：打印每通道详细信息（raw + 电压mV + 电流mA）
 */
static void printVerbose(uint32_t frameNo) {
  Serial.printf("=== 采样帧 #%lu ===\r\n", frameNo);
  Serial.println(F("[U1 第1片 - CN6/CN7 连接器] (mV=GPIO引脚直接电压，不再还原)"));
  for (uint8_t i = 0; i < CHANNELS_PER_MUX; i++) {
    Serial.printf("  CH%02u  raw=%4u  %5lumV  %5dmA\r\n",
                  i, g_raw[i], g_mv[i], pinMvToCurrentMa((int32_t)g_mv_sm[i]));
  }
  Serial.println(F("[U2 第2片 - CN4/CN5 连接器] (mV=GPIO引脚直接电压，不再还原)"));
  for (uint8_t i = CHANNELS_PER_MUX; i < TOTAL_CHANNELS; i++) {
    Serial.printf("  CH%02u  raw=%4u  %5lumV  %5dmA\r\n",
                  i, g_raw[i], g_mv[i], pinMvToCurrentMa((int32_t)g_mv_sm[i]));
  }
  Serial.println();
}

// ---------------- 初始化 ----------------

void setup() {
  Serial.begin(115200);
  delay(200);

  // 先应用默认地址映射
  setAddrMap(DEFAULT_ADDR_MAP_IDX);

  // 把 4 条候选 GPIO 全部配置为输出（避免切换映射时漏掉 pinMode）
  for (uint8_t i = 0; i < 4; i++) {
    pinMode(ADDR_GPIO_POOL[i], OUTPUT);
    digitalWrite(ADDR_GPIO_POOL[i], LOW);
  }

  pinMode(ADC_PIN_U1, INPUT);
  pinMode(ADC_PIN_U2, INPUT);

  analogReadResolution(12);
  analogSetPinAttenuation(ADC_PIN_U1, ADC_11db);
  analogSetPinAttenuation(ADC_PIN_U2, ADC_11db);

  // 启动信息
  Serial.println(F("\r\n========================================"));
  Serial.println(F("  ESP32 + CD74HCT4067 x2  32CH ADC (WiFi + 诊断)"));
  Serial.printf  ("  地址映射 #%u: S0=GPIO%u  S1=GPIO%u  S2=GPIO%u  S3=GPIO%u\r\n",
                  g_addrMapIdx, g_addrPinForS[0], g_addrPinForS[1], g_addrPinForS[2], g_addrPinForS[3]);
  Serial.println(F("  提示：如通道/电压不对，浏览器打开 /diag 切换其他 23 种映射"));
  Serial.printf  ("  U1 -> ADC : GPIO%u (CH00~CH15)\r\n", ADC_PIN_U1);
  Serial.printf  ("  U2 -> ADC : GPIO%u (CH16~CH31)\r\n", ADC_PIN_U2);
  {
    // 电流映射摘要：以 0A 实测零点 + 实测灵敏度为准
    Serial.printf  ("  电流参数  : ZERO_PIN=%dmV (0A窗口 %d~%d), SENS_PIN=%d.%dmV/A ×10\r\n",
                    (int)ACS712_ZERO_PIN_MV,
                    (int)ACS712_ZERO_WIN_PIN_LO_MV, (int)ACS712_ZERO_WIN_PIN_HI_MV,
                    (int)(ACS712_SENS_PIN_MV_PER_A_X10/10), (int)(ACS712_SENS_PIN_MV_PER_A_X10%10));
    Serial.printf  ("  ★校验公式 : 电压mV = raw × 3300 / 4095（请用计算器验算：raw×3300÷4095 ≈ 万用表实测GPIO电压？）\r\n");
  }
  Serial.printf  ("  采样间隔  : %lums  过采样: %ux\r\n", SAMPLE_INTERVAL_MS, OVERSAMPLE_COUNT);
  Serial.println(F("========================================"));

  // 首帧预热
  sampleAllChannels();

  // WiFi 连接
  bool wifiOk = wifiConnect();

  // HTTP 路由（即使 WiFi 连不上也注册，避免代码分支太散）
  server.on("/",       handleRoot);
  server.on("/json",   handleJson);
  server.on("/csv",    handleCsv);
  server.on("/diag",   handleDiag);
  server.on("/setmap", handleSetMap);
  server.on("/lock",   handleLock);
  server.on("/unlock", handleUnlock);
  server.begin();
  Serial.printf("HTTP: 服务器启动，端口 %u，路由 / /json /csv /diag /setmap /lock /unlock\r\n", HTTP_PORT);
  if (!wifiOk) {
    Serial.println("HTTP: WiFi 未连上，服务不可用；请检查热点后按 RST 重连");
  }
}

// ---------------- 主循环 ----------------

void loop() {
  static uint32_t lastTick         = 0;
  static uint32_t frameNo          = 0;
  static uint32_t verboseCounter   = 0;
  static uint32_t wifiCheckCounter = 0;

  // 1. 处理 HTTP 请求（每次 loop 都要跑，保证响应及时）
  server.handleClient();

  // 2. 按节拍采样
  uint32_t now = millis();
  if (now - lastTick >= SAMPLE_INTERVAL_MS) {
    lastTick = now;
    frameNo++;

    sampleAllChannels();
    emaSmoothVoltage();
    printCsvFrame();

    verboseCounter++;
    if (verboseCounter >= 50) {   // 50 × 200ms = 10 秒输出一次 verbose
      verboseCounter = 0;
      printVerbose(frameNo);
    }
  }

  // 3. 每 5 秒检查一次 WiFi 状态，掉线了自动重连
  wifiCheckCounter++;
  if (wifiCheckCounter >= 500) {   // loop 约 1ms 一次，500 ≈ 5 秒
    wifiCheckCounter = 0;
    if (WiFi.status() != WL_CONNECTED) {
      Serial.println("WiFi: 连接中断，尝试重连...");
      WiFi.disconnect();
      delay(100);
      WiFi.begin(WIFI_SSID, WIFI_PASS);
      uint32_t t0 = millis();
      while (WiFi.status() != WL_CONNECTED && millis() - t0 < WIFI_CONNECT_TIMEOUT_MS) {
        delay(500);
        Serial.print('.');
      }
      if (WiFi.status() == WL_CONNECTED) {
        Serial.printf("\r\nWiFi: 重连成功，IP = %s\r\n", WiFi.localIP().toString().c_str());
      } else {
        Serial.println("\r\nWiFi: 重连失败，5 秒后再试");
      }
    }
  }
}
