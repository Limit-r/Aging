# -*- coding: utf-8 -*-
"""训练产物自动部署（数据中心「训练 / 转换」页专用）。

把训练输出的最佳模型 + TinyConv 分类器 + 类别表复制到集中部署目录 `ml/deploy/`，
供检测 / 推理程序统一从该目录加载。训练脚本输出（相对 ml/）：
    weights/MERGED/model_best_precision_deploy.pt   部署格式（dict 含 model）
    weights/MERGED/best_epoch_weights.pth           最佳 epoch 权重
    classifier/weights/best_tinyconv_merged.pth     统一 TinyConv 二分类器
    datasets/merged/label_merged.txt                统一 9 类类别表

部署后生成 `ml/deploy/latest.json` 清单（部署时间 / 来源 / 文件清单），
方便检测程序确认当前生效模型。本模块只做文件复制 + 元数据写入，
不加载 torch / 不依赖 Qt，保证懒加载启动轻量。
"""

import json
import os
import shutil
import time

# ml/ = 本文件所在目录（deploy_models.py -> train -> ml）
ML_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 集中部署目录
DEPLOY_DIR = os.path.join(ML_ROOT, "deploy")

# 部署目标固定文件名（检测程序统一引用，不被训练批次影响）
DEPLOY_MODEL = "yolo_best_deploy.pt"          # 部署格式（含 input_shape/num_classes/phi）
DEPLOY_WEIGHTS = "yolo_best_epoch_weights.pth"  # 最佳 epoch 权重
DEPLOY_CLASSIFIER = "tinyconv_best.pth"       # 统一 TinyConv 亮灭二分类器
DEPLOY_LABELS = "label_merged.txt"            # 统一类别表
MANIFEST_NAME = "latest.json"

# 训练输出源（相对 ml/）
SOURCE_DIR = os.path.join(ML_ROOT, "weights", "MERGED")
SOURCE_CLASSIFIER = os.path.join(ML_ROOT, "classifier", "weights", "best_tinyconv_merged.pth")
SOURCE_LABELS = os.path.join(ML_ROOT, "datasets", "merged", "label_merged.txt")


def latest_manifest() -> dict | None:
    """读取最近一次部署清单；无则返回 None。"""
    path = os.path.join(DEPLOY_DIR, MANIFEST_NAME)
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def deployed_paths() -> dict:
    """返回部署目录下各固定文件名对应的绝对路径（不存在时仍返回）。"""
    return {
        "model": os.path.join(DEPLOY_DIR, DEPLOY_MODEL),
        "weights": os.path.join(DEPLOY_DIR, DEPLOY_WEIGHTS),
        "classifier": os.path.join(DEPLOY_DIR, DEPLOY_CLASSIFIER),
        "labels": os.path.join(DEPLOY_DIR, DEPLOY_LABELS),
        "manifest": os.path.join(DEPLOY_DIR, MANIFEST_NAME),
    }


def deploy_latest(on_log=None) -> dict:
    """把训练输出复制到集中部署目录，并写部署清单。

    on_log(msg) 可选回调：供 GUI 把部署过程回显到日志区。

    返回：
        {"ok": bool, "dir": str, "files": [部署的文件名...],
         "ts": 时间戳str, "error": 失败原因(ok=False 时)}
    """
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    os.makedirs(DEPLOY_DIR, exist_ok=True)

    sources = {
        DEPLOY_MODEL: os.path.join(SOURCE_DIR, "model_best_precision_deploy.pt"),
        DEPLOY_WEIGHTS: os.path.join(SOURCE_DIR, "best_epoch_weights.pth"),
        DEPLOY_CLASSIFIER: SOURCE_CLASSIFIER,
        DEPLOY_LABELS: SOURCE_LABELS,
    }

    deployed_files = []
    for target_name, src in sources.items():
        if not os.path.exists(src):
            return {
                "ok": False, "dir": DEPLOY_DIR, "files": deployed_files,
                "ts": ts, "error": "源文件不存在: %s" % src,
            }
        dst = os.path.join(DEPLOY_DIR, target_name)
        try:
            shutil.copy2(src, dst)
        except OSError as exc:
            return {
                "ok": False, "dir": DEPLOY_DIR, "files": deployed_files,
                "ts": ts, "error": "复制 %s 失败: %s" % (target_name, exc),
            }
        deployed_files.append(target_name)
        if on_log is not None:
            on_log("  部署 %s → %s" % (target_name, dst))

    manifest = {
        "ts": ts,
        "source_dir": SOURCE_DIR,
        "files": deployed_files,
        "paths": deployed_paths(),
    }
    with open(os.path.join(DEPLOY_DIR, MANIFEST_NAME), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return {
        "ok": True, "dir": DEPLOY_DIR, "files": deployed_files, "ts": ts,
        "error": None,
    }


if __name__ == "__main__":
    # 冒烟：打印部署目标路径（不实际执行）
    print(DEPLOY_DIR)
    for k, v in deployed_paths().items():
        print(k, "->", v)
