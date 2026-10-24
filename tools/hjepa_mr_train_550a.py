#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🎯 hjepa_mr_train_550a.py — 550A 几何分支训练 (4060, 用 550C 进化出的 HP)

数据来源: **真机** 3DGS 采集任务的位姿 (jobs/*/ds/cameras.json 的 T_cam2world)。
这是真实机械臂轨迹, 不是合成正弦 —— 只有这种数据才能反映域内分布。

监督方式 (JEPA 式自监督, 无 6D 标注):
  ① 相对运动回归: 用真实相邻帧的 SE(3) 相对位移当目标 (T_i⁻¹·T_{i+1} 的 twist)
  ② 切空间 NLL: 训练不确定性校准 (Σ 报得准 = 对未来有把握)
  ③ 法线约束: 球面切向量保持小 (法线缓变)

环境变量:
  MR_HP       550C 回传的 best_hp (JSON)
  MR_A_STEPS  训练步数 (默认 120)
  MR_OUT      输出目录 (ckpt + result.json)
"""
import glob
import json
import os
import os.path as osp
import sys
import time

import numpy as np

ROOT = os.environ.get("ZMAX_ROOT", "/home/ubuntu/zmax")
for _p in (osp.join(ROOT, "src"), ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import torch                                                           # noqa: E402

from lerobot.manifold.hjepa_manifold import (                          # noqa: E402
    build_geometric_branch, ema_update, make_momentum_target)
from lerobot.manifold.lie_intent import se3_log, so3_log               # noqa: E402


def nll_torch(mu, x, log_sigma, sigma_min=5e-3):
    """切空间对角高斯 NLL (torch 版, **带 σ 下限**)。

    `hjepa_manifold.tangent_gaussian_nll` 是 **numpy** 实现, 直接塞进训练循环会
    返回 float 而不是 tensor (backward 断链)。这里内联等价式:
        NLL = 0.5·Σ[(x−μ)²/σ² + 2·log σ]      (忽略常数项)

    🔴 σ 下限是必须的: 实测不加时 σ 一路压到 0, NLL 从 -11.6 掉到 -26.7 (模型
    靠"声称自己绝对准"刷分, 而 reg 早已收敛到 1e-4), 最后一步还反弹到 -4.5。
    插装配 5mm 已经是"对不准"的量级, 再小就没物理意义了。
    """
    ls = torch.clamp(log_sigma, min=float(np.log(sigma_min)))
    sig2 = torch.exp(2.0 * ls)
    return 0.5 * (((x - mu).pow(2) / sig2) + 2.0 * ls).sum(dim=-1)

HP = json.loads(os.environ.get("MR_HP", "{}"))
STEPS = int(os.environ.get("MR_A_STEPS", "120"))
OUT = os.environ.get("MR_OUT", ".")


def load_real_poses():
    """从真机 3DGS 任务读位姿序列 (T_cam2world 4x4)。返回 (Ts, 源文件)。"""
    pats = [osp.join(ROOT, "gs_train_service/jobs/*/ds/cameras.json"),
            "/home/ubuntu/gs_train_service/jobs/*/ds/cameras.json"]
    best = None
    for pat in pats:
        try:
            files = sorted(glob.glob(pat), key=lambda x: -os.path.getmtime(x))[:8]
        except Exception:                                              # noqa: BLE001
            files = []
        for f in files:
            try:
                d = json.load(open(f))
            except Exception:                                          # noqa: BLE001
                continue
            fr = d.get("frames") or d.get("cameras") or []
            if len(fr) < 20:
                continue
            if best is None or len(fr) > len(best[1]):
                best = (f, fr)
    if not best:
        return None, None
    src, frames = best
    Ts = []
    for e in frames:
        m = (e.get("T_cam2world") or e.get("T") or e.get("transform_matrix")
             or e.get("T_base2cam"))
        if m is None:
            continue
        try:
            arr = np.asarray(m, float)
            if arr.shape == (4, 4):
                Ts.append(arr)
        except Exception:                                              # noqa: BLE001
            pass
    return (np.stack(Ts) if Ts else None), src


def poses_to_state7(Ts):
    """SE(3) 序列 → state7 (xyz + 旋转向量 + 占位夹爪)。"""
    out = []
    for T in Ts:
        w = so3_log(T[:3, :3])
        out.append([T[0, 3], T[1, 3], T[2, 3], w[0], w[1], w[2], 0.5])
    return np.asarray(out, dtype=np.float32)


