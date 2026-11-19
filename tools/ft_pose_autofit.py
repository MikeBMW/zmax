#!/usr/bin/env python3
"""ft_pose_autofit.py — 盯着力+姿态采样, 姿态多样性一达标就自动拟合重力/零偏并报阈值。

为什么这样设计: 拟合必须有"同一工具、不同朝向"的力读数; 实测 427 帧四元数完全相同时
最小二乘会给出 m=−9226 kg 这种退化解。所以不猜、不等我说, 由数据自己触发:
    每 5s 算姿态多样性 spread = mean(1 − dᵢ·dⱼ) (d = 工具 z 轴在世界系)
    spread ≥ --spread (默认 0.30) 且帧数 ≥ 200 ⇒ 跑 ft_gravity_fit --fit, 打印结果后退出

用法: python3 -u tools/ft_pose_autofit.py [--mins 30] [--spread 0.30]
退出码: 0 = 拟合完成 / 1 = 超时(多样性一直不够) / 2 = 没采到数据
"""
import argparse
import glob
import json
import os
import subprocess
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "zmax_data", "rokae_sdk", "ft_out")


def latest_file():
    fs = sorted(glob.glob(os.path.join(OUT, "ft_pose_*.jsonl")))
    return fs[-1] if fs else None


def spread_of(path, tail=400):
    rows = []
    with open(path, "rb") as f:
        f.seek(max(0, os.path.getsize(path) - 120000))
        for ln in f.read().decode("utf-8", "ignore").splitlines()[-tail:]:
            if not ln.strip():
                continue
            try:
                r = json.loads(ln)
            except Exception:                                                # noqa: BLE001
                continue
            q = r.get("quat")
            if q and len(q) == 4:
                rows.append(q)
    if len(rows) < 8:
        return 0.0, len(rows)
    qs = np.asarray(rows, dtype=float)
    qs = qs / np.linalg.norm(qs, axis=1, keepdims=True)
    x, y, z, w = qs.T
    # 工具 z 轴 (world→tool 的第三列) 作为朝向代表
    d = np.stack([2 * (x * z + y * w), 2 * (y * z - x * w), w * w + z * z - x * x - y * y], 1)
    d = d / np.linalg.norm(d, axis=1, keepdims=True)
    S = 1 - d @ d.T
    return float(S.mean()), len(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mins", type=float, default=30.0)
    ap.add_argument("--spread", type=float, default=0.30)
    a = ap.parse_args()
    t_end = time.time() + a.mins * 60
    last = None
    while time.time() < t_end:
        fp = latest_file()
        if not fp:
            time.sleep(5)
            continue
        sp, n = spread_of(fp)
        line = "姿态多样性 %.3f (帧 %d / 需 ≥%d)" % (sp, n, 200)
        if line != last and int(time.time()) % 30 < 5:
            print("%s %s" % (time.strftime("%H:%M:%S"), line), flush=True)
            last = line
        if sp >= a.spread and n >= 200:
            print("%s 多样性达标 %.3f ⇒ 自动拟合" % (time.strftime("%H:%M:%S"), sp), flush=True)
            r = subprocess.run(["python3", os.path.join(ROOT, "tools/ft_gravity_fit.py"), "--fit", fp],
                               capture_output=True, text=True, timeout=300)
            print(r.stdout[-2000:] or r.stderr[-800:], flush=True)
            return 0
        time.sleep(5)
    print("[timeout] %.0f 分钟多样性一直不够 (spread<%.2f) ⇒ 臂没有真的换姿态" % (a.mins, a.spread), flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
