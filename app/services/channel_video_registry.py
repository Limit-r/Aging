"""通道 ↔ 视频映射与检测状态注册表（GUI 进程内共享单例）。

用途：把"某个 CH 通道对应哪个视频源、是否正被静默监控"集中暴露给各页面，
供「电流检测 ↔ 视频流检测」的控制联动（current_page 启动联动拉起视频等）查询。
- 只做 GUI 侧信息登记，不参与 worker 内部状态；worker 对重复 job 幂等忽略。
- `path(cid)`：该通道已知的视频源路径（由视频总览/视频流页登记）。
- `monitored_cids()`：当前处于 54 路静默监控中的通道集合（监控全局进行，
  避免对同一视频在交互侧重复开流）。
"""
from __future__ import annotations

from typing import Callable, Optional
from app.observability import get_logger

_log = get_logger("app.services.channel_video_registry")


class ChannelVideoRegistry:
    """每通道视频路径 + 静默监控集合的注册表（线程均为 GUI 主线程）。"""

    def __init__(self) -> None:
        self._paths: dict[int, str] = {}      # cid -> 视频路径
        self._monitored: set[int] = set()     # 静默监控中（且映射过视频）的 cid
        self._paused: set[int] = set()        # 电流页暂停的 cid（后续开流需继承）
        self._current_running: set[int] = set()  # 电流检测正在运行/暂停的 cid

    # -- 视频路径 -----------------------------------------------------------
    def set_path(self, cid: int, path: str) -> None:
        """登记某通道的视频源路径。path 为空/None 则视为清除。"""
        if not path:
            self._paths.pop(cid, None)
        else:
            self._paths[cid] = path

    def path(self, cid: int) -> Optional[str]:
        """返回该通道已知视频路径；无则 None。"""
        return self._paths.get(cid)

    # -- 静默监控状态 ---------------------------------------------------------
    def set_monitored(self, cids: list, active: bool) -> None:
        """登记某批通道是否处于静默监控。active=True 加入，False 移除。"""
        if active:
            self._monitored.update(int(c) for c in cids)
        else:
            self._monitored.difference_update(int(c) for c in cids)

    def monitored_cids(self) -> set:
        """返回当前静默监控中的通道集合。"""
        return set(self._monitored)

    # -- 电流页暂停状态（供后续开流继承） -------------------------------------
    def set_paused(self, cid: int, paused: bool) -> None:
        """登记某通道的电流检测暂停状态。暂停时加入，恢复时移除。"""
        if paused:
            self._paused.add(int(cid))
        else:
            self._paused.discard(int(cid))

    def is_paused(self, cid: int) -> bool:
        """该通道的电流检测当前是否处于暂停。"""
        return int(cid) in self._paused

    # -- 电流运行通道集合 -----------------------------------------------------
    def set_current_running(self, cids: list) -> None:
        """登记当前「电流检测运行/暂停」的通道全集（全量替换）。

        作为「视频后台检测是否应随电流持续运行」的单一事实源：检测页切走/
        关闭时，若该通道仍在此集合中，则保留后台检测流、只复位页面展示。
        """
        self._current_running = {int(c) for c in (cids or [])}

    def current_running_cids(self) -> set:
        """返回当前电流检测运行/暂停的通道集合（副本）。"""
        return set(self._current_running)

    # -- 组合判定 ------------------------------------------------------------
    def auto_startable(self, cid: int) -> Optional[str]:
        """电流启动联动判定：返回应拉起的视频路径。
        规则：有已知路径 且 不在静默监控中 → 返回路径；否则 None。
        交互侧已运行的同 job 由 worker 幂等忽略，故无需在此追查交互运行态。
        """
        path = self._paths.get(cid)
        if not path:
            return None
        if cid in self._monitored:
            return None
        return path


_registry: Optional[ChannelVideoRegistry] = None


def get_channel_video_registry() -> ChannelVideoRegistry:
    """应用级唯一实例（惰性单例）。"""
    global _registry
    if _registry is None:
        _registry = ChannelVideoRegistry()
    return _registry