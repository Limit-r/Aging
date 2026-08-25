# -*- coding: utf-8 -*-
"""多进程替换读帧线程原型：共享内存解码进程池，实测真实跨进程吞吐。

零解码实验已证明 54 路编排无解码可达 ~208fps（vs 有读帧线程 154fps），瓶颈在
GIL。本原型把解码移出主进程：N 个 spawn 子进程各负责若干路，用 Cap 读帧并把
解码帧写入**固定尺寸共享内存槽**（numpy 视图，零拷贝），靠共享版本号同步；
主进程仅做调度 + GPU 检测/分类，消除读帧线程的 GIL 争用。

以此评估：真实多进程(含共享内存传输开销)能否 >170fps，达到或接近 216fps 目标。
"""
import multiprocessing as mp
import sys
import time
from multiprocessing import shared_memory as mp_shm
from pathlib import Path

mp.set_start_method("spawn", force=True)

import cv2  # noqa: E402
import numpy as np  # noqa: E402

ML = Path(__file__).resolve().parents[1]
VIDEOS = sorted((ML / "video").glob("*.mp4"))
sys_path = str(ML / "ml" / "vision")

N_CH = 54
FPS = 4.0
PERIOD = 1.0 / FPS
MAX_W, MAX_H = 1280, 720          # 共享槽统一最大尺寸
# 解码进程数：每进程负责几条流（各自节流），进程数 ≈ min(cpu//2, N_CH)
N_DECODER = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 8


def decoder_main(cfg, shm_name, versions, stop_ev, sys_path):
    """子进程：attach 共享内存，为所属各路按 4fps 读帧写槽并递增版本号。"""
    import sys
    import cv2
    import numpy as np
    from multiprocessing import shared_memory
    sys.path.insert(0, sys_path)
    shm = shared_memory.SharedMemory(name=shm_name)
    buf = np.ndarray((N_CH, MAX_H, MAX_W, 3), np.uint8, buffer=shm.buf)
    caps = {}
    for job in cfg["jobs"]:
        caps[job] = cv2.VideoCapture(cfg["videos"][job])
    next_t = {job: time.time() + cfg["phase"][job] for job in caps}
    loops = 0
    while not stop_ev.is_set():
        now = time.time()
        for job, cap in caps.items():
            if now < next_t[job]:
                continue
            ret, f = cap.read()
            if not ret:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)     # 循环读，模拟监控
                ret, f = cap.read()
                if not ret:
                    continue
                loops += 1
            # 写共享槽（小帧留在左上角，主进程按自己记录的 h,w 截取）
            h, w = f.shape[:2]
            dst = buf[job][:h, :w]
            np.copyto(dst, f, casting="unsafe")
            versions[job] += 1
            next_t[job] = now + PERIOD
        time.sleep(0.002)
    for cap in caps.values():
        cap.release()


def main() -> int:
    import sys
    sys.path.insert(0, sys_path)
    from engine import DEPLOY_DIR, DetectionEngine  # noqa: E402
    import worker as W  # noqa: E402
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            try: s.reconfigure(encoding="utf-8")
            except OSError: pass

    eng = DetectionEngine(input_shape=(320, 320), backend="onnx",
                          onnx_path=str(DEPLOY_DIR / "yolo_ptq_int8_320_dyn.onnx"))
    # 每路视频 h,w（主进程需知道以截取共享槽）
    vshape = []
    for i in range(N_CH):
        cap = cv2.VideoCapture(str(VIDEOS[i % len(VIDEOS)]))
        vshape.append((int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
                       int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))))
        cap.release()

    # 分配各进程负责的 job，并按相位错开首帧
    cfgs = []
    for d in range(N_DECODER):
        jobs = [j for j in range(N_CH) if j % N_DECODER == d]
        cfgs.append({"jobs": jobs,
                     "videos": [str(VIDEOS[0])] * N_CH,   # 占位（见下）
                     "phase": {j: (j % N_DECODER) * (PERIOD / N_DECODER) for j in jobs}})
    # videos 真实映射：job->video 路径
    for cfg in cfgs:
        cfg["videos"] = [str(VIDEOS[j % len(VIDEOS)]) for j in range(N_CH)]

    shm = mp_shm.SharedMemory(create=True,
                              size=N_CH * MAX_H * MAX_W * 3)
    versions = mp.Array("i", [0] * N_CH)
    stop_ev = mp.Event()
    procs = [mp.Process(target=decoder_main,
                        args=(cfg, shm.name, versions, stop_ev, sys_path),
                        daemon=True) for cfg in cfgs]
    for p in procs:
        p.start()

    buf = np.ndarray((N_CH, MAX_H, MAX_W, 3), np.uint8, buffer=shm.buf)
    consumed = [0] * N_CH
    seen = [0] * N_CH
    frames = [None] * N_CH

    frames_det = 0
    iters = 0
    t_end = time.time() + 25
    while time.time() < t_end:
        now = time.time()
        iters += 1
        batch, shapes, js = [], [], []
        for j in range(N_CH):
            v = versions[j]
            if v <= consumed[j]:
                continue                       # 尚无新帧
            h, w = vshape[j]
            f = np.ascontiguousarray(buf[j][:h, :w])
            consumed[j] = v
            seen[j] += 1
            js.append(j)
            batch.append(f)
            shapes.append([h, w])
            if len(batch) >= W.MONITOR_CHUNK:
                break
        if batch:
            dets_batch = eng.detect_batch_parallel(batch, shapes,
                                                   max_workers=W.MONITOR_WORKERS)
            hl_list = eng.classify_batch([(f, d) for f, d in zip(batch, dets_batch)])
            frames_det += len(batch)
        time.sleep(0.001 if batch else 0.005)

    stop_ev.set()
    for p in procs:
        p.join(2)
    shm.close(); shm.unlink()

    dur = time.time() - (t_end - 25)
    print("\n================ 多进程(共享内存)54路汇总 ================")
    print(f"解码进程数: {N_DECODER} | 运转 {dur:.1f}s | 调度迭代 {iters}")
    print(f"检测帧吞吐: {frames_det/dur:.1f} fps (目标216) → "
          f"{'达标' if frames_det/dur>=216 else '未达标'}")
    print(f"各路上帧数 min={min(seen)} max={max(seen)}")
    return 0


if __name__ == "__main__":
    try:
        mp.freeze_support()
        main()
    except Exception:
        import traceback; traceback.print_exc()