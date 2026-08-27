"""常驻检测 worker 的全局单例管理（GUI 侧编排）。

- **全应用共享单个 QProcess 子进程**（`ml/vision/worker.py`），避免每次进入
  视频流检测页都重新启动并重新预加载 YOLO + TinyConv 模型。
- 生命周期归属应用：首次用到才启动，应用关闭时统一 `shutdown()`。
- 本模块只做进程编排（QProcess 启动 + stdin 命令/ stdout JSON 事件转发），
  **不向 GUI 进程引入 torch**（`app/ui` 不依赖 torch 的约束保持不变）。

进程事件按类型分发给订阅方（视频流检测页）：
- 全局事件 `ready` / `fatal` → 独立信号
- 带 `job` 的任务事件（sample / done / error）→ `event(payload)`，由订阅方按 job 过滤
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import QObject, QProcess, QProcessEnvironment, pyqtSignal

from app.core import labels
from app.core.tokens import DEFAULT_TOKENS
from app.observability import get_logger, narrative

_S = DEFAULT_TOKENS.sizing

PROJECT_ROOT = Path(__file__).resolve().parents[2]   # d:\Aging
WORKER_SCRIPT = PROJECT_ROOT / "ml" / "vision" / "worker.py"

_log = get_logger("app.ui.vision_worker")


class VisionWorkerManager(QObject):
    """全局唯一的常驻检测 worker 编排对象（单例）。"""

    ready = pyqtSignal(str)        # model 说明（device 等）
    fatal = pyqtSignal(str)        # 致命错误（模型缺失等）
    job_event = pyqtSignal(dict)   # sample / done / error（含 job），订阅方按 job 过滤
    state_changed = pyqtSignal(str)  # starting / ready / failed / stopped

    def __init__(self):
        super().__init__()
        self._proc: Optional[QProcess] = None
        self._buf: str = ""
        self._state = "idle"
        self._stopping = False
        # worker 未启动/未 ready 时暂存命令，ready 后按序补发，
        # 保证电流页等先于 worker 启动下达的 pause/resume 等命令不丢失
        self._pending: list = []

    # ------------------------------------------------------------------ 状态
    @property
    def state(self) -> str:
        return self._state

    def _set_state(self, state: str) -> None:
        if self._state != state:
            self._state = state
            self.state_changed.emit(state)

    # ------------------------------------------------------------------ 启动
    def ensure_started(self) -> None:
        """确保 worker 子进程已启动（幂等，忽略重复调用）。"""
        if self._proc is not None or self._stopping:
            return
        proc = QProcess(self)
        proc.setProcessChannelMode(QProcess.MergedChannels)
        penv = QProcessEnvironment.systemEnvironment()
        penv.insert("PYTHONIOENCODING", "utf-8")
        penv.insert("PYTHONUNBUFFERED", "1")
        proc.setProcessEnvironment(penv)
        proc.setWorkingDirectory(str(PROJECT_ROOT))
        proc.readyReadStandardOutput.connect(self._on_stdout)
        proc.finished.connect(self._on_finished)
        proc.errorOccurred.connect(self._on_error)
        self._proc = proc
        self._buf = ""
        self._set_state("starting")
        proc.start(sys.executable, [str(WORKER_SCRIPT)])
        narrative.event("vision_worker_start",
                        note="常驻检测 worker 启动（全局单例，模型预加载）")

    # ------------------------------------------------------------------ 命令
    def send(self, obj: dict) -> None:
        """向 worker 的 stdin 写入一行 JSON 命令。

        worker 进程未启动或尚未 ready 时，先缓存到 `_pending`，等 ready 事件
        到达后按序补发。避免先于 worker 启动下达的 pause/resume 等联动命令
        被静默丢弃。
        """
        if self._stopping:
            return
        if self._proc is None or self._state != "ready":
            self._pending.append(obj)
            return
        self._write(obj)

    def _write(self, obj: dict) -> None:
        if self._proc is None:
            return
        self._proc.write((json.dumps(obj) + "\n").encode("utf-8"))

    def _flush_pending(self) -> None:
        if not self._pending:
            return
        pending, self._pending = self._pending, []
        for obj in pending:
            self._write(obj)
        narrative.event("vision_worker_flush",
                        note=f"补发 {len(pending)} 条待执行命令")

    # ------------------------------------------------------------------ 收发
    def _on_stdout(self) -> None:
        proc = self._proc
        if proc is None:
            return
        data = bytes(proc.readAllStandardOutput()).decode("utf-8", "replace")
        lines = (self._buf + data).split("\n")
        self._buf = lines.pop()
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except (ValueError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            self._dispatch(payload)

    def _dispatch(self, payload: dict) -> None:
        ptype = payload.get("type")
        if ptype == "ready":
            self._set_state("ready")
            self.ready.emit(payload.get("device", ""))
            self._flush_pending()
        elif ptype == "fatal":
            self.fatal.emit(payload.get("message", ""))
        else:
            # sample / done / error / status ... 交给订阅方，由 job 过滤
            self.job_event.emit(payload)

    def _on_finished(self, _code: int, _status: int) -> None:
        self._log_finish("finished")
        self._clear_proc("stopped")

    def _on_error(self, error: QProcess.ProcessError) -> None:
        _log.warning("vision worker process error: %s", error)
        self.fatal.emit(labels.VIDEO_WORKER_CRASH)
        self._clear_proc("failed")

    @staticmethod
    def _log_finish(kind: str) -> None:
        _log.warning("vision worker %s", kind)

    def _clear_proc(self, state: str) -> None:
        if self._proc is not None:
            self._proc.disconnect()
            self._proc = None
        self._buf = ""
        self._set_state(state)

    # ------------------------------------------------------------------ 关闭
    def shutdown(self, wait_ms: int = 3000) -> None:
        """应用退出时统一关闭 worker（幂等）。"""
        if self._proc is None:
            self._stopping = False
            return
        self._stopping = True
        self._write({"cmd": "quit"})
        self._proc.terminate()
        if not self._proc.waitForFinished(wait_ms):
            _log.warning("vision worker did not exit gracefully, killing")
            self._proc.kill()
            self._proc.waitForFinished(_S.WORKER_FORCE_KILL_WAIT_MS)
        self._clear_proc("stopped")
        self._stopping = False
        narrative.event("vision_worker_shutdown",
                        note="常驻检测 worker 已关闭")


# ------------------------------------------------------------------ 单例获取
_manager: Optional[VisionWorkerManager] = None


def get_vision_worker() -> VisionWorkerManager:
    """返回应用级唯一的 worker 管理器单例。"""
    global _manager
    if _manager is None:
        _manager = VisionWorkerManager()
    return _manager