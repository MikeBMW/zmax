#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""repair_live_ds.py — 把「5Hz 采样 + 1Hz 真值」造成的重复帧压成真实样本。

现象: 真值约 1Hz 更新, 采集按 5Hz ⇒ 同一姿态被记 5 次(图几乎相同), 动作差分恒 0,
      模型只学到"不动"。这里按**姿态变化**去重: 连续相同姿态(取到 0.1mm)只保留一条,
      并把 dup 计数与真实 dt 记下来, 后续动作标签用真实 dt 归一。

输出: zmax_data/live_ds_fix/<ep>/data/frames.jsonl  (不动原数据, 只读)
判据: 去重前后条数、唯一姿态数、真实 dt 分布、覆盖轨迹包络内的唯一姿态数。
"""
from __future__ import annotations
import glob, json, os
import numpy as np

ROOT = "/home/ubuntu/zmax"
SRC = os.path.join(ROOT, "zmax_data/live_ds")
DST = os.path.join(ROOT, "zmax_data/live_ds_fix")
EPS = 0.1          # 0.1mm 以内算同一姿态


def main() -> int:
    tot_in = tot_out = 0
    for f in sorted(glob.glob(os.path.join(SRC, "episode_*/data/frames.jsonl"))):
        ep = f.split("/")[-3]
        rows = [json.loads(l) for l in open(f)]
        out, last, dup, t_last = [], None, 0, None
        for r in rows:
            p = np.asarray(r["pose7"][:6], float)
            same = last is not None and np.abs(p - last).max() < EPS / 1000.0
            if same:
                dup += 1
                continue
            q = dict(r)
            q["dup"] = dup
            q["dt_real"] = round(float(r["ts"]) - t_last, 3) if t_last else 0.0
            out.append(q)
            last = p
            t_last = float(r["ts"])
            dup = 0
        os.makedirs(os.path.join(DST, ep, "data"), exist_ok=True)
        with open(os.path.join(DST, ep, "data/frames.jsonl"), "w") as g:
            for q in out:
                g.write(json.dumps(q, ensure_ascii=False) + "\n")
        P = np.array([q["pose7"][:3] for q in out]) if out else np.zeros((0, 3))
        env = ((P[:, 0] > 640) & (P[:, 0] < 860) & (P[:, 1] > -300) & (P[:, 1] < 240)
               & (P[:, 2] > 100) & (P[:, 2] < 310)) if len(P) else np.zeros(0, bool)
        dt = np.array([q["dt_real"] for q in out]) if out else np.zeros(1)
        print("%s: %d → %d 条 (%d 条重复) · 轨迹内 %d · dt 中位 %.2fs"
              % (ep, len(rows), len(out), len(rows) - len(out), int(env.sum()),
                 float(np.median(dt[dt > 0])) if (dt > 0).any() else 0.0))
        tot_in += len(rows); tot_out += len(out)
    print(json.dumps({"in": tot_in, "out": tot_out,
                      "dedup_pct": round((1 - tot_out / max(tot_in, 1)) * 100, 1),
                      "out_dir": DST}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
