#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_se3_engine.py — SE(3) 流形引擎验收 (数学 + 接线 + 实链)

四组判据, 每组都要真数字:
  ① 内核: exp/log 往返、四元数 1 万步不漂、群 vs 解耦差异、测地线不变量、torch↔numpy 一致
  ② 真值守卫: 位姿停更时**必须拒绝预测**(不许拿旧位姿编 7 数)
  ③ 引擎接线: 从在役轨迹建引擎, 接上头逐步 step, rec["se3_pose"] 必须有 7 数、‖q‖=1
  ④ 实链残差: 用仿真真值夹具模拟"位姿在动", 报 1 步前向测地线残差 (与"不动"基线对比)

用法
    python tools/verify_se3_engine.py            # 全跑
    python tools/verify_se3_engine.py --fast     # 跳过仿真夹具 (只 ①②③)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np

ROOT = os.environ.get("ZMAX_ROOT", "/home/ubuntu/zmax")
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tools"))


def _write_pose_fixture(path: str, pose7) -> None:
    """写一个**新鲜**的位姿夹具 (mtime=now)。pose7=[x,y,z,qw,qx,qy,qz]。"""
    p = np.asarray(pose7, float).ravel()
    d = {"ts": time.time(), "t": time.strftime("%F %T"), "frame": "fixture(base_link)",
         "src": "verify_se3_engine: 仿真真值夹具 (不是真机)", "x": float(p[0]), "y": float(p[1]),
         "z": float(p[2]), "qw": float(p[3]), "qx": float(p[4]), "qy": float(p[5]), "qz": float(p[6])}
    tmp = path + ".tmp"
    json.dump(d, open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
    os.replace(tmp, path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true")
    a = ap.parse_args()
    from lerobot.manifold import se3_pose_head as H
    import se3_pose_provider as P            # tools/se3_pose_provider.py
    import ss_engine_loop as EL              # 复用与常驻服务同一套建引擎口径

    rep = {"ts": time.strftime("%Y%m%d_%H%M%S"), "cases": {}}
    ok_all = True

    # ① 内核
    m = H.self_test(verbose=False)
    rep["cases"]["math"] = {k: m[k] for k in ("ok", "exp_log_roundtrip_max", "exp_log_wrap_pose_err",
                                              "quat_norm_drift_10k", "group_vs_decoupled_small",
                                              "group_vs_decoupled_big", "dist_self", "dist_q_neg",
                                              "left_invariance_err", "torch_vs_numpy_step",
                                              "head_out_dim")}
    ok_all &= bool(m["ok"])

    # ② 真值守卫 (用真实位姿文件, 它此刻是否新鲜如实记录)
    real = P.read_pose7()
    prov_real = P.Se3PoseProvider()
    out_real = prov_real(state=None)
    rep["cases"]["guard"] = {"pose_age_s": real.get("age_s"), "ok": out_real.get("ok"),
                             "why": out_real.get("why", ""),
                             "pass": bool((real.get("age_s") or 1e9) > prov_real.max_age_s) == (not out_real.get("ok")),
                             "note": "陈旧时拒绝预测 = 正确行为; 新鲜时必须出 7 数"}
    ok_all &= bool(rep["cases"]["guard"]["pass"])

    # ③ 引擎接线 (在役轨迹真建引擎)
    import ss_engine_loop as _EL
    traj = _EL.read_traj(_EL.TRAJ)
    if not traj:
        rep["cases"]["engine"] = {"ok": False, "why": "在役轨迹唯一依据读不到: %s" % _EL.TRAJ}
        ok_all = False
    else:
        eng, note, _ = EL.build_engine(traj, 3.643, False, True)
        fx = os.path.join(ROOT, "zmax_data/se3_pose_head/pose_fixture.json")
        os.makedirs(os.path.dirname(fx), exist_ok=True)
        p7 = np.concatenate([[0.66, 0.23, 0.23], H.quat_from_rotvec([0.02, -0.01, 0.03])])
        _write_pose_fixture(fx, p7)
        os.environ["SE3_POSE_FIXTURE"] = fx
        prov = P.Se3PoseProvider()
        eng.set_se3_pose_provider(prov, "verify: 仿真夹具位姿 + 训练头")
        rows = []
        for i in range(4):
            st = np.asarray(traj["obs"][min(i, len(traj["obs"]) - 1)], float)
            _write_pose_fixture(fx, p7 + np.array([0.001 * i, 0, 0, 0, 0, 0, 0]))
            rec = eng.step(st, dt=0.1)
            sp = rec.get("se3_pose") or {}
            rows.append({"ok": sp.get("ok"), "n_pose": len(sp.get("pose7_pred") or []),
                         "quat_norm": sp.get("quat_norm"), "xi": sp.get("xi"),
                         "residual_1step": sp.get("residual_1step"),
                         "keys": sorted(sp.keys())})
        good = all(r["ok"] and r["n_pose"] == 7 and abs((r["quat_norm"] or 0) - 1) < 1e-6 for r in rows)
        rep["cases"]["engine"] = {"ok": bool(good), "calib": note, "steps": rows,
                                  "fixture": os.path.relpath(fx, ROOT),
                                  "note": "夹具位姿=仿真真值, 只为验链路; 真机预测需真值在刷"}
        ok_all &= bool(good)

    # ④ 实链残差 (仿真夹具连续 12 拍, 报 1 步残差 vs 不动基线)
    if not a.fast:
        for k, v in {"MUJOCO_GL": "glfw", "DISPLAY": ":0",
                     "XAUTHORITY": "/run/user/1000/gdm/Xauthority"}.items():
            os.environ.setdefault(k, v)
        try:
            from ar_mujoco_env import ArMujocoEnv
            env = ArMujocoEnv(seed=101)     # 训练用 episode seed 7..16 ⇒ 101 是**留出**种子
            obs, _ = env.reset(seed=101)
            for _w in range(20):                                  # 丢掉复位物理瞬态 (与训练同口径)
                obs, *_ = env.step(np.zeros(10))
            rng = np.random.default_rng(101)
            poses, obss, vv = [], [], np.zeros(6)
            for t in range(13):
                p, R = env._tcp()
                poses.append(np.concatenate([p, H.quat_from_R(R)]))
                obss.append(np.asarray(obs, float).ravel())      # 每拍各自的 obs (不能用最后一帧代替)
                vv = 0.8 * vv + rng.normal(0, 0.10, 6)
                act = np.zeros(10)
                act[:6] = vv
                obs, *_ = env.step(act)
            env.close()
            fx = os.path.join(ROOT, "zmax_data/se3_pose_head/pose_fixture_roll.json")
            # 🔴 必须显式给 pose_path: ③ 里设过 SE3_POSE_FIXTURE 环境变量, 不显式传会沿用那个静态夹具
            #    ⇒ 位姿与预测对不上, 残差虚高到 0.9m (踩过)
            prov = P.Se3PoseProvider(pose_path=fx)
            preds, base = [], []
            for k in range(len(poses) - 1):
                _write_pose_fixture(fx, poses[k])
                o = prov(state=obss[k])                        # 潜表示用**这一拍**的真实 obs
                if not o.get("ok"):
                    raise RuntimeError(o.get("why"))
                preds.append((np.asarray(o["pose7_pred"]), poses[k + 1]))
                base.append((poses[k], poses[k + 1]))
            f = lambda pairs, key: float(np.mean([H.pose_distance(a1, b1)[key] for a1, b1 in pairs]))
            res = {"n": len(preds),
                   "pred": {"rot_deg": round(f(preds, "rot_deg"), 4),
                            "trans_mm": round(f(preds, "trans_m") * 1e3, 4)},
                   "baseline_stay": {"rot_deg": round(f(base, "rot_deg"), 4),
                                     "trans_mm": round(f(base, "trans_m") * 1e3, 4)},
                   "pass": True}
            res["better_than_stay"] = bool(res["pred"]["trans_mm"] < res["baseline_stay"]["trans_mm"])
            rep["cases"]["rollout"] = res
            ok_all &= bool(res["better_than_stay"])
        except Exception as e:                                              # noqa: BLE001
            rep["cases"]["rollout"] = {"pass": False, "why": "%s: %s" % (type(e).__name__, str(e)[:200])}
            ok_all = False

    rep["ok"] = bool(ok_all)
    od = os.path.join(ROOT, "reports", "se3_engine")
    os.makedirs(od, exist_ok=True)
    jp = os.path.join(od, rep["ts"] + ".json")
    json.dump(rep, open(jp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print(json.dumps(rep["cases"], ensure_ascii=False, indent=1)[:4000])
    print("\n===> %s · %s" % ("PASS" if rep["ok"] else "FAIL", jp))
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
