#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用真机 TCP/关节序列训练分层 H-JEPA, 并与线性外推基线同口径对比。

数据: zmax_data/ss_live/state_2026MMDD.jsonl (10Hz 主循环, tcp 真值)
口径: 每个样本 = 历史 T 帧状态 -> 预测未来 K 帧 (K = micro_horizon*micro_substep)
基线: 线性外推 (last + k*(last - prev)), 同一批样本、同一范数
判据: 模型 RMSE 必须低于基线, 否则如实报"无提升"。

用法:
    PYTHONPATH=src ./gui-venv311/bin/python tools/train_hjepa_hier.py \
        --jsonl zmax_data/ss_live/state_20261120.jsonl --steps 400
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src"))

from lerobot.manifold.engine.hjepa_hier import HierConfig, HierHJEPA  # noqa: E402


# --------------------------------------------------------------- 数据
def _row_vec(d, dim_ft=6, dim_j=7):
    """把一行 jsonl 拆成定长状态向量 (24 维), 缺失补 0 并记录有效性。"""
    v = np.zeros(24, dtype=np.float32)
    ok = True
    tcp = d.get("tcp")
    if not tcp or not isinstance(tcp, (list, tuple)) or len(tcp) < 3:
        return None, False
    v[0:3] = np.asarray(tcp[:3], dtype=np.float32)
    q = d.get("tcp_quat")
    if q and len(q) >= 4:
        v[3:7] = np.asarray(q[:4], dtype=np.float32)
    else:
        v[3] = 1.0                       # 单位四元数 w=1, 表示"无姿态信息"
        ok = False
    jp = d.get("jpos")
    if jp and isinstance(jp, (list, tuple)) and len(jp) >= dim_j:
        v[7:7 + dim_j] = np.asarray(jp[:dim_j], dtype=np.float32)
    jv = d.get("jvel")
    if jv and isinstance(jv, (list, tuple)) and len(jv) >= dim_j:
        v[14:14 + dim_j] = np.asarray(jv[:dim_j], dtype=np.float32)
    ft = d.get("ft")
    if ft and isinstance(ft, (list, tuple)) and len(ft) >= dim_ft:
        v[21:21 + min(dim_ft, 3)] = np.asarray(ft[:3], dtype=np.float32)
    g = d.get("gripper")
    if isinstance(g, (int, float)):
        v[23] = float(g)
    return v, ok


def load_series(path, max_rows=400_000, stride=1):
    rows, t0 = [], None
    n_ok = 0
    with open(path, encoding="utf-8", errors="ignore") as f:
        for i, line in enumerate(f):
            if i >= max_rows:
                break
            try:
                d = json.loads(line)
            except Exception:
                continue
            v, ok = _row_vec(d)
            if v is None:
                continue
            n_ok += 1
            rows.append(v)
    return np.stack(rows, 0) if rows else np.zeros((0, 24), np.float32), n_ok


def make_windows(X, T, K, n_samples, seed=0, min_move_mm=15.0):
    """X:(N,24) -> (hist:(n,T,24), future:(n,K,24))。

    ★ 只从【运动窗口】切样本。实测 state_20261120 位移中位 0.000 mm/步、19.5% 在动,
      静止窗口会主导训练集 -> 模型学成"预测不动", 自然打不过"保持基线"。
      判据: 窗口内首末位置差 >= min_move_mm, 且窗口内累计位移 >= min_move_mm。
    """
    rng = np.random.RandomState(seed)
    N = X.shape[0]
    span = T + K
    if N < span + 1:
        raise SystemExit("序列太短: %d < %d" % (N, span + 1))

    # 先算逐步位移, 用它筛"有运动"的起点 (避免在静止段采一堆样本)
    step_mm = np.linalg.norm(np.diff(X[:, :3], axis=0), axis=1) * 1000.0
    csum = np.concatenate([[0.0], np.cumsum(step_mm)])      # csum[i] = 前 i 步累计
    cand = np.arange(0, N - span)
    if len(cand) == 0:
        raise SystemExit("没有可用起点")
    span_move = csum[cand + span] - csum[cand]
    ok = span_move >= min_move_mm
    n_ok = int(ok.sum())
    print("    运动窗口 %d / %d (%.1f%%), 阈值 %.0fmm"
          % (n_ok, len(cand), 100.0 * n_ok / max(1, len(cand)), min_move_mm), flush=True)
    if n_ok < 50:
        print("    ⚠️ 运动窗口太少, 放宽到 5mm", flush=True)
        ok = span_move >= 5.0
        cand = cand[ok]
    else:
        cand = cand[ok]
    if len(cand) == 0:
        raise SystemExit("无运动窗口")
    pick = rng.choice(cand, size=min(n_samples, len(cand)), replace=False)
    H = np.stack([X[s:s + T] for s in pick], 0)
    F = np.stack([X[s + T:s + T + K] for s in pick], 0)
    return H.astype(np.float32), F.astype(np.float32)


