#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""se3_pose_head_train.py — 训练 SE(3) 7 维位姿预测头 (6 维 ξ → 指数映射 → 7 数)

数据: AR 工位 MuJoCo 真值 (ar_mujoco_env) —— 位姿来自几何体真值 `_tcp()` (不是运动学手推),
      动作是随机平滑 OU 序列, 所以**真的在动**, 才谈得上"预测下一拍位姿"。
潜输入: obs(实测 39 维) → PCA(16) (与引擎内建编码器同一算法, 同一维数)。
标签:   ξ_true = log(T_t⁻¹·T_{t+1})  ∈ se(3)  [ρ; φ]
损失:   SE(3) 测地线损失 (旋转角 + 平移距离), **不**逐元素回归四元数。

判据 (都要跟"不动"基线比, 否则等于自证):
  · 1 步预测: 平移 mm / 旋转 deg 必须 < 零增量基线
  · 四元数: 预测输出的 ‖q‖ 恒 =1 (由流形保证, 不是网络学的)
  · 消融: 同一损失下预测"不动"的基线数字一并报出

用法
    python tools/se3_pose_head_train.py --train --episodes 8 --steps 120 --epochs 600
    python tools/se3_pose_head_train.py --selftest
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
OUT = os.path.join(ROOT, "zmax_data/se3_pose_head")
CKPT = os.path.join(OUT, "head.pt")
META = os.path.join(OUT, "train_meta.json")

WARMUP = 20          # 复位瞬态步数 (丢弃)
ENV_GL = {"MUJOCO_GL": "glfw", "DISPLAY": ":0", "XAUTHORITY": "/run/user/1000/gdm/Xauthority"}


def _H():
    from lerobot.manifold import se3_pose_head as H
    return H


def collect(episodes: int = 8, steps: int = 120, seed: int = 7):
    """跑 AR 工位仿真, 采 (obs, pose7) 真值对。返回 obs[N,43], pose7[N,7], ep[N]。"""
    for k, v in ENV_GL.items():
        os.environ.setdefault(k, v)
    from ar_mujoco_env import ArMujocoEnv
    H = _H()
    import mujoco  # noqa: F401
    env = ArMujocoEnv(seed=seed)
    rng = np.random.default_rng(seed)
    OBS, POSE, EP = [], [], []
    for e in range(episodes):
        obs, _ = env.reset(seed=seed + e)
        v = np.zeros(6)                                   # OU 速度 (平滑, 不是白噪声抖)
        # 🔴 复位后有 10~20 步物理瞬态 (实测单步 0.21m/32°, 不是任务动作) ⇒ 必须丢掉,
        #    否则模型学的是"复位冲击"而不是"运动动力学", 评测也会被瞬态主导。
        for _w in range(WARMUP):
            a = np.zeros(10)
            obs, *_ = env.step(a)
        for t in range(steps + 1):
            p, R = env._tcp()                             # 🔴 几何真值 (MJ 前向后的体位置矩阵)
            OBS.append(np.asarray(obs, float).ravel())   # 实际 39 维 (tcp_p 0:3 + 相对位移 7:10 + tcp_R 24:33)
            POSE.append(np.concatenate([np.asarray(p, float), H.quat_from_R(R)]))
            EP.append(e)
            if t == steps:
                break
            v = 0.82 * v + rng.normal(0.0, 0.10, 6)
            a = np.zeros(10)
            a[:6] = v                                     # env.step 会再 ×0.8 并 clip
            a[6] = 0.0
            obs, *_ = env.step(a)
    env.close()
    return np.asarray(OBS, float), np.asarray(POSE, float), np.asarray(EP, int)


def build_head(latent_dim=16, hidden=128, torch=None):
    from lerobot.manifold.se3_pose_head import build_head as _b
    return _b(latent_dim=latent_dim, hidden=hidden, torch=torch)


