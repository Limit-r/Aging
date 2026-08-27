"""每 cell 倒计时服务（wall-clock timer）。

设计要点
--------
- 由 MainWindow 持有，跨 cell 共享 1 个 QTimer（1s tick），
  避免开 72 个独立 timer。
- 状态：
    idle    ─start→   running  ─tick→ running / warning  ─remain≤0→ expired
                                                  ─cancel→ idle
- 信号：
    started(cid, total_s)        # 启动/重置
    ticked(cid, remain_s, total_s)  # 每秒
    entered_warning(cid, remain_s)  # 进入 ≤60s 区间
    expired(cid)                 # 归零
    cancelled(cid)               # 用户取消
    finished(cid)                # 归零或取消（统一收尾信号）

线程安全
--------
所有 API 均在主线程调用（UI 槽函数），QTimer 也在主线程触发，
因此无需锁；不暴露给 worker 线程。

与 cell 状态机的关系
-------------------
- 服务独立于 DetectionState（STOPPED/RUNNING/PAUSED）。
  暂停 cell 不会暂停倒计时；这是有意的：倒计时代表"老化计划时长"。
- 归零时仅 emit expired(cid)，由 MainWindow 决定是否 stop cell
  以及把 cell 标 ANOMALY（红边）。
"""

from typing import Dict, Optional

from PyQt5.QtCore import QObject, QTimer, pyqtSignal

from app.core import config
from app.observability import get_logger, narrative
from app.observability.log_signals import LogLevel


_log = get_logger("app.services.countdown")


STATE_IDLE = "idle"
STATE_RUNNING = "running"
STATE_WARNING = "warning"
STATE_EXPIRED = "expired"