def main():
    torch.manual_seed(int(HP.get("seed", 0)))
    dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print("[550A] device=%s" % dev, flush=True)
    print("[550A] HP=%s" % json.dumps(HP, ensure_ascii=False)[:260], flush=True)

    Ts, src = load_real_poses()
    if Ts is None:
        print("[550A] ❌ 找不到真实位姿数据 (gs_train_service/jobs/*/ds/cameras.json)",
              flush=True)
        return 2
    print("[550A] 真实位姿 %d 帧 ← %s" % (len(Ts), src), flush=True)

    s7 = poses_to_state7(Ts)
    dp = np.linalg.norm(np.diff(s7[:, :3], axis=0), axis=1)
    print("[550A] 帧间位移 min/med/max = %.4f / %.4f / %.4f m"
          % (dp.min(), np.median(dp), dp.max()), flush=True)
    if float(np.median(dp)) < 1e-4:
        print("[550A] ⚠ 帧间位移中位 <0.1mm: 这批位姿几乎是同一个点, "
              "训练几何分支学不到运动。先确认数据源。", flush=True)

    d_g = int(HP.get("d_g", 128))
    n_layers = int(HP.get("n_layers", 2))
    lr = float(HP.get("lr", 3e-3))
    mom = float(HP.get("momentum", 0.99))
    lam_v = float(HP.get("lam_v", 0.5))

    br = build_geometric_branch(d_in=256, d_g=d_g, n_layers=n_layers,
                               with_uncertainty=True).to(dev)
    tg = make_momentum_target(br)
    rs = np.random.RandomState(int(HP.get("seed", 0)) + 7)
    proj = torch.from_numpy((rs.normal(size=(7, 256)) / np.sqrt(7)).astype(np.float32)).to(dev)

    # 目标: 相邻帧真实相对运动的 twist
    tgt_xi = []
    for i in range(len(Ts) - 1):
        Trel = np.linalg.inv(Ts[i]) @ Ts[i + 1]
        tgt_xi.append(se3_log(Trel))
    tgt_xi = torch.from_numpy(np.asarray(tgt_xi, np.float32)).to(dev)
    s7t = torch.from_numpy(s7).to(dev)
    print("[550A] 目标 twist 模长 med=%.5f (前 3 个: %s)"
          % (float(np.median(np.linalg.norm(tgt_xi.cpu().numpy(), axis=1))),
             np.round(tgt_xi[0].cpu().numpy(), 5).tolist()), flush=True)

    opt = torch.optim.Adam(br.parameters(), lr=lr)
    n_par = sum(p.numel() for p in br.parameters())
    print("[550A] 几何分支 %d 参数, 训 %d 步" % (n_par, STEPS), flush=True)

    t0 = time.time()
    hist = []
    bs = min(32, max(2, len(s7t) - 2))
    for step in range(STEPS):
        idx = torch.randint(0, len(s7t) - 1, (bs,), device=dev)
        h = s7t[idx] @ proj
        o = br(h)
        xi = o["xi"]
        vn = o["v_n"]
        ls = o["log_sigma"]
        loss_reg = (xi - tgt_xi[idx]).pow(2).mean()
        nll = nll_torch(xi, tgt_xi[idx], ls[:, :6]).mean()
        loss_v = vn.pow(2).mean()
        # NLL 权重 0.3→0.1: 实测 0.3 时 NLL 主导, reg 收敛到 1e-4 后还在被 NLL 拖着抖
        loss = loss_reg + 0.1 * nll + lam_v * 0.1 * loss_v
        opt.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(br.parameters(), 1.0)
        opt.step()
        ema_update(tg, br, mom)
        if step % 20 == 0 or step == STEPS - 1:
            sig_mean = float(torch.exp(ls).mean())
            hist.append({"step": step, "loss": round(float(loss), 6),
                         "reg": round(float(loss_reg), 6),
                         "nll": round(float(nll), 6),
                         "sigma_mean": round(sig_mean, 6)})
            print("[550A] step %3d loss=%.6f reg=%.6f nll=%.6f σ=%.4f"
                  % (step, float(loss), float(loss_reg), float(nll), sig_mean),
                  flush=True)

    secs = time.time() - t0
    os.makedirs(OUT, exist_ok=True)
    ck = osp.join(OUT, "geometric_branch_550a.pt")
    torch.save({"hp": HP, "state_dict": br.state_dict(), "n_params": n_par,
                "frames": int(len(Ts)), "steps": STEPS, "data_src": src}, ck)

    first = hist[0]["loss"] if hist else None
    last = hist[-1]["loss"] if hist else None
    res = {"ok": True, "n_params": n_par, "frames": int(len(Ts)), "steps": STEPS,
           "secs": round(secs, 1), "loss_first": first, "loss_last": last,
           "ckpt": ck, "data_src": src, "device": str(dev), "hist": hist,
           "dp_med": round(float(np.median(dp)), 6),
           "note": "自监督 (真实相邻帧相对 twist), 无 6D 标注"}
    print("__RESULT__" + json.dumps(res, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
