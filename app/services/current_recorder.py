"""电流检测 · 数据记录服务（报告体系的 Phase 1 电流侧）。

把电流读数从"进程内 HistoryBuffer、会话结束即丢"升级为**可留档、可回读**。
设计依据 docs/video-detection-report.md §2/§3/§4（GUI 侧落盘、紧凑二进制、空态 valid 标记）。

约定：
- **文件粒度 = 单设备 · 单老化启动**：一台设备一次老化运行 = 一个 .bin
  （作 state_changed 中 stopped→running 开启，running/paused→stopped 关闭归档）
- **暂停不记录**：pause 时该设备不再写采样（与 worker 语义一致），resume 后继续同一文件
- **空态 valid 标记**：每行带 valid 标志，供报告区分"该设备未上载/空"与真实 0 电流
- 目录：`ml/detection_logs/<CH-XX>/<启动墙钟>.bin`

二进制布局（电流段，行定长，可随机定位）：
```
HEADER: >4sHIIQ   magic 'VDRC' | version | cid | session_id | start_wall_ms
ROW   : >iB4f     ts(秒) | valid(u8) | 4 × float32
```
"""

from __future__ import annotations

import os
import struct
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PyQt5.QtCore import QObject, QTimer

from app.core import config
from app.core.formatting import format_cid
from app.data.protocol import ChannelReading
from app.observability import get_logger, narrative

_log = get_logger("app.services.current_recorder")

# ---- 二进制格式（与 docs/video-detection-report.md §4 电流段对齐）--------
MAGIC = b"VDRC"
CURRENT_RECORD_VERSION = 1
_HEADER = struct.Struct(">4sHIIQ")   # magic, version, cid, session_id, start_wall_ms
_ROW = struct.Struct(">iB4f")        # ts(秒), valid(u8), currents 4×float32

# 仓库根：app/services -> 3 级 dirname 到 d:\Aging
_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _log_root() -> Path:
    return Path(_PROJECT_ROOT) / config.DETECTION_LOG_DIR


def detection_log_root() -> Path:
    """检测记录落盘根目录（数据中心历史页据此扫描会话）。"""
    return _log_root()


# ---- 读取接口（供后续数据中心回放） ----------------------------------------
DeviceHeader = Tuple[int, int, int, int, int]  # (version, cid, session_id, start_wall_ms, magic)
DeviceRow = Tuple[int, int, Tuple[float, float, float, float]]  # (ts_s, valid, currents)


def _read_file_header(data: bytes) -> DeviceHeader:
    if len(data) < _HEADER.size:
        raise ValueError("电流日志文件过短")
    magic, version, cid, session_id, start_ms = _HEADER.unpack_from(data, 0)
    if magic != MAGIC:
        raise ValueError(f"电流日志 magic 不匹配: {magic!r}")
    return (version, cid, session_id, start_ms, magic.decode("ascii"))