class CountdownService(QObject):
    """每 cell 倒计时服务（单实例，MainWindow 持有）。"""

    # 信号：channel_id + 数值
    started = pyqtSignal(int, int)            # cid, total_s
    ticked = pyqtSignal(int, int, int)        # cid, remain_s, total_s
    entered_warning = pyqtSignal(int, int)    # cid, remain_s
    expired = pyqtSignal(int)                 # cid
    cancelled = pyqtSignal(int)               # cid
    finished = pyqtSignal(int)                # cid（expired/cancelled 都会发）

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        # cid -> {state, total_s, remain_s}
        self._entries: Dict[int, Dict] = {}
        self._timer = QTimer(self)
        self._timer.setInterval(config.COUNTDOWN_TICK_MS)
        self._timer.timeout.connect(self._tick)
        self._running_cids: set = set()  # 只存正在跑的 cid，避免全表扫描
        self._paused_cids: set = set()   # 已暂停的 cid（remain_s 冻结不递减）

    # -- 查询 API -------------------------------------------------------------
    def state(self, cid: int) -> str:
        e = self._entries.get(cid)
        return e["state"] if e else STATE_IDLE

    def is_running(self, cid: int) -> bool:
        return cid in self._running_cids

    def is_paused(self, cid: int) -> bool:
        """该 cid 是否处于暂停冻结（倒计时停走但仍在 running）。"""
        return cid in self._paused_cids

    def remaining(self, cid: int) -> int:
        e = self._entries.get(cid)
        return e["remain_s"] if e else 0

    def total(self, cid: int) -> int:
        e = self._entries.get(cid)
        return e["total_s"] if e else 0

    def running_cids(self) -> list:
        return sorted(self._running_cids)

    # -- 写 API ---------------------------------------------------------------
    def start(self, cid: int, total_s: int) -> None:
        """启动/重置某 cell 的倒计时。

        - 若已有 running 倒计时则重置为新的 total_s（保持简单一致）
        - 若 total_s <= 0：忽略

        日志策略：cell_controller.apply() 已聚合成功转移 event（含 cids 列表），
        main_window 的 batch_action event 包含 duration 信息，
        本方法不重复打 per-cell DEBUG。倒计时生命周期事件（timer start/stop /
        entered warning / tick expired）保留 DEBUG 记录。
        """
        if total_s <= 0:
            _log.warning(
                "event=countdown_start_invalid cid=CH-%s total=%s reason=non_positive",
                cid, total_s,
            )
            return
        total_s = int(total_s)
        prev_state = self.state(cid)
        self._paused_cids.discard(cid)  # 新一次 start 视为非暂停
        self._entries[cid] = {
            "state": STATE_RUNNING,
            "total_s": total_s,
            "remain_s": total_s,
        }
        self._running_cids.add(cid)
        if not self._timer.isActive():
            self._timer.start()
            narrative.event(
                "countdown_timer_started",
                level=LogLevel.DEBUG,
                channels=sorted(self._running_cids),
                note=f"QTimer 启动，当前共 {len(self._running_cids)} 个 cell 倒计时中",
            )
        self.started.emit(cid, total_s)
        self.ticked.emit(cid, total_s, total_s)
        # 不再 per-cell 打 DEBUG：cell_controller 的 cell_state_apply event
        # + main_window 的 batch_action event 已覆盖。timer_started 仍打 1 条。

    def cancel(self, cid: int) -> None:
        """取消某 cell 的倒计时。

        日志策略：同 start() — cell_controller.apply() 已聚合，
        本方法不重复打 per-cell DEBUG。
        """
        if cid not in self._entries:
            _log.debug("event=countdown_cancel cid=CH-%s reason=no_entry note=无活跃倒计时", cid)
            return
        e = self._entries[cid]
        if e["state"] in (STATE_IDLE, STATE_EXPIRED):
            _log.debug("event=countdown_cancel cid=CH-%s state=%s reason=terminal_state",
                       cid, e["state"])
            return
        prev_remain = e["remain_s"]
        e["state"] = STATE_IDLE
        e["remain_s"] = 0
        self._running_cids.discard(cid)
        self._paused_cids.discard(cid)
        self.cancelled.emit(cid)
        self.finished.emit(cid)
        self._stop_timer_if_idle()
        # 不再 per-cell 打 DEBUG：cell_controller 的 cell_state_apply event 已覆盖。

    def pause(self, cid: int) -> None:
        """暂停某 cell 的倒计时（remain_s 冻结，不再随 tick 递减）。

        仅在存在 running(非已暂停) 的倒计时时生效；已暂停则幂等。
        倒计时与 cell 状态机解耦：本方法是用户主动"暂停检测"与之联动时调用，
        由 current_page 在 pause 动作下统一触发。
        """
        if cid in self._entries and cid in self._running_cids \
                and cid not in self._paused_cids:
            self._paused_cids.add(cid)
            _log.debug("event=countdown_paused cid=CH-%s remain_s=%s",
                       cid, self._entries[cid]["remain_s"])

    def resume(self, cid: int) -> None:
        """恢复某 cell 的倒计时（继续递减）。仅在已暂停时生效；否则幂等。"""
        if cid in self._paused_cids:
            self._paused_cids.discard(cid)
            _log.debug("event=countdown_resumed cid=CH-%s remain_s=%s",
                       cid, self._entries.get(cid, {}).get("remain_s", 0))

    def set_duration(self, cid: int, new_total_s: int) -> None:
        """详情页 spinbox 调整：rescale 倒计时。

        running 中：按当前 remain/total 比例缩放 remain_s
        idle/expired：不起作用（仅在 detail 页有 spinbox 的场景下手动调用 start）
        """
        if new_total_s <= 0:
            _log.warning("set_duration(cid=%s, %s): 无效 total_s，忽略",
                         cid, new_total_s)
            return
        e = self._entries.get(cid)
        if e is None or e["state"] != STATE_RUNNING:
            _log.debug("set_duration(cid=%s, %s): 当前无 running 倒计时，忽略",
                       cid, new_total_s)
            return
        old_total = e["total_s"]
        old_remain = e["remain_s"]
        consumed = max(old_total - old_remain, 0)
        # 已消耗时间保持，新总时长 = max(已消耗 + 1, new_total_s)
        new_total = max(new_total_s, consumed + 1)
        e["total_s"] = new_total
        e["remain_s"] = max(new_total - consumed, 1)
        if e["remain_s"] <= config.COUNTDOWN_WARNING_THRESHOLD_S:
            e["state"] = STATE_WARNING
            self.entered_warning.emit(cid, e["remain_s"])
        self.ticked.emit(cid, e["remain_s"], e["total_s"])
        # DEBUG 而非 INFO：set_duration 是单 cell 调整，但用户从主流程看不到 diff，降 DEBUG 配合详情页 INFO
        _log.debug(
            "set_duration cid=%s: %s → %s (consumed=%s, remain_s=%s)",
            cid, old_total, new_total, consumed, e["remain_s"],
        )

    # -- 内部 ----------------------------------------------------------------
    def _tick(self) -> None:
        if not self._running_cids:
            self._timer.stop()
            _log.debug("tick: 无 running cell, timer stopped")
            return
        # 拷贝一份避免迭代中修改
        expired_cids: list[int] = []
        warning_entered: list[tuple[int, int]] = []  # (cid, remain_s)
        for cid in list(self._running_cids):
            e = self._entries.get(cid)
            if e is None or e["state"] not in (STATE_RUNNING, STATE_WARNING):
                self._running_cids.discard(cid)
                _log.debug("tick cid=%s: 状态 %s 异常, 从 running 移除",
                           cid, e["state"] if e else None)
                continue
            if cid in self._paused_cids:
                # 暂停：冻结剩余时间，不递减、不结束（仍在 running 列表中保持 timer 呼吸）
                continue
            e["remain_s"] -= 1
            if e["remain_s"] <= 0:
                # expired
                e["remain_s"] = 0
                e["state"] = STATE_EXPIRED
                self._running_cids.discard(cid)
                self.expired.emit(cid)
                self.finished.emit(cid)
                expired_cids.append(cid)
            else:
                if (e["state"] != STATE_WARNING
                        and e["remain_s"] <= config.COUNTDOWN_WARNING_THRESHOLD_S):
                    e["state"] = STATE_WARNING
                    self.entered_warning.emit(cid, e["remain_s"])
                    warning_entered.append((cid, e["remain_s"]))
                self.ticked.emit(cid, e["remain_s"], e["total_s"])
        # 收尾：聚合 warning entered（72 cells 同一 tick 进入 warning 时只 1 条）
        if len(warning_entered) == 1:
            cid, remain = warning_entered[0]
            _log.debug("cid=%s entered warning (remain_s=%s)", cid, remain)
        elif len(warning_entered) > 1:
            _log.debug(
                "%d cells entered warning: cids=%s (remain_s~%s)",
                len(warning_entered),
                [c for c, _ in warning_entered],
                warning_entered[0][1],
            )
        if expired_cids:
            _log.info("tick expired: cids=%s", expired_cids)
        if not self._running_cids:
            self._stop_timer_if_idle()

    def _stop_timer_if_idle(self) -> None:
        if not self._running_cids and self._timer.isActive():
            self._timer.stop()
            _log.debug("timer stopped (all cells finished)")
