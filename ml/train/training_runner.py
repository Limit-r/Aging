# -*- coding: utf-8 -*-
"""
训练 / 转换子进程运行器（数据中心「训练 / 转换」页签专用）。

把一键流程涉及的脚本封装为可执行的命令行，并在 `ml/` 目录下以子进程方式运行，
逐行回调输出（供 GUI 日志区实时回显）。本模块只负责「组装命令 + 启动并流式读数」，
不承载 UI；`app/ui` 只做编排调用，保持依赖单向。

命令均以 `ml/`（PROJECT_ROOT）为工作目录，因为训练脚本内部路径
（weights/MERGED、datasets/merged/...）是相对 ML 根解析的。

可根据 STAGE 组合一/多步，供「一键完整流程」串行调用：
    DATA   -> train.gen_merged_txt                生成统一 9 类标注 txt
    YOLO   -> train.train_merged                 训练统一 YOLOv8 检测模型
    ROI    -> classifier.prepare_data_merged      合并 FP/A ROI 数据
    CLS    -> classifier.train_merged             训练统一 TinyConv 二分类器
"""
import os
import subprocess
import sys

# ml/ = PROJECT_ROOT（training_runner.py -> ml/train -> ml）
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _py() -> str:
    """当前解释器（GUI 由 Main.py 启动，训练沿用同一 python）。"""
    return sys.executable


def _abs(rel: str) -> str:
    """把 ML 根相对路径转绝对（避免子进程 CWD 干扰）。"""
    return os.path.join(PROJECT_ROOT, rel.replace("/", os.sep))


# ---- 命令组装 ---------------------------------------------------------------
def build_cmd(stage: str, params: dict = None) -> list:
    """返回 `stage` 对应的完整命令行（list，供 subprocess）。

    params 可选键（drill 到对应内核）:
      DATA: 无
      YOLO: epochs / batch / lr / phi
      ROI : 无
      CLS : epochs / batch / lr
    """
    params = params or {}
    py = _py()

    if stage == "DATA":
        return [py, _abs("train/gen_merged_txt.py")]

    if stage == "YOLO":
        cmd = [py, _abs("train/train_merged.py")]
        if params.get("epochs") is not None:
            cmd += ["--epochs", str(params["epochs"])]
        if params.get("batch") is not None:
            cmd += ["--batch", str(params["batch"])]
        if params.get("lr") is not None:
            cmd += ["--lr", str(params["lr"])]
        if params.get("phi"):
            cmd += ["--phi", str(params["phi"])]
        return cmd

    if stage == "ROI":
        return [py, _abs("classifier/prepare_data_merged.py")]

    if stage == "CLS":
        cmd = [py, _abs("classifier/train_merged.py")]
        if params.get("epochs") is not None:
            cmd += ["--epochs", str(params["epochs"])]
        if params.get("batch") is not None:
            cmd += ["--batch", str(params["batch"])]
        if params.get("lr") is not None:
            cmd += ["--lr", str(params["lr"])]
        return cmd

    raise ValueError("未知训练阶段: %s" % stage)


# ---- 执行 + 流式读数 ---------------------------------------------------------
def run(cmd: list, on_line=None):
    """在 ml/ 下运行命令，逐行回调 stdout（合并 stderr）。

    on_line(line: str) 收到去尾换行的文本；收集全部行后返回整体日志字符串。
    """
    proc = subprocess.Popen(
        cmd,
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
        universal_newlines=True,
        encoding="utf-8",
        errors="replace",
    )
    lines = []
    for raw in iter(proc.stdout.readline, ""):
        line = raw.rstrip("\r\n")
        lines.append(line)
        if on_line is not None:
            on_line(line)
    proc.stdout.close()
    proc.wait()
    return "\n".join(lines)


if __name__ == "__main__":
    # 冒烟：打印各阶段命令行（不实际执行）
    print(PROJECT_ROOT)
    for st in ("DATA", "YOLO", "ROI", "CLS"):
        print(st, "->", build_cmd(st))