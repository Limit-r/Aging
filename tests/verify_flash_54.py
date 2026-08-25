# -*- coding: utf-8 -*-
"""核对真实视频里是否真的检到 LED / 闪烁，排除"检测链路 vs 视频本身无LED"。

对每个真实 .mp4 串行逐帧：320 onnx detect -> classify -> _assign_led_ids，
统计每路检出的 base 类 LED 种类、各 H/L 状态切换（闪烁）、以及是否从未检出任何框。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ml" / "vision"))

import cv2  # noqa: E402
from engine import DEPLOY_DIR, DetectionEngine  # noqa: E402
import worker as W  # noqa: E402

for s in (sys.stdout, sys.stderr):
    if hasattr(s, "reconfigure"):
        try: s.reconfigure(encoding="utf-8")
        except OSError: pass

ML = Path(__file__).resolve().parents[1]
VIDEOS = sorted((ML / "video").glob("*.mp4"))

def strip_suffix(name: str) -> str:
    for suf in ("_H", "_L"):
        if name.endswith(suf):
            return name[: -len(suf)]
    return name

def main() -> int:
    eng = DetectionEngine(input_shape=(320, 320), backend="onnx",
                          onnx_path=str(DEPLOY_DIR / "yolo_ptq_int8_320_dyn.onnx"))
    print("## 逐路核对 LED 检出 / 闪烁 ##")
    for vi, v in enumerate(VIDEOS):
        cap = cv2.VideoCapture(str(v))
        if not cap.isOpened():
            print(f"[{v.name}] 无法打开"); continue
        tracker = W.FlashTracker(debounce_frames=4)
        seen_base: dict[str, int] = {}
        state_trans: dict[str, int] = {}
        prev: dict[str, str] = {}
        n = m = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            n += 1
            dets = eng.detect_batch_parallel([frame], [frame.shape[:2]],
                                             max_workers=1)[0]
            hl = eng.classify_batch([(frame, dets)])[0]
            samples = W._assign_led_ids(dets, hl)
            m += len(samples)
            for name, state in samples.items():
                base = strip_suffix(name)
                seen_base[base] = seen_base.get(base, 0) + 1
                if name in prev and prev[name] != state:
                    state_trans[name] = state_trans.get(name, 0) + 1
                prev[name] = state
        cap.release()
        bases = {f"{k}:{v}" for k, v in seen_base.items()} or {"(无检出)"}
        n_tr = sum(state_trans.values())
        print(f"[{v.name}] 帧={n} 检出框样本={m} | base={sorted(bases)}"
              f" | H/L切换总次数={n_tr}")
        if not seen_base:
            print("   ⚠ 该视频全程未检出任何 LED 框")
        elif n_tr == 0:
            print("   — 检到 LED 但全程状态无切换(可能是常亮，非闪烁)")
        else:
            print(f"   ✓ 检到 LED 且有 {n_tr} 次状态切换")
    print("## 核对完成 ##")
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        import traceback; traceback.print_exc(); sys.exit(1)