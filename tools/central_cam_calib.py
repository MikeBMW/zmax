#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""central_cam_calib.py — 中央相机(8812, 640x480 USB)标定: 已知 base 点 + 像素点 → K/fx + R,t。

背景(2026-11-19 老倪): 「中央相机正在看着两个插口, 你注意到了么？」
  实测: L5 在中央画面上能认出两个金属笼插口(conf 0.5~0.55), 但**中央相机没有任何内参/外参标定**
  (models/ 下只有臂上 D405 的 real_cam_calib.json) ⇒ 它的像素换不成毫米, 只能"看得见", 不能"量得准"。

本脚本解决"怎么标定":
  输入 correspondence: [{"name":..., "p_base_mm":[x,y,z], "px":[u,v]}, ...]  (≥6 个点, 最好不共面)
  模型: 针孔 + 畸变≈0 + 方像素 + 主点≈中心(可关) ⇒ 未知 = fx + rvec(3) + tvec(3) = 7
  求解: scipy least_squares 最小化重投影误差
  输出: models/central_cam_calib.json {K, dist, R, t, T_base2cam, rms_px, n, note}
  校验: 逐点重投影残差 + 把已知插口点投到图上(可肉眼对)

用法:
  ./gui-venv311/bin/python tools/central_cam_calib.py solve --pairs zmax_data/calib/central_pairs.json
  ./gui-venv311/bin/python tools/central_cam_calib.py validate
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "models", "central_cam_calib.json")
W, H = 640, 480

# 已知插口几何(base_link, mm) —— 用于 validate 与"点不出 6 个点时"的先验
PORT_PTS = {
    "下口口沿-左": [761.3, 222.5, 192.3],
    "下口口沿-右": [761.3, 237.1, 192.3],
    "下口内底-左": [811.6, 222.5, 182.8],
    "下口内底-右": [811.6, 237.1, 182.8],
    "上口口沿-左": [764.3, 218.5, 299.9],
    "上口口沿-右": [764.3, 233.1, 299.9],
}


def _load_pairs(path: str):
    d = json.load(open(path, encoding="utf-8"))
    pts = d["points"] if isinstance(d, dict) else d
    P, uv, names = [], [], []
    for it in pts:
        P.append(it["p_base_mm"])
        uv.append(it["px"])
        names.append(it.get("name", "p%d" % len(names)))
    return np.array(P, float), np.array(uv, float), names


def _proj(params, P):
    fx, rv, tv = params[0], params[1:4], params[4:7]
    from scipy.spatial.transform import Rotation as Rot
    R = Rot.from_rotvec(rv).as_matrix()
    Pc = (R @ P.T).T + tv
    u = fx * Pc[:, 0] / Pc[:, 2] + W / 2.0
    v = fx * Pc[:, 1] / Pc[:, 2] + H / 2.0
    return np.stack([u, v], 1), Pc


def solve(pairs_path: str, fx0: float = 600.0, free_principal: bool = False) -> int:
    from scipy.optimize import least_squares
    P, uv, names = _load_pairs(pairs_path)
    assert len(P) >= 6, "至少要 6 个点(不共面更佳), 现在 %d" % len(P)
    if free_principal:
        print("⚠️ 自由主点需要 ≥10 点, 当前 %d" % len(P))
    # 初值: 相机大致在 port 前方 500mm、朝 -x 看
    p0 = np.array([fx0, 0.0, 0.0, 0.0, P[:, 0].mean() + 0.45, P[:, 1].mean(), P[:, 2].mean()])

    def resid(x):
        pr, _ = _proj(x, P)
        return (pr - uv).ravel()

    r = least_squares(resid, p0, method="lm", max_nfev=20000)
    pr, Pc = _proj(r.x, P)
    err = np.linalg.norm(pr - uv, axis=1)
    from scipy.spatial.transform import Rotation as Rot
    R = Rot.from_rotvec(r.x[1:4]).as_matrix()
    t = r.x[4:7]
    K = [[r.x[0], 0, W / 2.0], [0, r.x[0], H / 2.0], [0, 0, 1]]
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = t
    out = {"schema": "zmax.central_cam_calib.v1", "K": K, "dist": [0, 0, 0, 0, 0],
           "R": R.tolist(), "t": t.tolist(), "T_cam2base": T.tolist(),
           "T_base2cam": np.linalg.inv(T).tolist(),
           "rms_px": float(np.sqrt((err ** 2).mean())), "max_px": float(err.max()),
           "n_points": int(len(P)), "wh": [W, H],
           "note": "方像素+主点居中; 由 %s 求解" % os.path.basename(pairs_path)}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("fx %.1f · RMS %.2f px · max %.2f px · 点 %d" % (r.x[0], out["rms_px"], out["max_px"], len(P)))
    for n, e, p in zip(names, err, pr):
        print("  %-14s 残差 %5.2f px  → 投 (%.0f, %.0f)" % (n, e, p[0], p[1]))
    print("写入 %s" % os.path.relpath(OUT, ROOT))
    return 0


def validate() -> int:
    d = json.load(open(OUT, encoding="utf-8"))
    K = np.array(d["K"], float)
    T = np.array(d["T_base2cam"], float)          # base→cam
    print("RMS %.2f px · fx %.1f · 点 %d" % (d["rms_px"], K[0, 0], d["n_points"]))
    for n, P in PORT_PTS.items():
        Pc = (T @ np.array(P + [1.0]))[:3]
        uv = K @ (Pc / Pc[2])
        inside = 0 <= uv[0] < W and 0 <= uv[1] < H
        print("  %-12s → px (%6.1f, %6.1f)  z_cam %.0fmm  %s" % (
            n, uv[0], uv[1], Pc[2] * 1000, "在画面内" if inside else "画面外/投影异常"))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["solve", "validate", "template"])
    ap.add_argument("--pairs", default=os.path.join(ROOT, "zmax_data", "calib", "central_pairs.json"))
    ap.add_argument("--fx0", type=float, default=600.0)
    a = ap.parse_args()
    if a.cmd == "template":
        tpl = {"schema": "zmax.central_pairs.v1", "wh": [W, H],
               "points": [{"name": n, "p_base_mm": P, "px": [0, 0]} for n, P in PORT_PTS.items()]}
        os.makedirs(os.path.dirname(a.pairs), exist_ok=True)
        json.dump(tpl, open(a.pairs, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("模板 → %s (把 px 填成中央相机画面上的像素坐标)" % os.path.relpath(a.pairs, ROOT))
        return 0
    return solve(a.pairs, a.fx0) if a.cmd == "solve" else validate()


if __name__ == "__main__":
    sys.exit(main())
