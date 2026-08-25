# -*- coding: utf-8 -*-
"""54 路真实视频流端到端静默监控测试。

启动 `ml/vision/worker.py` 子进程，下发 monitor(54路, fps=4, loop=false)，
收集其 stdout 事件，直至 monitor_finished；输出聚合结果要点。

仅 6 个真实视频 -> 按 CH01..CH54 轮询分配（同视频多路复用），全程真实
NVDEC/cv2 解码 + GPU batch 检测 + TinyConv 分类。
"""
import json
import subprocess
import sys
import time
from pathlib import Path

ML_ROOT = Path(__file__).resolve().parents[1]          # d:\Aging
VIDEOS = sorted((ML_ROOT / "video").glob("*.mp4"))
if not VIDEOS:
    print("未找到视频 ", ML_ROOT / "video" / "*.mp4"); sys.exit(1)

WORKER = str(ML_ROOT / "ml" / "vision" / "worker.py")
PY = sys.executable

# 6 个真实视频 -> 54 路（round-robin）
JOBS = [{"job": i + 1, "video": str(VIDEOS[i % len(VIDEOS)])}
        for i in range(54)]
CMD_MONITOR = json.dumps({"cmd": "monitor", "jobs": JOBS,
                          "fps": 4, "conf": 0.25, "nms": 0.45,
                          "loop": False}, ensure_ascii=False)
CMD_SNAPSHOT = json.dumps({"cmd": "snapshot"})
CMD_QUIT = json.dumps({"cmd": "quit"})


def main() -> int:
    env = {"PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1",
           "PYTHONHASHSEED": "0"}  # 固定哈希种子，规避管道 stdio 下启动期系统RNG失败
    proc = subprocess.Popen(
        [PY, WORKER], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, encoding="utf-8", env=env)

    def send(line: str):
        proc.stdin.write(line + "\n"); proc.stdin.flush()

    print("== 启动 worker ==")
    send(CMD_MONITOR)
    start = time.time()

    events, monitor_start, done = [], None, 0
    snapshot_final = None
    while time.time() - start < 120:
        line = proc.stdout.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        # worker 可能输出非 JSON（异常 traceback）— 规整到日志
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            print("[raw]", line); continue
        events.append(e)
        t = time.time() - start
        typ = e.get("type")
        if typ == "status":
            print(f"[{t:6.1f}s] status: {e.get('message')}")
        elif typ == "fatal":
            print(f"[{t:6.1f}s] FATAL: {e.get('message')}"); break
        elif typ == "ready":
            print(f"[{t:6.1f}s] ready: {e.get('model')} device={e.get('device')}")
        elif typ == "monitor_start":
            monitor_start = e
            print(f"[{t:6.1f}s] monitor_start count={e.get('count')} "
                  f"fps={e.get('fps')} input={e.get('input')}")
        elif typ == "error":
            print(f"[{t:6.1f}s] error: {e.get('message')}")
        elif typ == "snapshot":
            snapshot_final = e
            c = e.get("count", 0)
            done = sum(1 for s in e["streams"]
                       if s.get("status") == "done")
            print(f"[{t:6.1f}s] snapshot count={c} done={done} "
                  f"all_done={e.get('done')}")
        elif typ == "monitor_finished":
            print(f"[{t:6.1f}s] monitor_finished")
            break
    send(CMD_QUIT)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    elapsed = time.time() - start

    print("\n================ 54路端到端汇总 ================")
    print(f"总耗时: {elapsed:.1f}s | monitor_start: {monitor_start}")
    errs = [e for e in events if e.get("type") == "error"]
    print(f"error 事件数: {len(errs)}")
    for e in errs:
        print("  -", e.get("message"))

    # 从最后一次 snapshot 或各自 snapshot 汇总闪烁统计
    if snapshot_final:
        streams = snapshot_final.get("streams", [])
        opened = [s for s in streams if s.get("status") in ("opened", "done")]
        ok_done = sum(1 for s in streams if s.get("status") == "done")
        err = [s for s in streams if s.get("status") == "error"]
        n_flash = sum(1 for s in opened if s.get("flashes"))
        n_loop = sum(1 for s in opened if s.get("loops", 0) > 0)
        total_flash = sum(sum(s.get("flashes", {}).values())
                          for s in opened if s.get("flashes"))
        print(f"路数: {len(streams)} | done(播放完): {ok_done} | error: {len(err)}")
        print(f"有闪烁统计的路: {n_flash} | 有循环的路: {n_loop} | 累计闪烁次数: {total_flash}")
        for s in streams:
            if s.get("error"):
                print(f"  CH{s['job']:02d} error: {s['error']}")
        # 前 6 路详情示例
        print("示例路详情 (前6):")
        for s in streams[:6]:
            fl = dict(s.get("flashes", {}))
            print(f"  CH{s['job']:02d} {s.get('status')} "
                  f"frame={s.get('frame')}/{s.get('total')} "
                  f"loops={s.get('loops')} flashes={fl}")
    print("================ 完成 ================")
    return 0


if __name__ == "__main__":
    sys.exit(main())