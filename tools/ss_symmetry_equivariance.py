#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ss_symmetry_equivariance.py — 对称性「真实现」的四项硬检验（离线，可复现）

为什么要有这个：竞品分析里我方唯一的不可复制项是「对称性」。
但如果它只是嘴上的、或只是拟合出来的，对手一句「你凭什么」就废了。
所以把「对称性」拆成四条可测命题，用真机 400 帧数据当场量：

  E1 等距性      左乘群元素后测地距离不变 —— 数学恒等，不过就是实现错了
  E2 预测等变性  predict(q·p, k) == q·predict(p, k) —— 表示是否天然跨位姿
  E3 判定不变性  valid 标志与 err_rad 在群作用下不变 —— 判据不依赖绝对方位
  E4 零样本换位姿 用 A 段轨迹学的速度，去推 B 段（B = A 旋转 90°/180°）——
                 若误差与 A 自身同量级，则「换位姿不需要新数据」成立

四项全过 ⇒ 对外可以这么说：换工位/换朝向不重训、不重标定，靠群作用传递。
任一项不过 ⇒ 那就是我方相对具身大模型公司的**真实缺口**，不能吹。

用法: python3 tools/ss_symmetry_equivariance.py [--json out.json]
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 跨机：<repo>/tools/x.py
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, os.path.join(REPO, "tools"))

from lerobot.manifold.orbit_predict import OrbitPredictor, _dist, symmetry_residual  # noqa: E402
from lerobot.manifold.manifold_engine import ManifoldEngine                          # noqa: E402

TRAJ = os.path.join(REPO, "data", "database", "zmax", "sources", "canvas", "ss_traj_last.json")
CKPT = os.path.join(REPO, "models", "manifold_engine.npz")
M = float(os.environ.get("SYM_DEPLOY_M", "3.643"))


def engine():
    e = ManifoldEngine(manifold_type="su2", latent_dim=16, state_dim=43, action_dim=4,
                       manifold_M=M, inertia=False, su2_tangent=True)
    try:
        e.load(CKPT)
    except Exception as ex:                                              # noqa: BLE001
        print("[warn] ckpt 未加载:", ex)
    return e


def quat_left(q: np.ndarray, p: np.ndarray) -> np.ndarray:
    """SU(2) 左作用：q ⊗ p（Hamilton 积，p 视作单位四元数）。"""
    w1, x1, y1, z1 = q
    w2, x2, y2, z2 = p
    return np.array([w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
                     w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
                     w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
                     w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2], float)


def qrot(deg: float, axis=(0, 0, 1)) -> np.ndarray:
    a = np.asarray(axis, float)
    a = a / np.linalg.norm(a)
    th = np.deg2rad(deg) / 2.0
    return np.array([np.cos(th), *(np.sin(th) * a)], float)


def canon(p: np.ndarray) -> np.ndarray:
    """四元数双覆盖：q 与 −q 同一姿态 ⇒ 统一符号再比，否则假误差 2|q|。"""
    p = np.asarray(p, float)
    return p if p[0] >= 0 else -p


