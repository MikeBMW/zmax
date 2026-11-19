#!/usr/bin/env python3
"""ft_gravity_fit.py — 用现场采样拟合「工具重力 + 零点偏置」, 输出接触力口径。

模型 (与实测一致): 控制器 getEndTorque 给的是**带未补偿工具重力**的读数, 且随姿态转,
所以按工具系建模:
    F_meas(q) = m · R(q)ᵀ · ḡ + b        ḡ = (0, 0, −9.81) m/s², R(q) 由四元数 (x,y,z,w) 给
  未知量: m (kg) 与 b (3 维, 工具系下的零偏/残余)  ⇒ 线性最小二乘, 4 个未知数
  接触力 = F_meas − (m·Rᵀ·ḡ + b)

判据: 拟合残差 RMS 决定接触阈值 (取 3σ, 但不低于 1.5N)。

用法:
  python3 tools/ft_gravity_fit.py --fit zmax_data/rokae_sdk/ft_out/ft_pose_20261119.jsonl
  python3 tools/ft_gravity_fit.py --self-test          # 合成数据自检 (不碰真机)
  python3 tools/ft_gravity_fit.py --apply zmax_data/rokae_sdk/ft_out/ft_direct_20261119.jsonl --params ...
"""
import argparse
import json
import math
import os
import sys

import numpy as np

G = 9.80665
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARAMS = os.path.join(ROOT, "zmax_data", "ft_contact", "gravity_params.json")


def quat_R(q):
    """四元数 (x,y,z,w) → 旋转矩阵 world←tool"""
    x, y, z, w = [float(v) for v in q]
    n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def fit(rows):
    """rows: [{fx,fy,fz,quat}] → (m, b, residual_rms, n)"""
    A, y = [], []
    for r in rows:
        q = r.get("quat")
        if not q or len(q) != 4:
            continue
        u = quat_R(q).T @ np.array([0.0, 0.0, -G])          # 重力在工具系下的向量
        A.append([u[0], 1, 0, 0])
        y.append(float(r["fx"]))
        A.append([u[1], 0, 1, 0])
        y.append(float(r["fy"]))
        A.append([u[2], 0, 0, 1])
        y.append(float(r["fz"]))
    if len(y) < 12:
        return None
    A = np.asarray(A)
    y = np.asarray(y)
    sol, *_ = np.linalg.lstsq(A, y, rcond=None)
    m, b = float(sol[0]), [float(v) for v in sol[1:4]]
    pred = A @ sol
    rms = float(np.sqrt(np.mean((pred - y) ** 2)))
    # 姿态多样性 (工具轴在球面上的分布): 越大越好, <0.3 说明只测了相近姿态
    dirs = []
    for r in rows:
        q = r.get("quat")
        if q and len(q) == 4:
            dirs.append(quat_R(q)[:, 2])
    spread = 0.0
    if len(dirs) >= 2:
        D = np.asarray(dirs)
        spread = float(np.mean(1 - D @ D.T))
    return {"m_kg": m, "b": b, "residual_rms_N": rms, "n_frames": len(rows),
            "spread": spread, "thr_N": max(1.5, 3.0 * rms)}


def apply(rows, m, b):
    out = []
    for r in rows:
        q = r.get("quat")
        if not q or len(q) != 4:
            continue
        u = quat_R(q).T @ np.array([0.0, 0.0, -G])
        g = m * u + np.asarray(b)
        c = np.array([float(r["fx"]), float(r["fy"]), float(r["fz"])]) - g
        out.append((r.get("ts"), [float(v) for v in c]))
    return out


def self_test():
    rng = np.random.default_rng(0)
    m_true, b_true = 1.62, np.array([1.3, -0.7, 2.1])
    rows = []
    for _ in range(60):
        q = rng.normal(size=4)
        q = (q / np.linalg.norm(q)).tolist()
        u = quat_R(q).T @ np.array([0.0, 0.0, -G])
        f = m_true * u + b_true + rng.normal(scale=0.15, size=3)
        rows.append({"quat": q, "fx": f[0], "fy": f[1], "fz": f[2]})
    r = fit(rows)
    print(json.dumps({"self_test": True, "m_true": m_true, "b_true": b_true.tolist(),
                      "fit": r}, ensure_ascii=False, indent=1))
    ok = abs(r["m_kg"] - m_true) < 0.02 and max(abs(np.array(r["b"]) - b_true)) < 0.5
    print("自检:", "通过" if ok else "不通过")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fit")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--apply")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    if a.fit:
        rows = [json.loads(l) for l in open(a.fit, encoding="utf-8") if l.strip()]
        r = fit(rows)
        if not r:
            print("样本不足 (需要 ≥4 帧带 quat 的)", flush=True)
            return 1
        os.makedirs(os.path.dirname(PARAMS), exist_ok=True)
        json.dump(r, open(PARAMS, "w"), ensure_ascii=False, indent=1)
        print(json.dumps(r, ensure_ascii=False, indent=1))
        if r["spread"] < 0.3:
            print("⚠ 姿态多样性只有 %.2f ⇒ 拟合不可信, 再多摆 3~4 个不同姿态重采" % r["spread"], flush=True)
        return 0
    if a.apply:
        p = json.load(open(PARAMS, encoding="utf-8"))
        rows = [json.loads(l) for l in open(a.apply, encoding="utf-8") if l.strip()]
        out = apply(rows, p["m_kg"], p["b"])
        if not out:
            print("该文件没有 quat 字段 ⇒ 只能用 ft_pose_*.jsonl", flush=True)
            return 1
        mags = [math.sqrt(sum(v * v for v in c)) for _, c in out]
        mags.sort()
        print("接触力口径 · 帧 %d · 中位 |Fc| %.2f N · P95 %.2f N · 阈值建议 %.2f N" % (
            len(mags), mags[len(mags) // 2], mags[int(len(mags) * 0.95)], p["thr_N"]))
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
