# 日志和异常管理系统硬化实施计划

> 文档版本：v1  ·  2026-07-16  ·  待审阅
> 配套背景：[optimization-analysis-2026-07-11.md](file:///d:/Aging/.trae/documents/optimization-analysis-2026-07-11.md) §三、§四

---

## 0. 目标与原则

把系统的可观测性从"主页面 1 个模块有日志"提升到"全模块关键路径可追溯 + 异常处理一致化"，让任何**业务状态机变化、数据流异常、UI 副作用、第三方错误**都能在 `logs/app.log` 中查到完整因果链。

**5 个核心原则**：

1. **每个业务模块都有 logger**：data/services/widgets/ui 全部初始化 `get_logger(__name__)`，命名空间分层清晰
2. **关键路径都打 DEBUG 日志**：state_changed、reading emit、buffer append、countdown 事件、UI 槽函数入口
3. **异常处理有统一模式**：UI 槽用 `@safe_call`；后台线程异常走 `threading.excepthook`；不静默吞 except
4. **错误有 UI 反馈**：CRITICAL 错误自动推状态栏，状态栏徽标计数（已有部分功能）
5. **不破坏现有功能**：纯增量改造，每个模块改动 < 30 行

---

## 1. 现状审计（2026-07-15 实测）

### 1.1 observability 模块自身（完善度 ★★★★★）

| 维度 | 文件 | 状态 |
|------|------|------|
| 多 handler（文件轮转 + 控制台 + Qt signal） | [logger.py:35-62](file:///d:/Aging/app/observability/logger.py#L35-L62) | ✅ |
| 文件按天轮转 + 14 天保留 | [logger.py:36-41](file:///d:/Aging/app/observability/logger.py#L36-L41) | ✅ |
| 控制台 ANSI 颜色 | [logger.py:76-89](file:///d:/Aging/app/observability/logger.py#L76-L89) | ✅ |
| Qt signal 推 UI 状态栏 | [log_signals.py:21-40](file:///d:/Aging/app/observability/log_signals.py#L21-L40) | ✅ |
| 3 个全局异常钩子 | [exception_hook.py:23-77](file:///d:/Aging/app/observability/exception_hook.py#L23-L77) | ✅ |
| safe_call 装饰器 | [safe_call.py:15-59](file:///d:/Aging/app/observability/safe_call.py#L15-L59) | ✅ |
| 命名空间约定（app.data / app.ui / app.system） | [__init__.py:5-7](file:///d:/Aging/app/observability/__init__.py#L5-L7) | ✅ 约定但**只有 1 个模块实际用** |

### 1.2 业务模块 logger 覆盖度（严重不足）

| 模块 | 文件 | logger? | 关键路径有日志? | 评估 |
|------|------|---------|-----------------|------|
| MainWindow | [main_window.py:47](file:///d:/Aging/app/ui/main_window.py#L47) | ✅ 15 处 | 选区 / 按钮 / 倒计时 / 详情页 | 中等 |
| DetailWindow | [detail_window.py:40](file:///d:/Aging/app/ui/detail_window.py#L40) | ⚠️ 3 处（我刚加） | 取消 / 计时 | 缺 |
| **MockDataSource** | [mock_source.py](file:///d:/Aging/app/data/mock_source.py) | ❌ 无 | start/stop/loop/异常 emit | **严重缺** |
| **HistoryBuffer** | [history_buffer.py](file:///d:/Aging/app/data/history_buffer.py) | ❌ 无 | append/snapshot/size | **严重缺** |
| **CellController** | [cell_controller.py](file:///d:/Aging/app/services/cell_controller.py) | ❌ 无 | state_changed.emit / apply() | **严重缺** |
| **CountdownService** | [countdown.py](file:///d:/Aging/app/services/countdown.py) | ❌ 无 | start/expire/cancel | **严重缺** |
| **DataCell** | [data_cell.py](file:///d:/Aging/app/widgets/data_cell.py) | ❌ 无 | mouse / 选中 / 状态 | 缺 |
| **CountdownWidget** | countdown_widget.py | ❌ 无 | 渲染 / 倒计时 | 缺 |
| Charts | charts.py | ❌ 无 | 渲染 / 数据更新 | 缺 |

**关键缺口**：
- **数据流路径**（worker 线程 → emit → 主线程 → buffer → cell/详情页）**完全无日志**
- **业务状态机** 状态变化**完全无日志**（只看 emit 流转，无法回溯）
- **倒计时服务** start/expire/cancel 事件**无日志**

### 1.3 异常处理（不一致）

| 模式 | 用法 | 评估 |
|------|------|------|
| `@safe_call` 装饰器 | 8 个 UI 槽函数 | ✅ 一致 |
| 静默 `try/except pass` | [mock_source.py:70-73](file:///d:/Aging/app/data/mock_source.py#L70-L73) `unsubscribe` | ⚠️ 错误被吞，无日志 |
| Qt 内部异常 | QApplication.notify wrap | ✅ |
| threading 异常 | threading.excepthook | ✅ |
| Python 顶层异常 | sys.excepthook | ✅ |
| **QSS 加载错误** | 内部 try/except | ⚠️ 待审计 |
| **Config 加载错误** | 静态导入 | ⚠️ 启动时崩溃风险 |
| **第三方库调用** | 散落各模块 | ⚠️ 待审计 |

### 1.4 诊断能力（有限）

| 场景 | 可诊断? |
|------|---------|
| 应用启动失败 | ✅（sys.excepthook） |
| worker 线程崩溃 | ✅（threading.excepthook） |
| Qt 事件循环内部异常 | ✅（notify wrap） |
| UI 槽函数异常 | ✅（safe_call） |
| **业务状态机变化** | ❌（无日志） |
| **数据流中断 / 丢帧** | ❌（无日志） |
| **倒计时归零** | ⚠️（仅 main_window 部分） |
| **QSS 错误** | ❌（无捕获） |
| **Config 错误** | ❌（无日志） |

---

## 2. 业务核心层（Layer 1）

### 2.1 目标
让 4 个核心业务模块（mock_source / history_buffer / cell_controller / countdown）每个都有 logger，关键路径都打 DEBUG 日志。

### 2.2 实施项

#### 2.2.1 CellController（[cell_controller.py](file:///d:/Aging/app/services/cell_controller.py)）

| 日志点 | 级别 | 格式 |
|--------|------|------|
| `__init__` | INFO | `"cell controller initialized (total=%d)" % total` |
| `apply()` 入口 | DEBUG | `"apply: action=%s cids=%s" % (action, list(cids))` |
| `apply()` 转移成功 | DEBUG | `"cell %d: %s → %s" % (cid, old.value, new.value)` |
| `apply()` 无效 action | DEBUG | `"apply: no-op for cid %d (state=%s, no transition)" % (cid, old.value)` |
| `state_of()` | DEBUG | （高频，跳过；或仅在 DEBUG 模式下 log） |
| `count_actionable()` | DEBUG | （高频，跳过） |

**改动量**：~15 行

#### 2.2.2 CountdownService（[countdown.py](file:///d:/Aging/app/services/countdown.py)）

| 日志点 | 级别 | 格式 |
|--------|------|------|
| `start()` | DEBUG | `"countdown start: cid=%d total=%ds" % (cid, total_s)` |
| `_on_tick()` | DEBUG | （每秒触发，不打；改为 10 秒或 remain≤60s 才打） |
| `enter_warning` 状态 | INFO | `"countdown warning: cid=%d remain=%ds" % (cid, remain_s)` |
| `expired()` | INFO | `"countdown expired: cid=%d" % cid` |
| `cancel()` | INFO | `"countdown cancelled: cid=%d (was state=%s)" % (cid, e["state"])` |
| `set_duration()` | DEBUG | `"countdown set_duration: cid=%d new_total=%ds" % (cid, new_total_s)` |
| `_stop_timer_if_idle()` | DEBUG | （仅状态变化时打） |

**改动量**：~10 行

#### 2.2.3 MockDataSource（[mock_source.py](file:///d:/Aging/app/data/mock_source.py)）

| 日志点 | 级别 | 格式 |
|--------|------|------|
| `start()` | INFO | `"data source started (channel_count=%d refresh_ms=%d)"` |
| `stop()` | INFO | `"data source stopping (was_running=%s)"` |
| `_loop()` 启动 | DEBUG | `"data source loop running"` |
| `_loop()` 退出 | DEBUG | `"data source loop exited"` |
| `_tick()` | DEBUG | （每 2s 触发一次，**不**打。改为每 30s 采样一次） |
| 静默 except（L70-73） | WARNING | `"data source unsubscribe: %r (slot was not connected)"` |
| 异常 emit 失败 | ERROR | `"reading emit failed: %r"` |

**改动量**：~10 行

#### 2.2.4 HistoryBuffer（[history_buffer.py](file:///d:/Aging/app/data/history_buffer.py)）

| 日志点 | 级别 | 格式 |
|--------|------|------|
| `__init__` | DEBUG | `"history buffer initialized (max_per_channel=%d)"` |
| `append()` | DEBUG | （高频，**不**打；改为每 100 帧采样一次） |
| `snapshot()` 入口 | DEBUG | （高频，不打） |
| buffer overflow 截断 | WARNING | `"history buffer overflow: cid=%d dropped=%d" % (cid, dropped_count)` |

**改动量**：~8 行

### 2.3 数据流追踪增强（关键）

**当前路径**：
```
MockDataSource._tick (worker thread, 2s)
  → reading.emit(reading)
    → MainWindow._dispatch_reading (main thread)
      → HistoryBuffer.append
      → cells[cid-1].update_data (if RUNNING)
      → detail.on_reading (if any)
```

**问题**：每 2s × 72 channel = 36 reading/s，无任何日志可看。

**方案**：**采样日志 + 关键事件日志**

| 事件 | 级别 | 格式 |
|------|------|------|
| 数据源启动 | INFO | （见 2.2.3） |
| 数据源停止 | INFO | （见 2.2.3） |
| **每 30s 一次**采样 | INFO | `"data source tick sample: cid=%d ts=%d current=%.2f" % (sample_cid, now, currents[0])` |
| buffer overflow | WARNING | （见 2.2.4） |
| cell 状态转移 | INFO | （见 2.2.1） |
| 倒计时归零 | INFO | （见 2.2.2） |

**改动量**：~15 行（含 sample logger）

### 2.4 验证方法
- 重启应用，看 `logs/app.log`：
  - 启动时有 `cell controller initialized` / `countdown service ready` / `data source started`
  - 每 30s 有 `data source tick sample: cid=N ...`
  - 启动 1 个 cell → 看到 `cell N: stopped → running` + `countdown start: cid=N`
  - 等到倒计时归零（缩短 duration 到 30s 测试）→ 看到 `countdown expired: cid=N`

---

## 3. 异常一致层（Layer 2）

### 3.1 目标
所有 UI 槽函数都用 `@safe_call`；所有 `try/except` 不静默吞；QSS/config 加载错误有捕获；第三方库错误有捕获。

### 3.2 实施项

#### 3.2.1 safe_call 扩展（[safe_call.py](file:///d:/Aging/app/observability/safe_call.py)）

| 改进点 | 描述 |
|--------|------|
| 增强 on_error 钩子 | 让 `on_error` 可以恢复 UI 状态（已有部分） |
| 增加 `level` 参数 | `safe_call(..., level=LogLevel.ERROR)`，默认 ERROR，DEBUG 路径可用 WARNING |
| 增强 _safe_repr | 处理 numpy 数组、Qt 对象（避免 repr 崩溃） |

**改动量**：~15 行

#### 3.2.2 safe_call 应用补全

| 模块 | 当前 | 目标 |
|------|------|------|
| main_window.py | 8 个槽 | 8 个 ✅（保持） |
| detail_window.py | 1 个 | 补全 `on_reading` / `update_state` / `closeEvent` / `resizeEvent` 等 → 4-5 个 |
| DataCell | 0 个 | 补 `mousePressEvent` / `mouseDoubleClickEvent` / `set_selected` / `set_status` → 4 个 |
| Charts widget | 0 个 | 补 `_refresh_charts` / `_position_legend` / `update_data` → 3 个 |
| CountdownWidget | 0 个 | 补 `_on_finished` / `_on_started` / `_on_ticked` → 3 个 |

**改动量**：~20 行

#### 3.2.3 静默 except 改革（[mock_source.py:70-73](file:///d:/Aging/app/data/mock_source.py#L70-L73)）

**当前**：
```python
def unsubscribe(self, slot) -> None:
    try:
        self.reading.disconnect(slot)
    except (TypeError, RuntimeError):
        pass
```

**改为**：
```python
def unsubscribe(self, slot) -> None:
    try:
        self.reading.disconnect(slot)
    except (TypeError, RuntimeError) as e:
        _log.warning("unsubscribe: slot=%r err=%r (already disconnected?)",
                     slot, e)
```

**审计范围**：
- 搜索所有 `except ... pass` → 4-6 处需改革
- 搜索 `except ...: continue/break` → 1-2 处需改革

**改动量**：~8 行

#### 3.2.4 QSS 加载错误捕获（[Main.py:36](file:///d:/Aging/Main.py#L36)）

**当前**：
```python
app.setStyleSheet(build_stylesheet(DEFAULT_TOKENS))
```

**风险**：如果 `build_stylesheet` 内部抛异常，应用启动失败。

**改为**：
```python
try:
    app.setStyleSheet(build_stylesheet(DEFAULT_TOKENS))
    _log.info("qss applied (%d bytes)", len(app.styleSheet()))
except Exception as e:
    _log.critical("qss load failed: %r\n  app will run with default style",
                  e, exc_info=True)
    # 兜底：不应用 QSS，让应用以默认样式启动
```

**改动量**：~8 行

#### 3.2.5 Config 错误处理（[config.py](file:///d:/Aging/app/core/config.py)）

**当前**：静态常量，导入时崩溃会传上去。

**风险**：如果用户改了 config 拼错常量名（如 `LOG_LVEL`），启动时 NameError，整个应用起不来。

**方案**：把 config 改为 dataclass + 启动时验证；或加 `__getattr__` 容错（**不推荐**，太灵活）。

**评估**：先**不**改 config 结构（避免大改），但**加 logger 记录**所有 `config.X` 访问（在 `config.py` 末尾加 1 个 dump 验证函数）。

**改动量**：~10 行

### 3.3 错误 UI 反馈增强

**当前已有**：
- 状态栏 error badge（[config.py:56](file:///d:/Aging/app/core/config.py#L56) `LOG_ERROR_BADGE_MAX`）
- QtLogHandler 把 WARNING+ 推到 UI

**增强**：
- CRITICAL 错误弹 QMessageBox（带 traceback 折叠 + "重试"/"退出"/"忽略"按钮）
- 错误计数达到阈值（如 10）时弹 QMessageBox 询问是否重启

**改动量**：~25 行

### 3.4 验证方法
- **safe_call 验证**：在 `mousePressEvent` 中加 `raise RuntimeError("test")`，看是否被 safe_call 捕获 + log + 状态栏提示
- **静默 except 验证**：调用 `unsubscribe(not_connected_slot)`，看 WARNING 日志
- **QSS 错误验证**：临时改 `tokens.py` 加个非法字符，看启动是否 CRITICAL log + 兜底启动

---

## 4. 新增功能（Layer 3，可选）

### 4.1 日志查看器（[Main.py](file:///d:/Aging/Main.py)）

**功能**：菜单栏"工具"→"查看日志"，调起系统默认文本编辑器打开 `logs/app.log`（Windows: `notepad`）。

**改动量**：~20 行

### 4.2 日志轮转增强

**当前**：[logger.py:36-41](file:///d:/Aging/app/observability/logger.py#L36-L41) 按天轮转，保留 14 天。

**增强**：
- 文件大小轮转（`RotatingFileHandler`，10MB × 5 文件）
- 压缩旧日志（`gzip`）

**改动量**：~10 行

### 4.3 结构化日志

**当前**：`%(message)s` 纯字符串。

**增强**：可选用 JSON formatter，让日志可被 ELK/Loki 解析。

**改动量**：~15 行

### 4.4 性能监控

**功能**：关键方法执行时间（如 `_dispatch_reading` / `_refresh_charts`）自动记录，超过阈值 WARNING。

**改动量**：~30 行

---

## 5. 实施顺序

按"先核心后增强"原则，5 个 Phase：

### Phase 1（0.5h）业务核心层 · 4 个模块加 logger
- [ ] cell_controller.py：__init__ + apply() + state_changed
- [ ] countdown.py：start/expire/cancel
- [ ] mock_source.py：start/stop + 静默 except 改革
- [ ] history_buffer.py：__init__ + overflow warning
- 验证：跑应用，看启动日志 + 操作日志

### Phase 2（0.3h）数据流采样
- [ ] mock_source.py：每 30s 采样一条 INFO 日志
- [ ] history_buffer.py：每 100 帧采样一条
- 验证：跑 1 分钟，看 `data source tick sample` 出现频率

### Phase 3（0.3h）safe_call 扩展应用
- [ ] detail_window.py：补 4-5 个
- [ ] data_cell.py：补 4 个
- [ ] charts.py / countdown_widget.py：各补 2-3 个
- 验证：在某槽函数 raise RuntimeError，确认捕获

### Phase 4（0.3h）静默 except 改革
- [ ] mock_source.py：L70-73
- [ ] 全局搜索其他静默 except
- 验证：调 unsubscribe(not_connected)，看 WARNING 日志

### Phase 5（0.3h）QSS / Config 错误捕获
- [ ] Main.py：QSS 加载 try/except
- [ ] config.py：dump 验证
- 验证：故意改坏 QSS，确认兜底启动

**总预估：1.7h**（纯增量，无破坏性改动）

---

## 6. 风险与回滚

### 6.1 风险

| 风险 | 等级 | 缓解 |
|------|------|------|
| 日志量暴增（每 2s 36 readings） | 中 | 采样日志，每 30s/100 帧一次 |
| safe_call 静默吞关键异常 | 中 | 已有 on_error 钩子，统计 ERROR 计数 |
| QSS 兜底导致 UI 显示错乱 | 低 | 异常时记录到 _log.critical，用户看到默认样式 + 日志 |
| Config dump 失败影响启动 | 低 | 放在 try/except 内，失败仅 WARNING |

### 6.2 回滚

每个 Phase 独立，可单独回滚：
- Phase 1-4：删 logger 初始化 + DEBUG 日志（保留 import）
- Phase 5：删 try/except 包裹

---

## 7. 验证方法汇总

| 验证项 | 命令 / 操作 | 期望 |
|--------|-------------|------|
| 启动日志完整 | 启动应用 + `tail logs/app.log` | 看到 cell controller / countdown / data source 启动 INFO |
| 数据流追踪 | 跑 1 分钟 + tail | 看到 2 条 `data source tick sample`（30s 间隔） |
| 状态机可追溯 | 启停 cell_1 | 看到 `cell 1: stopped → running` + `countdown start: cid=1` |
| 倒计时归零 | 改 duration 到 30s | 看到 `countdown warning: cid=1` (≤60s) + `countdown expired: cid=1` |
| 静默 except 改革 | `unsubscribe(not_connected)` | WARNING 日志 |
| QSS 兜底 | 故意改坏 tokens.py | CRITICAL 日志 + 应用启动（默认样式） |
| safe_call 捕获 | 临时 raise RuntimeError | ERROR 日志 + 状态栏提示 + 不崩 |

---

## 8. 决策点

实施前需要确认：
- [ ] Phase 5（QSS 兜底）是否需要？如不实施，QSS 错误会让应用直接崩溃
- [ ] Layer 3（新增功能）是否纳入？默认 **不**做
- [ ] 数据流采样间隔（30s / 60s / 100 帧）哪个合适？
- [ ] 是否加错误 UI 反馈（CRITICAL 弹 QMessageBox）？默认 **不**做
- [ ] Phase 1-5 顺序是否合理？

---

## 9. 后续

完成 Layer 1-2 后，可考虑：
- 全模块覆盖层（每个 widget 都有 logger + 关键事件）
- pytest 单元测试（冻结现有行为）
- 性能监控（关键方法执行时间）
- 结构化日志（JSON / ELK 集成）

