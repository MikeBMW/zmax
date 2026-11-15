#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""traj_progress_bridge.py —— 把 arm_step_traj.py 的 stdout 进度同步成 traj_step_state.json

为什么需要它(2026-11-15):
    arm_step_traj.py 每走到一点只往 stdout 打 {"progress": n, "step": {...}}, 不写
    traj_step_state.json; 而 8797 的 /api/arm/step_traj/status 只读那个 state 文件 ⇒
    页面「游标 x/215」和甘特游标永远停在上一轮的陈旧值(实测卡在 cursor=124)。
    真机正在跑, 不能改那个脚本(改了就中断采集), 所以用这个旁路进程把日志刷进 state。

用法:
    ./gui-venv311/bin/python tools/traj_progress_bridge.py \
        --log zmax_data/reports/logs/replay215_LAST.log \
        --state zmax_data/rokae_sdk/traj_step_state.json \
        --total 215
退出: 日志出现最终结果行(含 "n_done") 后写完最后一次即退出; 或 --timeout 到点退出。
"""
import argparse
import json
import os
import time


def last_progress(path):
    """返回 (n, step_dict) —— 日志里最后一条 progress; 没有就 (None, None)。"""
    n, step = None, None
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 200000))       # 只看尾部 200KB, 日志再长也不拖慢
            for ln in f.read().decode("utf-8", "replace").splitlines():
                ln = ln.strip()
                if not ln.startswith("{"):
                    continue
                try:
                    d = json.loads(ln)
                except Exception:                                # noqa: BLE001
                    continue
                if "progress" in d:
                    n = int(d["progress"])
                    step = d.get("step")
    except FileNotFoundError:
        return None, None
    return n, step


def finished(path):
    """日志里出现最终结果(n_done) 即认为这一轮结束。"""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 200000))
            return '"n_done"' in f.read().decode("utf-8", "replace")
    except FileNotFoundError:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", required=True)
    ap.add_argument("--state", required=True)
    ap.add_argument("--total", type=int, default=215)
    ap.add_argument("--interval", type=float, default=1.5)
    ap.add_argument("--timeout", type=float, default=1800)
    a = ap.parse_args()

    t0 = time.time()
    last = None
    while time.time() - t0 < a.timeout:
        n, step = last_progress(a.log)
        if n is not None and n != last:
            last = n
            st = {
                "running": not finished(a.log),
                "t0": t0,
                "n": 1,
                "dry": False,
                "start": max(0, n - 1),          # 最近一步的下标(与 8797 的语义一致)
                "total": a.total,
                "advanced": True,
                "cursor": n,                     # ★ 已走到第 n 点
                "pid": os.getpid(),
                "done": n,
                "src": "traj_progress_bridge",
                "log": a.log,
                "step": step,
                "updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            try:
                tmp = a.state + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(st, f, ensure_ascii=False)
                os.replace(tmp, a.state)         # 原子替换, 8797 永远读到完整 JSON
            except Exception as e:                               # noqa: BLE001
                print("write err: %s: %s" % (type(e).__name__, e), flush=True)
            print(json.dumps({"synced": n, "total": a.total}, ensure_ascii=False), flush=True)
        if finished(a.log) and n is not None:
            # 收尾: 标 done 后退出
            try:
                st = json.load(open(a.state, encoding="utf-8"))
                st["running"] = False
                st["finished"] = True
                with open(a.state + ".tmp", "w", encoding="utf-8") as f:
                    json.dump(st, f, ensure_ascii=False)
                os.replace(a.state + ".tmp", a.state)
            except Exception:                                    # noqa: BLE001
                pass
            print(json.dumps({"bridge": "done", "final": n}, ensure_ascii=False), flush=True)
            return 0
        time.sleep(a.interval)
    print(json.dumps({"bridge": "timeout", "last": last}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