def train(a) -> dict:
    import torch
    from lerobot.manifold import se3_pose_head as H
    from lerobot.manifold.manifold_engine import Encoder

    t0 = time.time()
    obs, pose, ep = collect(a.episodes, a.steps, a.seed)
    # 潜表示: 同引擎内建编码器 (PCA)
    enc = Encoder(a.latent_dim)
    enc.fit(obs)
    Z = np.stack([enc.encode(o) for o in obs])
    # 标签: 相邻两拍 (同一条 episode 内)
    idx = [(i, i + 1) for i in range(len(pose) - 1) if ep[i] == ep[i + 1]]
    z_t = np.stack([Z[i] for i, _ in idx])
    p_t = np.stack([pose[i] for i, _ in idx])
    p_n = np.stack([pose[j] for _, j in idx])
    # 按 episode 划分 (同一条轨迹不能跨 train/test)
    eps = sorted(set(ep.tolist()))
    te_eps = set(eps[::4])                                # 每 4 条取 1 条做测试
    te = np.array([ep[i] in te_eps for i, _ in idx])
    tr = ~te
    torch.manual_seed(a.seed)
    head = build_head(a.latent_dim, a.hidden, torch)
    opt = torch.optim.AdamW(head.parameters(), lr=a.lr, weight_decay=1e-4)

    def _t(x):
        return torch.tensor(np.asarray(x, dtype=np.float32))

    zt_tr, pt_tr, pn_tr = _t(z_t[tr]), _t(p_t[tr]), _t(p_n[tr])
    hist = []
    bs = min(a.batch, len(zt_tr))
    for ep_i in range(a.epochs):
        perm = torch.randperm(len(zt_tr))[:bs]
        z, p, pn = zt_tr[perm], pt_tr[perm], pn_tr[perm]
        pred = head.predict_pose(z, p)                    # 6 维 ξ → 7 维
        loss, parts = H.geodesic_loss(pred, pn)
        opt.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(head.parameters(), 1.0)
        opt.step()
        if ep_i % max(1, a.epochs // 12) == 0 or ep_i == a.epochs - 1:
            hist.append({"epoch": ep_i, "loss": round(float(loss), 6),
                         "rot_deg": round(float(parts["rot_rad"].mean()) * 57.2958, 3),
                         "trans_mm": round(float(parts["trans_m"].mean()) * 1e3, 3)})

    # ── 评测 (test episode, 同一口径; 与"不动"基线比) ──
    def _eval(z, p, pn):
        with torch.no_grad():
            pred = head.predict_pose(_t(z), _t(p)).numpy()
        d_pred = [H.pose_distance(pr, tv) for pr, tv in zip(pred, pn)]
        d_base = [H.pose_distance(pp, tv) for pp, tv in zip(p, pn)]        # 基线: 预测"不动"
        f = lambda ds, k: float(np.mean([d[k] for d in ds]))
        return {"n": len(z), "pred": {"rot_deg": round(f(d_pred, "rot_deg"), 4),
                                      "trans_mm": round(f(d_pred, "trans_m") * 1e3, 4),
                                      "se3": round(f(d_pred, "se3"), 6)},
                "baseline_stay": {"rot_deg": round(f(d_base, "rot_deg"), 4),
                                  "trans_mm": round(f(d_base, "trans_m") * 1e3, 4),
                                  "se3": round(f(d_base, "se3"), 6)},
                "quat_norm_max_dev": round(float(np.abs(np.linalg.norm(pred[:, 3:7], axis=1) - 1).max()), 12)}

    res = {"ok": True, "n_pairs": int(len(idx)), "n_train": int(tr.sum()), "n_test": int(te.sum()),
           "episodes": int(a.episodes), "steps": int(a.steps), "latent_dim": int(a.latent_dim),
           "epochs": int(a.epochs), "sec": round(time.time() - t0, 1),
           "train": _eval(z_t[tr], p_t[tr], p_n[tr]),
           "test": _eval(z_t[te], p_t[te], p_n[te]) if te.any() else {"n": 0},
           "hist": hist,
           "meta": {"pose_src": "ar_mujoco_env._tcp() (MuJoCo 几何真值)",
                    "latent_src": "%d 维 obs → PCA(%d) (与引擎内建编码器同算法)" % (obs.shape[1], a.latent_dim),
                    "label": "ξ = log(T_t⁻¹T_{t+1}), 损失=SE(3) 测地线",
                    "domain": "仿真 (AR 工位); 真机未标定"}}
    if res["test"].get("n"):
        res["improved"] = bool(res["test"]["pred"]["trans_mm"] < res["test"]["baseline_stay"]["trans_mm"]
                               and res["test"]["pred"]["rot_deg"] < res["test"]["baseline_stay"]["rot_deg"])
        # float32 归一化后 |‖q‖−1| ≈ 6e-8 是正常量级 (double 才 1e-16) ⇒ 阈值给 1e-6
        res["ok"] = bool(res["improved"] and res["test"]["quat_norm_max_dev"] < 1e-6)
    os.makedirs(OUT, exist_ok=True)
    torch.save({"state_dict": head.state_dict(), "latent_dim": a.latent_dim, "hidden": a.hidden,
                "max_trans": head.max_trans, "max_rot": head.max_rot,
                "pca_mu": enc.mu.tolist(), "pca_W": enc.W.tolist(),
                "obs_dim": int(obs.shape[1]),
                "feature_note": "obs 含 tcp_p(0:3)+tcp_R(24:33) ⇒ 本头学的是**动力学**(下一拍增量), 不是视觉位姿识别",
                "meta": res["meta"]}, CKPT)
    json.dump(res, open(META, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    res["ckpt"] = CKPT
    return res


def selftest() -> int:
    H = _H()
    r = H.self_test(verbose=False)
    ok = bool(r.get("ok"))
    print("① 内核数学自检: %s (往返 %.2e, 四元数漂移 %.2e)"
          % ("OK" if ok else "FAIL", r["exp_log_roundtrip_max"], r["quat_norm_drift_10k"]))
    obs, pose, ep = collect(episodes=1, steps=6, seed=3)
    ok2 = (obs.shape[1] >= 33 and pose.shape[1] == 7
           and float(np.abs(np.linalg.norm(pose[:, 3:7], axis=1) - 1).max()) < 1e-9
           and float(np.ptp(pose[:, 2])) > 0)          # TCP 真的有位移
    print("② 采集自检: %s · obs%s pose%s · z 跨度 %.4f m · |q| 偏差 %.1e"
          % ("OK" if ok2 else "FAIL", obs.shape, pose.shape, float(np.ptp(pose[:, 2])),
             float(np.abs(np.linalg.norm(pose[:, 3:7], axis=1) - 1).max())))
    print("✅ 自检通过" if (ok and ok2) else "❌ 自检失败")
    return 0 if (ok and ok2) else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--episodes", type=int, default=8)
    ap.add_argument("--steps", type=int, default=120)
    ap.add_argument("--latent-dim", type=int, default=16)
    ap.add_argument("--hidden", type=int, default=128)
    ap.add_argument("--epochs", type=int, default=600)
    ap.add_argument("--batch", type=int, default=128)
    ap.add_argument("--lr", type=float, default=2e-3)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.train:
        r = train(a)
        print(json.dumps({k: r[k] for k in ("ok", "n_pairs", "n_train", "n_test", "sec",
                                            "train", "test", "improved", "ckpt")},
                         ensure_ascii=False, indent=1))
        return 0 if r["ok"] else 1
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