def read_device_log(path: Path) -> Tuple[DeviceHeader, List[DeviceRow]]:
    """读取单个设备 .bin，返回 (头信息, 行列表)。报告期从原始行重推导指标。"""
    data = Path(path).read_bytes()
    header = _read_file_header(data)
    rows: List[DeviceRow] = []
    off = _HEADER.size
    for _ in range((len(data) - off) // _ROW.size):
        ts, valid, c1, c2, c3, c4 = _ROW.unpack_from(data, off)
        rows.append((ts, valid, (c1, c2, c3, c4)))
        off += _ROW.size
    return header, rows


def inspect_device_log(path: Path) -> Tuple[DeviceHeader, int, Optional[int], Optional[int]]:
    """轻量枚举单个会话：读取头部 + 采样行数 + 首/末墙钟秒（不加载全量行）。

    供数据中心"会话列表"扫描用，避免对每个文件全量读取。
    返回 (header, row_count, first_ts, last_ts)。
    """
    data = Path(path).read_bytes()
    header = _read_file_header(data)
    n = (len(data) - _HEADER.size) // _ROW.size
    first_ts = last_ts = None
    if n > 0:
        first_ts = _ROW.unpack_from(data, _HEADER.size)[0]
        last_ts = _ROW.unpack_from(data, len(data) - _ROW.size)[0]
    return header, n, first_ts, last_ts


class CurrentRecorder(QObject):
    """订阅 CellController 状态 + 每次读数，按设备老化会话落盘电流。

    线程说明：与 HistoryBuffer/detail 页一致，运行于 GUI 主线程（QObject 无跨线程）。
    """

    _FLUSH_INTERVAL_MS = 10_000  # 运行中周期 flush，异常退出最多丢 ~10s

    def __init__(
        self,
        session_id: Optional[int] = None,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self._session_id = session_id if session_id is not None else self._new_session_id()
        # cid -> 该设备当前打开的归档信息（_open_file 结构），仅 running/paused 存在
        self._open: Dict[int, dict] = {}
        self._seq = 0
        # 周期 flush：数据仍会定时刷盘，崩溃最多丢一个 flush 周期
        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(self._FLUSH_INTERVAL_MS)
        self._flush_timer.timeout.connect(self.flush)
        self._flush_timer.start()
        _log.info(
            "CurrentRecorder started: session_id=%s, root=%s",
            self._session_id, _log_root(),
        )

    # -- 生命周期 ------------------------------------------------------------
    @staticmethod
    def _new_session_id() -> int:
        return int(time.time())

    def start_session(self, cid: int) -> None:
        """设备老化启动（stopped→running）：为该设备开启一个新的归档文件。"""
        if cid in self._open:
            return  # 幂等：running/paused/继续中
        root = _log_root() / format_cid(cid)
        root.mkdir(parents=True, exist_ok=True)
        start_wall_ms = int(time.time() * 1000)
        name = time.strftime("%Y%m%d_%H%M%S") + (
            f"_{self._seq}" if self._seq else ""
        )
        self._seq += 1
        path = root / f"{name}.bin"
        fh = path.open("ab")
        fh.write(_HEADER.pack(MAGIC, CURRENT_RECORD_VERSION, cid,
                              self._session_id, start_wall_ms))
        self._open[cid] = {"path": path, "file": fh, "paused": False}
        _log.info("record start: %s -> %s", format_cid(cid), path)
        narrative.event(
            "current_record_start",
            cid=format_cid(cid), path=str(path),
            note="电流记录开始（该设备老化启动）",
        )

    def pause_session(self, cid: int) -> None:
        """设备暂停（running→paused）：停止采样写入，文件保留。"""
        info = self._open.get(cid)
        if info is not None:
            info["paused"] = True
            _log.info("record pause: %s", format_cid(cid))

    def resume_session(self, cid: int) -> None:
        """设备继续（paused→running）：恢复采样写入，沿用同一文件。"""
        info = self._open.get(cid)
        if info is not None:
            info["paused"] = False
            _log.info("record resume: %s", format_cid(cid))

    def end_session(self, cid: int) -> None:
        """设备老化结束（→stopped）：flush + 关闭归档文件（保留磁盘）。"""
        info = self._open.pop(cid, None)
        if info is None:
            return
        fh, path = info["file"], info["path"]
        fh.flush()
        fh.close()
        _log.info("record end: %s -> %s (bytes=%s)", format_cid(cid), path, fh.name)
        narrative.event(
            "current_record_end",
            cid=format_cid(cid),
            note="电流记录结束（该设备老化停止，文件已归档）",
        )

    # -- 采样写入 ------------------------------------------------------------
    def handle_reading(self, r: ChannelReading) -> None:
        """消费单帧读数。仅当该设备归档打开且未暂停时落盘。"""
        info = self._open.get(r.channel_id)
        if info is None or info["paused"]:
            return
        # valid：设备处于运行老化（已接载）→ 读数有效；否则视为空/无效段
        valid = 1 if any(c > config.AUTO_IDLE_CURRENT_A for c in r.currents) else 0
        row = _ROW.pack(
            int(r.timestamp_ms / 1000), valid,
            r.currents[0], r.currents[1], r.currents[2], r.currents[3],
        )
        info["file"].write(row)

    def flush(self) -> None:
        """flush 所有打开文件（周期调用 + 退出前调用）。"""
        for info in self._open.values():
            info["file"].flush()

    def close(self) -> None:
        """退出前归档全部打开会话（应用关闭时调用）。"""
        self._flush_timer.stop()
        for cid in list(self._open.keys()):
            self.end_session(cid)

    # -- 查询 ----------------------------------------------------------------
    @property
    def session_id(self) -> int:
        return self._session_id

    def open_device_count(self) -> int:
        return len(self._open)