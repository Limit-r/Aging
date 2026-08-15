# 硬编码集中治理 · 阶段收口完成记录

> **用途**：本文件是 [hardcode-management-design.md](file:///d:/Aging/.trae/documents/hardcode-management-design.md) 设计方案的**最终完成记录**（WHAT + WHY + 验证结果 + 后续维护建议）
> **版本**：v1  ·  2026-07-20  ·  收口完成
> **基线**：方案 §1-§6 + 5 个阶段（4-A / 4-B / 4-C / 4-D / 5 + closeout）的实际执行结果

---

## 0. 文档约定

- **状态快照日期**：2026-07-20（收口 commit `b615649` 提交时间 10:36:15）
- **扫描基线**：`python tests/run_config_registry_scan.py --strict-critical` → 0 hits
- **验证基线**：`python tests/verify_phase5.py` → py_compile 15/15 + import 15/15 + 集成 4/4 全通过
- **冒烟基线**：`python tests/smoke_phase5.py` → event loop rc=0（offscreen 启动 1s 全通过）

---

## 1. 设计达成度（与原方案 §2 对照）

### 1.1 三件套边界（§2.2 职责清单）

| 文件 | 设计目标 | 实际达成 | 验证手段 |
|------|----------|----------|----------|
| **tokens.py** | 视觉常量单一来源 | ✅ Colors (4 大类 75+ 项) + Fonts (4) + FontSizes (17) + Sizing (28) + `rgba()` / `rgba_from_tuple()` 工具 | `import app.core.tokens` + token 引用计数 100%+ |
| **config.py** | 业务常量单一来源 | ✅ 保留 GRID_ROWS/COLS、REFRESH_MS、LOG_ERROR_BADGE_MAX 等业务数字 | config_registry 扫描无业务数字泄漏到非业务文件 |
| **labels.py** | 文本常量单一来源 | ✅ WINDOW_TITLE / STATUS_ONLINE_TEXT / HUD_*_TITLE / MAIN_BUTTON_LABELS / DETECTION_STATE_PRESENTATION 全部集中 | config_registry `user_text` 类别 0 hits |
| **config_registry.py** | 治理 + 启动期扫描验证 | ✅ 9 类别扫描 + 白名单（stylesheet.py 合并入口）+ pre-commit `--strict-critical` 阻塞 | `run_config_registry_scan.py --strict-critical` 退出 0 |

### 1.2 关键决策（§2.3）

| # | 决策 | 状态 |
|---|------|------|
| 1 | 三件套零交叉 | ✅ **零交叉**（所有 widget 内的颜色/数字/文本均走三件套） |
| 2 | templates.py 是 QSS 唯一入口 | ✅ **零 widget 内 setStyleSheet**（floaters.py B 阶段 3 处全部迁出，data_cell.py A 阶段迁出） |
| 3 | QSS 动态注入用属性选择器 | ✅ **5 种 LED 状态全用 `[ledState="xxx"]` 选择器**（B 阶段遗留 3 处全部改造） |
| 4 | 同色多 alpha 用 `rgba()` 工具 | ✅ **0 处裸 `rgba(R, G, B, A)` 字面量**（除豁免文件） |
| 5 | 数字字面量按维度归 Sizing | ✅ 26 处内联数字（nav_bar / floaters / detail_page / current_page / data_cell）全部归 Sizing tokens |
| 6 | 文本字面量按维度归 labels | ✅ 全部用户可见中文走 `labels.X` |
| 7 | config_registry 启动期扫描 | ✅ 9 类别（color_hex / color_rgba / inline_qss / numeric / user_text / **font_family / qss_property / sleep_lit / path_lit**） |
| 8 | pre-commit 严格模式阻塞 | ✅ `--strict-critical` 退出 1 阻断 commit |
| 9 | DETECTION_STATE_PRESENTATION 集中映射 | ✅ 3 状态（online/anomaly/offline）合并到 `labels.DETECTION_STATE_PRESENTATION` dataclass |
| 10 | CellController `_pending_countdown` 清理 | ✅ 改 `apply(countdown_seconds=...)` 参数注入 |

---

## 2. 5 个阶段执行回顾

### 2.1 阶段总览

| 阶段 | 主题 | 关键文件 | commit |
|------|------|----------|--------|
| **4-A** | 颜色集中（templates.py 内裸 hex/rgba → tokens） | tokens.py / templates.py | `85821a0` |
| **4-B** | 浮窗内联 QSS → templates（nav_bar / floaters / reset_button） | nav_bar.py / floaters.py / templates.py | `d82787f` + `ce431c3` |
| **4-C** | 26 处内联数字字面量 → Sizing tokens | nav_bar.py / floaters.py / detail_page.py / current_page.py / data_cell.py / tokens.py | `f1f65f4` |
| **4-D** | 用户可见中文 → labels + 新增 config_registry 验证器 | labels.py / data_cell.py / config_registry.py | `540bd5a` |
| **5**   | 扫描类别扩展到 9 个 + 5 项 audit 遗留 + pre-commit | config_registry.py / tokens.py / cell_controller.py / cell_ui_manager.py | `601aa1f` |
| **closeout** | 3 项 E 阶段遗留收口 | config_registry.py / tokens.py / floaters.py / data_cell.py / templates.py / stylesheet.py | `b615649` |

### 2.2 closeout 阶段 3 项收口细节

| 收口项 | 来源 | 改动 |
|--------|------|------|
| **收口-1**：data_cell.py "● ON" → `labels.STATUS_ONLINE_TEXT` | 4-D 阶段 1 处遗漏 | [data_cell.py:144](file:///d:/Aging/app/widgets/data_cell.py#L144) |
| **收口-2**：config_registry 移除 templates.py 豁免 | 5 阶段扫描豁免冗余 | [config_registry.py](file:///d:/Aging/app/core/config_registry.py) `STYLE_FILES` 只剩 `stylesheet.py` |
| **收口-3**：floaters.py 3 处动态 setStyleSheet 迁 QSS 属性选择器 | B 阶段 3 处未根治 | 新增 `tokens.rgba_from_tuple()` 工具 + `templates.led_dot()` 模板（5 种状态）+ `floaters.py` 改 `setProperty("ledState", state)` + unpolish/polish 刷新 |

---

## 3. 最终状态（2026-07-20 10:36 实测）

### 3.1 启动期扫描结果

```text
$ python tests/run_config_registry_scan.py --strict-critical
======================================================================
config_registry 启动期扫描验证 (root=app)
======================================================================
======================================================================
TOTAL = 0 (CRITICAL=0 WARNING=0 INFO=0)
======================================================================
$ echo $?
0
```

**全工程 9 类别 0 命中**，唯一豁免 = `app/styles/stylesheet.py`（QSS 合并入口，仅做拼接）。

### 3.2 验证套件结果

| 验证项 | 结果 | 详情 |
|--------|------|------|
| py_compile | ✅ 15/15 | 所有 app/ 模块语法正确 |
| import smoke | ✅ 15/15 | 所有 app/ 模块导入成功 |
| 集成测试 | ✅ 4/4 | PRESENTATION 3 状态 + CellUIManager + CellController + scan |
| offscreen smoke | ✅ rc=0 | HomePage constructed + event loop 1s + DemoDataSource 启动 |

### 3.3 全工程 setStyleSheet 数量

| 位置 | 数量 | 备注 |
|------|------|------|
| app/styles/stylesheet.py | 1 | QSS 合并入口（**唯一豁免**） |
| **其他位置** | **0** | 全部走 QSS 模板 + `setProperty` 动态属性 |

### 3.4 全工程 setProperty 动态属性

| widget | 动态属性 | 用途 |
|--------|----------|------|
| QFrame `floaterPanel` | `side` (right/bottomright/ledstrip) | 浮窗边框色按侧切换 |
| QWidget `dataCell` | `status` (online/anomaly/offline/no_data) | 单元状态色 |
| QWidget `dataCell` | `hovered` (true) | hover 边框色 |
| QWidget `dataCell` | `selected` (true) | 选中边框色 |
| QWidget `dataCell` | `expired_pending` (on/off) | 倒计时归零闪烁 |
| QLabel `ledDot` | `ledState` (offline/running/paused/alert/warning) | LED 状态色（**closeout 新增**） |

---

## 4. 收口后维护指南

### 4.1 新增 widget 时的硬编码守则

1. **颜色** → 写入 `tokens.Colors` 命名常量，绝不在 widget / template 内出现 `#hex` 或 `rgba(R, G, B, A)`
2. **数字**（尺寸/间距/最小宽高）→ 写入 `tokens.Sizing` 命名常量；**业务数字**写入 `config.X`
3. **文本**（中文/按钮/标签）→ 写入 `labels.X`
4. **同色多 alpha** → 用 `tokens.rgba(color, alpha)` 工具
5. **动态颜色切换** → 用 `setProperty("xxx", "yyy")` + QSS 属性选择器 `[xxx="yyy"]`

### 4.2 pre-commit 使用

```bash
# 任何修改后跑一遍（默认仅报告）
python tests/run_config_registry_scan.py

# 严格模式（命中 CRITICAL 即退出 1）
python tests/run_config_registry_scan.py --strict-critical
```

### 4.3 修改后回滚锚点

| 阶段 | 回滚命令 |
|------|----------|
| closeout (3 项遗留) | `git revert b615649` |
| E 阶段（5 项 audit） | `git revert 601aa1f` |
| D 阶段（labels + validator） | `git revert 540bd5a` |
| C 阶段（Sizing 26 处） | `git revert f1f65f4` |
| B 阶段（templates 迁出） | `git revert d82787f ce431c3` |
| A 阶段（颜色集中） | `git revert 85821a0` |

### 4.4 已知豁免文件清单

| 文件 | 豁免原因 | 维护时注意事项 |
|------|----------|----------------|
| `app/styles/stylesheet.py` | QSS 合并入口（仅 `T.xxx(tokens)` 拼接） | 不可添加裸 QSS 字符串；新增模板时仅追加 `T.xxx(tokens)` 调用 |

---

## 5. 设计方案对照审计

### 5.1 §1.1 硬编码泄漏地图（2026-07-18 实测）→ 收口后

| 类别 | 原文件 / 行 | 原硬编码 | 收口后状态 |
|------|-------------|----------|------------|
| A 类（templates rgba） | templates.py:42,66,93,111,160,196,284,287,425,440,460-480,546,550 | 14+ 处 rgba 字面量 | ✅ 全部走 `tokens.rgba()` 工具或命名常量 |
| A 类（templates 裸 hex） | templates.py:441-442,693,698 | 4 处 #ffd0d8/#ff5a78/#ffd166/#ff7090 | ✅ 全部迁入 `tokens.Colors.TEXT_DANGER_LIGHT` 等 |
| B 类（UI 内联 QSS） | nav_bar.py:52,65,96-119 + floaters.py:38,90-101,312-322 | 18 处 setStyleSheet | ✅ nav_bar 0 处；floaters 0 处（closeout 收口 3 处） |
| C 类（数字字面量） | main_3d / home_page / detail_page 等 | ~20+ 处尺寸数字 | ✅ 26 处全部归 Sizing tokens（4-C 阶段） |
| D 类（文本分散） | home_diff / show / Main.py | "● SYSTEM ONLINE" 等 | ✅ 全部归 `labels.X`（4-D 阶段） |

### 5.2 §1.2 同色多 alpha 重复模式 → 收口后

```text
# 0,191,255（cyan）→ 4 个不同 alpha 重复
原: rgba(0, 191, 255, 40/50/60/25) 散布 4 处
收: 全部走 rgba(c.BORDER_PRIMARY, 40) / rgba(c.BORDER_PRIMARY, 50) 等

# 74,217,255（淡 cyan）→ 6 个不同 alpha 重复
原: rgba(74, 217, 255, 0/80/140/...) 散布 6 处
收: 命名常量 c.GLOW_LIGHT_CYAN_LOW/MID/HIGH/BORDER/ALERT 直接引用
```

### 5.3 §1.3 现有 token 体系定位 → 收口后

| 模块 | 原定位 | 实际定位（收口后） |
|------|--------|---------------------|
| tokens.py | 视觉常量单一来源 | **完全达成**：Colors 4 大类 75+ 项 + Fonts + FontSizes + Sizing + `rgba()` + `rgba_from_tuple()` |
| config.py | 业务常量单一来源 | **完全达成**：业务数字 0 泄漏到 widget |
| labels.py | 文本常量单一来源 | **完全达成**：DETECTION_STATE_PRESENTATION dataclass 集中 3 状态映射 |
| templates.py | QSS 入口 | **完全达成**：唯一 QSS 字符串生成处（stylesheet.py 仅做拼接） |
| config_registry.py | 启动期验证 | **完全达成**：9 类别扫描 + pre-commit 集成 |

---

## 6. 后续改进建议（非必须）

### 6.1 短期（1-2 周可做）

- 把 `pre-commit-config.yaml.example` 接入团队实际 pre-commit 流程
- 在 `Main.py` 启动时调用 `config_registry.scan_and_report()` 输出 INFO 级别日志（现状已通过 `smoke_phase5.py` 验证可扫描）

### 6.2 中期（1-2 月可做）

- 把 config_registry 扫描从 9 类别扩展到注释密度 / 异常吞噬等代码质量维度
- 引入 `tokens.export_diff(old_tokens, new_tokens)` 工具，在 PR review 时可视化 token 变化

### 6.3 长期

- tokens 化迁移到独立 `design-tokens.json` 文件（与 Figma Tokens 同步），运行时读取（牺牲 `frozen=True` 的运行时不可变性）
- config_registry 升级为 LSP 服务（IDE 实时标注硬编码）

---

## 7. 收口签字

| 阶段 | 完成 commit | 设计目标达成 | 验证通过 |
|------|-------------|--------------|----------|
| 4-A 颜色集中 | 85821a0 | ✅ | ✅ |
| 4-B 浮窗 QSS 迁出 | d82787f + ce431c3 | ✅ | ✅ |
| 4-C Sizing 26 处 | f1f65f4 | ✅ | ✅ |
| 4-D labels + validator | 540bd5a | ✅ | ✅ |
| 5 扫描扩展 + 5 audit | 601aa1f | ✅ | ✅ |
| **closeout 3 项遗留** | **b615649** | **✅** | **✅** |

**最终结论**：[hardcode-management-design.md](file:///d:/Aging/.trae/documents/hardcode-management-design.md) 设计方案 §1-§6 **100% 达成**。

- 启动期 config_registry 9 类别扫描：**0 hits**
- templates.py 路径已**不在豁免**，全工程唯一豁免 = stylesheet.py 合并入口
- floaters.py 0 处 setStyleSheet；data_cell.py 0 处硬编码中文
- tokens.py rgba 工具从 1 个扩到 2 个（hex → rgba + tuple → rgba）
- templates.py 新增 1 个 led_dot 模板函数

**py_compile 15/15 OK · import smoke 15/15 OK · 集成 4/4 OK · offscreen smoke rc=0**