# --------------------------------------------------------------- 基线
def baseline_linear(hist, K):
    """线性外推: 用最后两帧速度外推。hist:(n,T,24) -> (n,K,24)。"""
    last = hist[:, -1]
    if hist.shape[1] >= 2:
        vel = hist[:, -1] - hist[:, -2]
    else:
        vel = np.zeros_like(last)
    return np.stack([last + vel * (k + 1) for k in range(K)], 1).astype(np.float32)


def baseline_hold(hist, K):
    """保持基线: 一直维持最后一帧 (最朴素的对手)。"""
    last = hist[:, -1]
    return np.stack([last for _ in range(K)], 1).astype(np.float32)


def rmse_mm(a, b):
    """位置三轴 (米) -> mm RMSE。"""
    d = (a[..., :3] - b[..., :3]) * 1000.0
    return float(np.sqrt((d ** 2).mean()))


# --------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jsonl", default="zmax_data/ss_live/state_20261120.jsonl")
    ap.add_argument("--steps", type=int, default=400)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--samples", type=int, default=6000)
    ap.add_argument("--hist", type=int, default=20)
    ap.add_argument("--out", default="models/hjepa_hier_v1.pt")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--lam-sym", type=float, default=1.0,
                    help="辛守恒损失权重 (λ1); 加大可压住匀速段的漂移")
    args = ap.parse_args()

    t_start = time.time()
    p = args.jsonl if os.path.isabs(args.jsonl) else os.path.join(REPO, args.jsonl)
    print("[1] 读数据 %s" % p, flush=True)
    X, n_ok = load_series(p, max_rows=400_000)
    print("    有效状态 %d 行 · 形状 %s" % (n_ok, X.shape), flush=True)

    # 训练口径 micro_substep=1: 每 macro 大步只走 1 次 leapfrog。
    # 每步 10x10 次 leapfrog x2 autograd = 200 次反传, 实测 21s/步训不动;
    # 显式辛欧拉对任意 dt 都保辛, 子步只影响能量漂移幅度, 推理侧仍用 10 子步。
    cfg = HierConfig(d_x=24, d_z=256, nq=10, macro_horizon=15, micro_horizon=10,
                     micro_substep=1, macro_stride=5, n_layers=3, n_heads=4,
                     lam_col=1.0, lam_sym=args.lam_sym)
    K = cfg.micro_horizon

    print("[2] 切窗口 T=%d K=%d" % (args.hist, K), flush=True)
    H, F = make_windows(X, args.hist, K, args.samples, seed=args.seed)
    n = H.shape[0]
    n_tr = int(n * 0.8)
    Htr, Ftr = H[:n_tr], F[:n_tr]
    Hte, Fte = H[n_tr:], F[n_tr:]
    print("    训练 %d / 测试 %d" % (n_tr, len(Hte)), flush=True)

    # 归一化口径: 用训练集的均值方差, 测试集同口径 (防泄漏)
    mu = Htr.reshape(-1, 24).mean(0)
    sd = Htr.reshape(-1, 24).std(0) + 1e-6
    Htr_n = (Htr - mu) / sd
    Ftr_n = (Ftr - mu) / sd
    Hte_n = (Hte - mu) / sd
    # ★ delta 口径: 目标 = 未来末帧 − 当前末帧, 与线性外推/保持基线同一比较基准。
    #   🔴 归一化必须用 delta 自己的 std —— 位置 sd 比位移 sd 大一个量级,
    #   用位置 sd 归一化会把位移压成 1e-3 量级, 模型等于学不到速度 (实测回退 500%)。
    Dtr_raw = Ftr - Htr[:, -1:]
    sd_delta = Dtr_raw.reshape(-1, 24).std(0) + 1e-6
    Dtr_n = Dtr_raw / sd_delta

    print("[3] 建模 (d_z=%d, nq=%d, 参数量见下)" % (cfg.d_z, cfg.nq), flush=True)
    m = HierHJEPA(cfg, device=args.device)
    n_par = sum(pp.numel() for pp in m.parameters())
    print("    参数量 %s" % format(n_par, ","), flush=True)

    opt = m.torch.optim.AdamW(list(m.parameters()), lr=args.lr, weight_decay=1e-4)
    sched = m.torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=max(1, args.steps))

    print("[4] 训练 %d 步 (batch %d)" % (args.steps, args.batch), flush=True)
    rng = np.random.RandomState(args.seed)
    log_every = max(1, args.steps // 12)
    t_tr = time.time()
    for step in range(1, args.steps + 1):
        idx = rng.randint(0, n_tr, size=min(args.batch, n_tr))
        xb = m.torch.as_tensor(Htr_n[idx], dtype=m.torch.float32, device=m.device)
        fb = m.torch.as_tensor(Ftr_n[idx], dtype=m.torch.float32, device=m.device)
        db = m.torch.as_tensor(Dtr_n[idx], dtype=m.torch.float32, device=m.device)
        # JEPA 标准: 目标由同一编码器给出, 但 stop-gradient, 防塌缩靠 variance 项
        z_tgt = m.enc(fb).detach()
        st = m.train_step(xb, z_tgt, opt, x_target=db)   # 观测目标 = delta
        sched.step()
        if step % log_every == 0 or step == 1 or step == args.steps:
            el = time.time() - t_tr
            print("    [%4d/%d] total %.4f · jepa %.4f · energy %.4f · collapse %.4f · %.1fs"
                  % (step, args.steps, st["total"], st["jepa"], st["energy"],
                     st["collapse"], el), flush=True)

    # ---------------------------------------------------------- 评测
    print("[5] 评测 (同口径: 位置三轴 mm RMSE)", flush=True)
    m.eval_mode()
    torch = m.torch
    with torch.no_grad():
        xb = torch.as_tensor(Hte_n, dtype=torch.float32, device=m.device)
        out = m.forward(xb)
        # 评测口径: 解码器直出观测状态 (与训练同源), 再反归一化回米。
        # 不再用"潜空间线性探针" —— 实测塌缩时探针会给出 129mm 的假差。
        x_hat = out["x_hat"][:, -1].cpu().numpy()
    pred_pos = (Hte[:, -1, :3] + x_hat[:, :3] * sd_delta[:3]).astype(np.float32)
    W = np.zeros((1, 3), np.float32)   # 兼容报告字段 (探针已弃用)

    true_pos = Fte[:, -1, :3]
    base_lin = baseline_linear(Hte, K)[:, -1, :3]
    base_hold = baseline_hold(Hte, K)[:, -1, :3]

    def r3(a, b):
        d = (a - b) * 1000.0
        return float(np.sqrt((d ** 2).mean()))

    e_model = r3(pred_pos, true_pos)
    e_lin = r3(base_lin, true_pos)
    e_hold = r3(base_hold, true_pos)
    print("    模型     RMSE %.2f mm" % e_model, flush=True)
    print("    线性外推 RMSE %.2f mm" % e_lin, flush=True)
    print("    保持基线 RMSE %.2f mm" % e_hold, flush=True)
    best_base = min(e_lin, e_hold)
    gain = (best_base - e_model) / best_base * 100.0
    print("    → 相对最强基线 %s %.1f%%"
          % ("提升" if gain > 0 else "回退", abs(gain)), flush=True)

    # 分段: 用【末帧速度】和【加速度】把测试样本分成平动/变速两档。
    # 匀速段线性外推近乎最优, 只有在变速段模型才可能赢 —— 分开报, 才看得出真实价值。
    v_last = np.linalg.norm((Hte[:, -1, :3] - Hte[:, -2, :3]) * 1000.0, axis=1)
    if Hte.shape[1] >= 3:
        a_last = np.linalg.norm((Hte[:, -1, :3] - 2 * Hte[:, -2, :3] + Hte[:, -3, :3]) * 1000.0, axis=1)
    else:
        a_last = np.zeros_like(v_last)
    med_a = float(np.median(a_last))
    mask_dyn = a_last > med_a          # 加速度高于中位 = 变速样本
    print("    速度: 中位 %.3f mm/步 · 加速度中位 %.4f mm/步²" %
          (float(np.median(v_last)), med_a), flush=True)
    for tag, msk in (("匀速/低加速", ~mask_dyn), ("变速/高加速", mask_dyn)):
        if msk.sum() < 10:
            continue
        em = r3(pred_pos[msk], true_pos[msk])
        el = r3(base_lin[msk], true_pos[msk])
        eh = r3(base_hold[msk], true_pos[msk])
        eb = min(el, eh)
        g = (eb - em) / eb * 100.0
        print("    [%s] n=%d  模型 %.2f · 线性 %.2f · 保持 %.2f → %s %.1f%%"
              % (tag, int(msk.sum()), em, el, eh,
                 "提升" if g > 0 else "回退", abs(g)), flush=True)
    dyn_gain = None
    if mask_dyn.sum() >= 10:
        dyn_gain = (min(r3(base_lin[mask_dyn], true_pos[mask_dyn]),
                        r3(base_hold[mask_dyn], true_pos[mask_dyn]))
                    - r3(pred_pos[mask_dyn], true_pos[mask_dyn])) \
                   / min(r3(base_lin[mask_dyn], true_pos[mask_dyn]),
                         r3(base_hold[mask_dyn], true_pos[mask_dyn])) * 100.0

    # ---------------------------------------------------------- 辛守恒实测
    print("[6] 辛守恒实测 (跑满 micro 子步)", flush=True)
    with torch.no_grad():
        out_te = m.forward(torch.as_tensor(Hte_n[:200], dtype=torch.float32, device=m.device))
    Hv = out_te["H"].cpu().numpy()
    dH = Hv[:, 1:] - Hv[:, :-1]
    inc = float((dH > 1e-6).mean() * 100)
    print("    能量不增步占比 %.1f%% (越高越守规矩)" % (100 - inc), flush=True)
    print("    能量相对漂移 mean|ΔH|/|H| = %.4f"
          % float(np.abs(dH).mean() / (np.abs(Hv).mean() + 1e-9)), flush=True)

    # ---------------------------------------------------------- 存盘
    outp = os.path.join(REPO, args.out)
    os.makedirs(os.path.dirname(outp), exist_ok=True)
    m.save(outp)
    report = {
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "jsonl": os.path.relpath(p, REPO),
        "cfg": cfg.__dict__,
        "params": int(n_par),
        "steps": args.steps,
        "train_seconds": round(time.time() - t_tr, 1),
        "eval_mm_rmse": {"model": round(e_model, 2), "linear": round(e_lin, 2),
                         "hold": round(e_hold, 2)},
        "gain_vs_best_baseline_pct": round(gain, 2),
        "gain_dynamic_pct": (round(dyn_gain, 2) if dyn_gain is not None else None),
        "energy_nonincrease_pct": round(100 - inc, 1),
        "weights": os.path.relpath(outp, REPO),
        "norm": {"mu": mu.tolist(), "sd": sd.tolist(), "sd_delta": sd_delta.tolist()},
        "probe_W": W.tolist(),
    }
    rp = outp.replace(".pt", "_report.json")
    with open(rp, "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print("[7] 已存 %s" % os.path.relpath(outp, REPO), flush=True)
    print("    报告 %s" % os.path.relpath(rp, REPO), flush=True)
    print("总耗时 %.1fs" % (time.time() - t_start), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
