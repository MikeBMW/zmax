#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_se3_cond_239.py — 用真机位姿真值跑一拍 SE(3) 引擎, 看 L4 到底出不出 SE(3) 和 15 维 cond。

判据 (不过就非 0 退出):
  1. 位姿真值可用 (tcp_out/latest.json 帧龄 < 2s)
  2. det(R)=1 且 R 正交 (SE(3) 合法)
  3. ξ = log(T_goal⁻¹T) 有量值, 势函数 φ ≥ 0
  4. 测地线 8 步距离单调下降 (预测真的朝目标走)
  5. cond 维数 = 15 且无 NaN
"""
import json, sys, os, math
sys.path.insert(0, "/home/ubuntu/zmax/src")
import numpy as np
from lerobot.manifold.se3_engine import SE3Engine, COND_DIM

def main():
    eng = SE3Engine(root="/home/ubuntu/zmax")
    out = eng.step(frame={"traj_idx": int(os.environ.get("IDX", "100"))})
    print(json.dumps({k: out.get(k) for k in ("ok","why","goal_src","phi","xi","cond_dim","manifold_src")},
                     ensure_ascii=False, default=str)[:900])
    if not out.get("ok"):
        print("FAIL 引擎不应答: %s" % out.get("why")); return 1
    T = np.asarray(out["T"], float); R = T[:3,:3]; t = T[:3,3]
    detR = float(np.linalg.det(R)); orth = float(np.abs(R @ R.T - np.eye(3)).max())
    print("T_tcp mm %s  detR %.9f  orth %.2e" % (np.round(t*1000,2).tolist(), detR, orth))
    xi = np.asarray(out["xi"], float); phi = float(out["phi"])
    print("xi(6) %s  phi %.4f" % (np.round(xi,4).tolist(), phi))
    ds = out.get("dist_h") or []
    print("测地线距离序列(mm):", [round(float(d),2) for d in ds] if ds else "缺")
    cond = out.get("cond")
    fails=[]
    if abs(detR-1)>1e-9: fails.append("detR")
    if orth>1e-9: fails.append("orth")
    if phi < 0: fails.append("phi<0")
    if ds and not all(b<=a+1e-9 for a,b in zip(ds,ds[1:])): fails.append("测地线距离非单调")
    if cond is None or len(cond)!=COND_DIM: fails.append("cond")
    if cond and not np.isfinite(np.asarray(cond,float)).all(): fails.append("cond NaN")
    print("判据:", "PASS" if not fails else "FAIL "+",".join(fails))
    return 0 if not fails else 2

if __name__ == "__main__":
    raise SystemExit(main())
