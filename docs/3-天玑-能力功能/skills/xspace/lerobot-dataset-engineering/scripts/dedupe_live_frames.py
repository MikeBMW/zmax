#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按姿态去重长开采集器的帧序列, 报出"真实样本数 / 真实 dt / 包络内条数"。

为什么需要: 采集采样率高于真值刷新率时, 同一姿态会被记多次 (实测 79% 重复),
动作差分恒 0, 模型只学到"输出 0"。总帧数会骗人, 去重后的条数才是样本量上限。

用法:
  python dedupe_live_frames.py --src zmax_data/live_ds --dst zmax_data/live_ds_fix \\
      --eps 0.1 --envelope 640,860,-300,240,100,310 --only episode_000002

输入布局 (每 episode 一个目录):
  <src>/<ep>/data/frames.jsonl   每行 {ts, pose7:[x,y,z,rx,ry,rz,g], joints6:[...], img:...}
输出布局:
  <dst>/<ep>/data/frames.jsonl   去重后每行多出 dup (被压掉的重复数) 与 dt_real (真实秒差)
图像不复制 (原地还在 src), 下游按 <src>/<ep>/<img> 取图。
"""
from __future__ import annotations

import argparse
import glob
import json
import os

import numpy as np


def env_mask(P, box):
    if not box or len(P) == 0:
        return np.ones(len(P), bool)
    x0, x1, y0, y1, z0, z1 = box
    return ((P[:, 0] > x0) & (P[:, 0] < x1) & (P[:, 1] > y0)
            & (P[:, 1] < y1) & (P[:, 2] > z0) & (P[:, 2] < z1))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="zmax_data/live_ds")
    ap.add_argument("--dst", default="zmax_data/live_ds_fix")
    ap.add_argument("--eps", type=float, default=0.1, help="姿态差小于该值(mm)算同一位姿")
    ap.add_argument("--envelope", default="", help="x0,x1,y0,y1,z0,z1 轨迹包络(mm)")
    ap.add_argument("--only", default="", help="只处理某个 episode 目录名")
    a = ap.parse_args()
    box = [float(v) for v in a.envelope.split(",")] if a.envelope else None

    tot_in = tot_out = 0
    for f in sorted(glob.glob(os.path.join(a.src, "episode_*/data/frames.jsonl"))):
        ep = f.split("/")[-3]
        if a.only and ep != a.only:
            continue
        rows = [json.loads(l) for l in open(f)]
        out, last, dup, t_last = [], None, 0, None
        for r in rows:
            p = np.asarray(r["pose7"][:6], float)
            if last is not None and np.abs(p - last).max() < a.eps / 1000.0:
                dup += 1
                continue
            q = dict(r)
            q["dup"] = dup
            q["dt_real"] = round(float(r["ts"]) - t_last, 3) if t_last else 0.0
            out.append(q)
            last, t_last, dup = p, float(r["ts"]), 0
        os.makedirs(os.path.join(a.dst, ep, "data"), exist_ok=True)
        with open(os.path.join(a.dst, ep, "data/frames.jsonl"), "w") as g:
            for q in out:
                g.write(json.dumps(q, ensure_ascii=False) + "\n")
        P = np.array([q["pose7"][:3] for q in out]) if out else np.zeros((0, 3))
        dt = np.array([q["dt_real"] for q in out]) if out else np.zeros(1)
        med = float(np.median(dt[dt > 0])) if (dt > 0).any() else 0.0
        print("%s: %d → %d 条 (%d 重复) · 包络内 %d · dt 中位 %.2fs"
              % (ep, len(rows), len(out), len(rows) - len(out),
                 int(env_mask(P, box).sum()), med), flush=True)
        tot_in += len(rows)
        tot_out += len(out)
    print(json.dumps({"in": tot_in, "out": tot_out,
                      "dedup_pct": round((1 - tot_out / max(tot_in, 1)) * 100, 1),
                      "out_dir": a.dst}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