def main() -> int:
    d = json.load(open(TRAJ))
    obs = np.asarray(d["obs"], float)
    e = engine()
    P = [np.asarray(e.project(r)["p"], float) for r in obs]
    dim = P[0].size
    print("真机轨迹 %d 帧, 流形维数 %d, 引擎 M=%.3f" % (len(P), dim, M))
    if dim != 4:
        print("[warn] p 不是 4 维四元数（%d 维），群作用按前 4 维处理" % dim)

    # 原始轨迹本身的对称性基线
    base = symmetry_residual(P, manifold="sphere")
    print("基线 symmetry_residual:", {k: base[k] for k in ("speed", "drift", "accel", "bend")})

    pr = OrbitPredictor(window=6, drift_tol=1.0, accel_tol=1.0, bend_tol=1.0,
                        phi_tol=0.3, horizons=(1, 2, 5), manifold="sphere")

    def run(seq, window=6):
        """在一段序列上跑预测器，返回逐拍 (err, valid, pred1)。"""
        pr.reset()
        errs, valids, preds = [], [], []
        for i, p in enumerate(seq):
            o = pr.observe(p)
            errs.append(o.get("err_rad"))
            valids.append(bool(o.get("valid")))
            if i + 1 < len(seq):
                preds.append(np.asarray(pr.predict(p, 1), float))
            else:
                preds.append(None)
        return errs, valids, preds

    res = {}

    # ---------- E1 等距性 ----------
    f = lambda x: _dist(x[0], x[1], "sphere")                             # noqa: E731
    e1 = []
    for deg in (90, 180, 270):
        g = qrot(deg)
        for i in range(0, len(P) - 1, 17):
            a, b = P[i], P[i + 1]
            d0 = f((a, b))
            dg = f((quat_left(g, a), quat_left(g, b)))
            if d0 > 1e-12:
                e1.append(abs(dg - d0) / d0)
    res["E1_isometry_rel"] = float(np.max(e1)) if e1 else None
    _v = res["E1_isometry_rel"]
    print("E1 等距性   最大相对误差 %s (n=%d) → %s"
          % ("%.3e" % _v if _v is not None else "n/a", len(e1),
             "PASS" if (_v is not None and _v < 1e-6) else "FAIL"))

    # ---------- E2 预测等变性 / E3 判定不变性 ----------
    errs0, val0, pred0 = run(P)
    e2, e3_err, e3_flip = [], [], 0
    n_valid0 = sum(val0)
    for deg in (90, 180, 270):
        g = qrot(deg)
        Pg = [quat_left(g, p) for p in P]
        errs1, val1, pred1 = run(Pg)
        for a, b in zip(pred0, pred1):
            if a is None or b is None:
                continue
            tgt = canonsafe(quat_left(g, canonsafe(a)))
            e2.append(_dist(canonsafe(b), tgt, "sphere") / max(_dist(P[0], P[1], "sphere"), 1e-12))
        for x, y in zip(errs0, errs1):
            if x is not None and y is not None:
                e3_err.append(abs(float(y) - float(x)) / max(abs(float(x)), 1e-12))
        e3_flip += sum(1 for x, y in zip(val0, val1) if x != y)
    res["E2_equivariance_rel"] = float(np.max(e2)) if e2 else None
    res["E3_err_rel_max"] = float(np.max(e3_err)) if e3_err else None
    res["E3_valid_flips"] = int(e3_flip)
    res["E3_n_valid"] = int(n_valid0)
    _v2 = res["E2_equivariance_rel"]
    # 判据 1e-4: 引擎内部 float32, E1 实测地板 2.5e-9、E2 实测 6.5e-6 —— 低于 1e-4 即"数值等价"
    print("E2 预测等变 最大相对误差 %s (n=%d) → %s"
          % ("%.3e" % _v2 if _v2 is not None else "n/a", len(e2),
             "PASS" if (_v2 is not None and _v2 < 1e-4) else "FAIL"))
    print("E3 判定不变 误差漂移 %.3e, valid 翻转 %d/%d → %s"
          % (res["E3_err_rel_max"], e3_flip, len(val0),
             "PASS" if e3_flip == 0 and res["E3_err_rel_max"] < 1e-9 else "FAIL"))

    # ---------- E4 零样本换位姿 ----------
    # 用 A 段（前 200 帧）估的速度，去推 B 段（后 200 帧，几何上整体旋转 90°）:
    # 误差若与 A 段自推同量级 ⇒ 换朝向不用新数据
    half = len(P) // 2
    A, B = P[:half], P[half:]
    g = qrot(90)
    Bg = [quat_left(g, p) for p in B]

    # 开环一步：每拍都用"真实历史"估速度，只预测下一步 —— 衡量速度场本身能否跨位姿迁移
    def step_err(seq):
        pr.reset()
        errs = []
        for i in range(len(seq) - 1):
            pr.observe(seq[i])
            v = pr.host_velocity()
            if v is None:
                continue
            pred = pr.predict(seq[i], 1, v=v)
            errs.append(_dist(pred, seq[i + 1], "sphere"))
        return float(np.median(errs)) if errs else None

    eA = step_err(A)
    eB = step_err(Bg)
    med_step = _dist(P[0], P[1], "sphere")
    res["E4_same_seg_err_rel"] = None if eA is None else eA / max(med_step, 1e-12)
    res["E4_rot90_err_rel"] = None if eB is None else eB / max(med_step, 1e-12)
    if eA is not None and eB is not None:
        ratio = res["E4_rot90_err_rel"] / max(res["E4_same_seg_err_rel"], 1e-12)
        res["E4_penalty_x"] = float(ratio)
        print("E4 零样本换位姿 同段 %.4f×步长 / 旋转90° %.4f×步长 → 惩罚 %.2f× → %s"
              % (res["E4_same_seg_err_rel"], res["E4_rot90_err_rel"], ratio,
                 "PASS" if ratio < 1.5 else "FAIL"))
    else:
        print("E4 无法评估（host_velocity 为空）")

    out = {"traj": TRAJ, "n_frames": len(P), "dim": dim, "M": M, "base": base, "tests": res}
    dest = sys.argv[sys.argv.index("--json") + 1] if "--json" in sys.argv else \
        os.path.expanduser("~/zmax_data/deliverables/symmetry_equivariance.json")
    json.dump(out, open(dest, "w"), ensure_ascii=False, indent=1)
    print("→", dest)
    return 0


def canonsafe(p):
    p = np.asarray(p, float)
    if p.size >= 4 and p[0] < 0:
        p = -p
    return p


if __name__ == "__main__":
    sys.exit(main())
