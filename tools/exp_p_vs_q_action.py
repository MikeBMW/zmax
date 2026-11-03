#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""exp_p_vs_q_action.py — 引擎该用哪个四元数当状态点: 用动作解释力判定 (不是拍脑袋)

对照三路 (同一批 357 帧, 同一份动作真值 u_exec):
  A. p_project  = 引擎 project(43D) 的四元数      ← 现在在用的
  B. q_exec     = 统一状态空间 L2 几何误差群点
  C. u_scene    = 统一状态空间四层合成态 U_L2⊗L3⊗L4⊗L5
做法: 每路四元数 → 岭回归拟合 4 维动作, 时序切分 (前 70% 训 / 后 30% 测), 比留出集 RMSE。
判据: 谁能更好地解释动作, 谁就该当引擎的状态点 (readout 是按它拟合的)。
"""
import json
import os
import sys

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (REPO, os.path.join(REPO, "src"),
          os.path.join(REPO, "src", "lerobot", "policies", "left_right", "state_space")):
    if p not in sys.path:
        sys.path.insert(0, p)

import pose_caliper as pc                                        # noqa: E402
from lerobot.manifold.manifold_engine import ManifoldEngine      # noqa: E402
from lerobot.policies.left_right.state_space import su2 as SU    # noqa: E402

TRAJ = os.path.join(REPO, "data", "database", "zmax", "sources", "canvas", "ss_traj_last.json")
CKPT = os.path.join(REPO, "models", "manifold_engine.npz")


def ridge_fit(X, Y, lam=1e-2):
    Xb = np.hstack([X, np.ones((len(X), 1))])
    A = Xb.T @ Xb + lam * np.eye(Xb.shape[1])
    W = np.linalg.solve(A, Xb.T @ Y)
    return W


def ridge_pred(X, W):
    return np.hstack([X, np.ones((len(X), 1))]) @ W


def main() -> int:
    d = json.load(open(TRAJ, encoding="utf-8"))
    O = np.asarray(d["obs"], float)[:, :43]
    U = np.asarray(d.get("u_exec_vec") or [], float)
    if U.size == 0:
        U = np.asarray(d.get("action") or [], float)
    U = U.reshape(len(U), -1)
    n = min(len(O), len(U))
    O, U = O[:n], U[:n]
    eng = ManifoldEngine(manifold_type="su2", latent_dim=16, state_dim=43, action_dim=4,
                         manifold_M=3.643, inertia=False, su2_tangent=True)
    eng.load(CKPT)

    P, Q, S = [], [], []
    _q = lambda u: np.array([u.w, u.x, u.y, u.z], float)          # noqa: E731
    for o in O:
        P.append(np.asarray(eng.project(o)["p"], float).ravel())
        lay = SU.encode_layers({}, o)          # 无 frame ⇒ L3/L4/L5 落单位元, 只 L2 吃几何
        Q.append(_q(lay["L2"]))
        S.append(_q(SU.compose_scene(lay)))
    P, Q, S = np.asarray(P), np.asarray(Q), np.asarray(S)
    cut = int(n * 0.7)
    rows = []
    for name, X in (("A_p_project", P), ("B_q_exec(L2)", Q), ("C_u_scene(四层)", S)):
        # 四元数双覆盖: 统一到与首帧同符号, 否则线性模型看到两个相反输入
        Xn = X.copy()
        for i in range(1, len(Xn)):
            if float(np.dot(Xn[i], Xn[i - 1])) < 0:
                Xn[i] = -Xn[i]
        W = ridge_fit(Xn[:cut], U[:cut])
        pr = ridge_pred(Xn[cut:], W)
        rmse = float(np.sqrt(((pr - U[cut:]) ** 2).mean()))
        rows.append({"route": name, "holdout_rmse": round(rmse, 6),
                     "per_dim": [round(float(x), 5) for x in np.sqrt(((pr - U[cut:]) ** 2).mean(0))]})
    base = rows[0]["holdout_rmse"]
    for r in rows:
        r["vs_p_project"] = round(r["holdout_rmse"] / max(base, 1e-12), 4)
    rep = {"frames": int(n), "train": int(cut), "holdout": int(n - cut),
           "action_dim": int(U.shape[1]), "routes": rows,
           "action_range": [round(float(x), 3) for x in (U.max(0) - U.min(0))],
           "note": "动作是仿真真值 u_exec; RMSE 越小 = 该四元数对动作的解释力越强"}
    os.makedirs(os.path.join(REPO, "reports"), exist_ok=True)
    with open(os.path.join(REPO, "reports", "p_vs_q_action.json"), "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1)
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
