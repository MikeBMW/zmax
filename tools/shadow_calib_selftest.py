#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧪 影子模式自标定引擎单测 (合成数据, 不碰真机):
  ① 已知 X_R 合成 40 对 (ΔR_tcp 随机 1~20°, R_cam = X_R^T ΔR_tcp X_R + 噪声)
     ⇒ summary 应报残差≈0, 留出集通过, 反解与真值差≈0;
  ② 把标定换成错的 X_R(偏 25°) ⇒ 应报 mismatch / 不 accepted。
"""
import json, math, sys
import numpy as np

sys.path.insert(0, "/home/ubuntu/zmax/tools")
import shadow_mode_550c as S


def rand_R(deg):
    ax = np.random.randn(3); ax /= np.linalg.norm(ax)
    th = math.radians(deg)
    Kx = np.array([[0, -ax[2], ax[1]], [ax[2], 0, -ax[0]], [-ax[1], ax[0], 0]])
    return np.eye(3) + math.sin(th) * Kx + (1 - math.cos(th)) * Kx @ Kx


def noise(R, deg):
    return rand_R(deg) @ R


def run(true_X, calib_X, n=40, seed=0):
    np.random.seed(seed)
    c = S.ShadowCalib.__new__(S.ShadowCalib)
    c.X_R = calib_X
    c.pairs, c.cand_R, c.src = [], None, "synthetic"
    c.pb, c.lag = None, 0.0
    import cv2
    c.cv2 = cv2
    for _ in range(n):
        dR = rand_R(np.random.uniform(1.5, 20.0))
        Rc = noise(true_X.T @ dR @ true_X, 0.6)
        c.add_pair(dR, Rc, 0.8)
    return c.summary(), c.cand_R


def main():
    true_X = rand_R(38.0) @ rand_R(11.0)
    ok = True
    sm, cand = run(true_X, true_X)
    print("① 正确标定:", json.dumps(sm, ensure_ascii=False))
    ok &= sm["pairs"] == 40 and sm["resid_old_deg_median"] < 1.5
    # 标定本来就对 ⇒ 不替换(accepted False)但反解应与真值一致
    ok &= (not sm.get("accepted")) and sm["holdout_resid_new_deg"] < 1.5 and sm["delta_from_handeye_deg"] < 2.0

    wrong = rand_R(25.0) @ true_X
    sm2, cand2 = run(true_X, wrong)
    print("② 错标定:", json.dumps(sm2, ensure_ascii=False))
    ok &= sm2["resid_old_deg_median"] > 3 and sm2["status"] in ("mismatch", "suspect")
    ok &= bool(sm2.get("accepted")) and sm2["holdout_resid_new_deg"] < 1.5

    # 反解出来的 X_R 与真值对齐 (含 180° 对称解检验)
    if cand2 is not None:
        d = S.ang_deg(cand2.T @ true_X)
        print("③ 反解 vs 真值: %.2f°" % d)
        ok &= d < 2.0

    print(json.dumps({"selftest": "PASS" if ok else "FAIL"}))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
