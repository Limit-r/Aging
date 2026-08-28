# -*- coding: utf-8 -*-
"""
自动超参数推荐引擎（训练页「自动分配参数」专用）。

职责：
- 探测硬件环境（GPU 显存 / CPU 核数 / 内存）—— 通过子进程脚本在训练环境内执行，
  避免把 torch 加载进 GUI 进程
- 统计数据集规模（ml/datasets/merged 下 train/val/test 图数与框数）
- 依据「硬件 + 数据集」推荐一套合理的 YOLO 检测 + TinyConv 分类训练参数

约定：
- 本模块为纯数据逻辑，不依赖 Qt 与 app 层；不含用户可见文案
- 推荐依据以结构化 reason 键返回（如 ("phi", "mem_high")），由 UI 层用 labels 映射为文案
- 阈值取「偏保守」：宁可慢一点、batch 小一点，也不让显存溢出导致训练中断
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import List, Tuple

log = logging.getLogger("ml.train.auto_params")

# ml/ = ML 根（auto_params.py -> ml/train -> ml）
_ML_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MERGED_DIR = os.path.join(_ML_ROOT, "datasets", "merged")

# 显存分级阈值（GB）：决定 phi 与 batch 的档位
_MEM_MID = 8.0
_MEM_HIGH = 16.0


@dataclass
class EnvInfo:
    """硬件环境快照。"""

    gpu_count: int = 0
    gpu_name: str = ""
    gpu_mem_gb: float = 0.0
    cpu_cores: int = 4
    ram_gb: float = 8.0
    cuda: bool = False

    @property
    def has_gpu(self) -> bool:
        return bool(self.cuda and self.gpu_count and self.gpu_count > 0)


@dataclass
class DatasetStats:
    """数据集规模快照。"""

    train_imgs: int = 0
    val_imgs: int = 0
    test_imgs: int = 0
    boxes: int = 0


@dataclass
class AutoParams:
    """推荐结果；reasons 为 (key, detail) 依据列表，供 UI 映射文案。"""

    phi: str = "n"
    yolo_epochs: int = 200
    yolo_batch: int = 2
    yolo_lr: float = 0.005
    cls_epochs: int = 100
    cls_batch: int = 32
    cls_lr: float = 0.001
    reasons: List[Tuple[str, str]] = field(default_factory=list)


# ---- 环境探测 ---------------------------------------------------------------
# 独立可执行脚本：在训练环境（含 torch）内打印环境信息，GUI 通过子进程调用。
# 输出为 KEY VALUE 行：COUNT / NAME / MEM / CPU / RAM。
PROBE_SNIPPET = (
    "import ctypes, os, torch;"
    "print('COUNT', torch.cuda.device_count());"
    "print('NAME', torch.cuda.get_device_name(0) if torch.cuda.is_available() else '');"
    "print('MEM', round(torch.cuda.get_device_properties(0).total_memory/1024**3, 1) if torch.cuda.is_available() else 0);"  # noqa: E501
    "print('CPU', os.cpu_count() or 4)\n"
    "try:\n"
    " class _M(ctypes.Structure):\n"
    "  _fields_=[('dwLength',ctypes.c_ulong),('dwMemoryLoad',ctypes.c_ulong),('ullTotalPhys',ctypes.c_ulonglong),('ullAvailPhys',ctypes.c_ulonglong),('ullTotalPageFile',ctypes.c_ulonglong),('ullAvailPageFile',ctypes.c_ulonglong),('ullTotalVirtual',ctypes.c_ulonglong),('ullAvailVirtual',ctypes.c_ulonglong),('ullAvailExtendedVirtual',ctypes.c_ulonglong)]\n"  # noqa: E501
    " m=_M(); m.dwLength=ctypes.sizeof(_M); ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)); print('RAM', round(m.ullTotalPhys/1024**3, 1))\n"  # noqa: E501
    "except Exception:\n"
    " print('RAM', 0)"
)


def parse_env_output(text: str) -> EnvInfo:
    """解析 PROBE_SNIPPET 子进程输出 → EnvInfo。"""
    env = EnvInfo()
    for ln in text.splitlines():
        ln = ln.strip()
        if ln.startswith("COUNT "):
            env.gpu_count = int(ln.split()[1])
            env.cuda = env.gpu_count > 0
        elif ln.startswith("NAME "):
            env.gpu_name = ln.split(" ", 1)[1]
        elif ln.startswith("MEM "):
            env.gpu_mem_gb = float(ln.split()[1])
        elif ln.startswith("CPU "):
            env.cpu_cores = int(ln.split()[1])
        elif ln.startswith("RAM "):
            env.ram_gb = float(ln.split()[1])
    return env


# ---- 数据集统计 -------------------------------------------------------------
def dataset_stats() -> DatasetStats:
    """统计 ml/datasets/merged 下 train/val/test txt 的图数与框数。"""
    ds = DatasetStats()

    def _count(split: str):
        path = os.path.join(_MERGED_DIR, "2025_%s.txt" % split)
        n_img = 0
        n_box = 0
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                for ln in f:
                    ln = ln.strip()
                    if not ln:
                        continue
                    n_img += 1
                    n_box += len(ln.split()) - 1
        return n_img, n_box

    ds.train_imgs, ds.boxes = _count("train")
    ds.val_imgs, _ = _count("val")
    ds.test_imgs, _ = _count("test")
    return ds


def validate_for_training(kind: str = "YOLO") -> Tuple[bool, str]:
    """训练前前置校验：确认数据集已生成且可用于训练。

    供训练页在启动 YOLO / CLS / 一键流程前调用，避免跑空失败。

    kind:
      "YOLO"    -> 要求统一数据 train.txt 存在且含有效框
      "CLS"     -> 要求统一 train 已有图（分类器复用其框做 ROI 裁剪）
      "DATA"    -> 跳过校验（该阶段正是生成数据）
      "CONVERT" -> 要求已训练检测模型（weights/MERGED）与统一数据均存在

    返回 (ok, reason)；ok=False 时 reason 为阻断原因（供 UI 直接展示）。
    """
    log.debug("validate_for_training 开始: kind=%s", kind)

    ds = dataset_stats()
    log.debug("数据集统计: train=%d图/%d框, val=%d, test=%d, merged=%s",
              ds.train_imgs, ds.boxes, ds.val_imgs, ds.test_imgs, _MERGED_DIR)
    has_train = ds.train_imgs > 0

    if kind == "DATA":
        log.info("[datacheck] kind=DATA 跳过校验（该阶段正用于生成数据），直接放行")
        return True, ""

    if kind == "CONVERT":
        wpath = os.path.join(_ML_ROOT, "weights", "MERGED", "best_epoch_weights.pth")
        if not os.path.exists(wpath):
            log.warning("[datacheck] 阻断转换: 未找到已训练检测模型 %s", wpath)
            return False, "未找到已训练检测模型（weights/MERGED/best_epoch_weights.pth），请先运行「② 训练检测模型」"
        if not has_train:
            log.warning("[datacheck] 阻断转换: train.txt 无图片 (kind=%s)", kind)
            return False, "尚未生成统一数据（train.txt 无图），请先运行「① 生成统一标注」"
        log.debug("[datacheck] CONVERT 校验通过: 权重存在 + 有训练图")
        return True, ""

    if not has_train:
        log.warning("[datacheck] 阻断训练: train.txt 无图片 (kind=%s)", kind)
        return False, "尚未生成统一数据（train.txt 无图），请先运行「① 生成统一标注」"

    if kind == "YOLO" or kind == "ONECLICK":
        if ds.boxes <= 0:
            log.warning("[datacheck] 阻断训练: 有图片但无标注框 (kind=%s, boxes=%d)",
                        kind, ds.boxes)
            return False, "统一数据中未检出标注框，请先完成标注后重新生成数据"
        log.debug("[datacheck] YOLO/ONECLICK 框数校验通过: boxes=%d", ds.boxes)

    log.info("[datacheck] 校验通过: kind=%s, train=%d图/%d框", kind,
             ds.train_imgs, ds.boxes)
    return True, ""


# ---- 推荐主逻辑 -------------------------------------------------------------
def recommend(env: EnvInfo, ds: DatasetStats) -> AutoParams:
    """依据硬件 + 数据集规模生成推荐参数（数值偏保守，避免训练中途 OOM）。"""
    p = AutoParams()
    mem = env.gpu_mem_gb

    # 模型尺寸 phi：固定为 "n"（需求：不随硬件/数据变化，统一用 nano）
    p.phi = "n"
    p.reasons.append(("phi", "fixed"))

    # 检测批次：显存档位为主，训练集规模为上限约束
    if not env.has_gpu:
        p.yolo_batch = 2
        p.reasons.append(("batch", "cpu"))
    elif mem >= _MEM_HIGH:
        p.yolo_batch = 16
    elif mem >= _MEM_MID:
        p.yolo_batch = 8
    else:
        p.yolo_batch = 4
    if ds.train_imgs:
        p.yolo_batch = min(p.yolo_batch, ds.train_imgs)
    p.reasons.append(("batch", "data"))

    # 检测轮次：随数据量分级（early_stop 兜底防过拟合）
    if ds.train_imgs >= 1000:
        p.yolo_epochs = 300
    elif ds.train_imgs >= 500:
        p.yolo_epochs = 250
    elif ds.train_imgs >= 200:
        p.yolo_epochs = 200
    else:
        p.yolo_epochs = 150
    p.reasons.append(("epochs", "data"))

    # 分类器 TinyConv：轻量模型，batch/epochs 按硬件与数据量微调
    if not env.has_gpu:
        p.cls_batch = 16
        p.cls_epochs = 80
        p.reasons.append(("cls", "cpu"))
    else:
        p.cls_batch = 64 if mem >= _MEM_MID else 32
        p.cls_epochs = 120 if ds.train_imgs >= 2000 else 100
        p.reasons.append(("cls", "gpu"))
    if ds.train_imgs:
        p.cls_batch = min(p.cls_batch, ds.train_imgs)
    return p


if __name__ == "__main__":
    # 冒烟：本地统计数据集 + 打印一组样例推荐（需在训练环境运行）
    ds = dataset_stats()
    print("dataset:", ds)
    print("sample:", recommend(EnvInfo(gpu_count=1, gpu_name="RTX", gpu_mem_gb=16,
                                       cuda=True), ds))
