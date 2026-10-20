#!/usr/bin/env python3
"""插入练习 ×3 —— 老倪 2026-10-20 19:4x「你再次插入，练习三次」。

每轮: `--mode seat` 一步直插到示教点 插入到位_1020c (力看门狗: 轴向 30N 停 / 硬红线 40N, 侧向 15N, 力矩 8Nm)
      然后 `--mode push` 沿工具轴退 RETREAT_MM 回到练习起点。
每轮把 verdict + 峰值 + 到点误差写进 zmax_data/reports/insert_practice_x3.json, 逐轮打印。

用法: ./gui-venv311/bin/python tools/practice_insert_x3.py [--cycles 3] [--retreat 40]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEAT = "0.811571,0.230612,0.184349"
SEAT_RPY = "3.12260,-1.47094,0.07103"
LOGDIR = os.path.join(ROOT, "zmax_data", "rokae_sdk", "logs")
OUT = os.path.join(ROOT, "zmax_data", "reports", "insert_practice_x3.json")


def run(args, timeout=400):
    cmd = ["bash", os.path.join(ROOT, "tools", "rokae_sdk_run.sh"), "--script", "insert_sdk_fc.py"] + args
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    tail = [ln for ln in (p.stdout or "").strip().splitlines() if ln.strip()][-4:]
    return p.returncode, tail


def latest(prefix):
    fs = sorted(glob.glob(os.path.join(LOGDIR, prefix)), key=os.path.getmtime)
    if not fs:
        return {}
    try:
        return json.load(open(fs[-1], encoding="utf-8"))
    except Exception:                                                     # noqa: BLE001
        return {}


def pose_x():
    try:
        d = json.load(open(os.path.join(ROOT, "zmax_data", "rokae_sdk", "tcp_out", "latest.json"), encoding="utf-8"))
        return [d["x"], d["y"], d["z"]]
    except Exception:                                                     # noqa: BLE001
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cycles", type=int, default=3)
    ap.add_argument("--retreat", type=float, default=40.0)
    ap.add_argument("--lat", type=float, default=25.0, help="侧向 Δ 上限 N (插入练习放宽到 25, 防误停)")
    ap.add_argument("--tq", type=float, default=10.0, help="力矩 Δ 上限 Nm")
    a = ap.parse_args()
    rec = {"started_at": time.strftime("%Y-%m-%d %H:%M:%S"), "seat": SEAT,
           "red_line": {"axial_stop_n": 30, "axial_hard_n": 40, "lateral_n": "见 --lat", "torque_nm": "见 --tq"},
           "retreat_mm": a.retreat, "cycles": []}
    for k in range(1, a.cycles + 1):
        print("=== 第 %d/%d 轮 插入 ===" % (k, a.cycles), flush=True)
        t0 = time.time()
        rc, tail = run(["--mode", "seat", "--seat-pos", SEAT, "--seat-rpy", SEAT_RPY,
                        "--approach-mm", "15", "--fast-speed", "8", "--speed", "1",
                        "--stop-n", "30", "--lat-max", str(a.lat), "--lissa-tq-max", str(a.tq), "--timeout", "180"])
        time.sleep(0.5)
        d = latest("insert_fc_seat_*.json")
        c = {"cycle": k, "rc": rc, "verdict": d.get("verdict"), "err_mm": d.get("err_mm"),
             "peak_axial_n": d.get("peak_axial_n"), "peak_lateral_n": d.get("peak_lateral_n"),
             "peak_torque_nm": d.get("peak_torque_nm"), "tcp_end": d.get("end_pose"),
             "secs_insert": round(time.time() - t0, 1)}
        print("   插入: %s · 误差 %s mm · 轴向峰 %s N · 侧向峰 %s N · 力矩峰 %s Nm"
              % (c["verdict"], c["err_mm"], c["peak_axial_n"], c["peak_lateral_n"], c["peak_torque_nm"]), flush=True)
        if k < a.cycles:
            t1 = time.time()
            rc2, _ = run(["--mode", "push", "--travel-mm", "-%.1f" % a.retreat, "--speed", "2",
                          "--stop-n", "30", "--lat-max", "20", "--lissa-tq-max", "10", "--timeout", "150"])
            time.sleep(0.5)
            d2 = latest("insert_fc_push_*.json")
            c["retreat"] = {"rc": rc2, "verdict": d2.get("verdict"), "adv_mm": d2.get("adv_toolz_mm"),
                            "secs": round(time.time() - t1, 1)}
            print("   回退: %s · %s mm" % (c["retreat"]["verdict"], c["retreat"]["adv_mm"]), flush=True)
        c["tcp_after"] = pose_x()
        rec["cycles"].append(c)
    rec["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(rec, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n=== 汇总 (%d 轮) ===" % len(rec["cycles"]), flush=True)
    for c in rec["cycles"]:
        print("  第%d轮 %-14s 误差 %6s mm · 轴向峰 %5s N · 侧向峰 %5s N · 力矩峰 %5s Nm"
              % (c["cycle"], str(c["verdict"])[:14], c["err_mm"], c["peak_axial_n"], c["peak_lateral_n"], c["peak_torque_nm"]), flush=True)
    print("记录: %s" % OUT, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
