#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""夜间训练 (Night-mode training) —— 在 550C 上用 XPU 真训一个动力学头, 过闸才上线。

为什么夜间要"训练"而不只是"统计":
白天的 RLS 线性头只能吃掉一阶趋势; 白天日志里真正难的是**拐点/启停/接触**这些非线性段。
夜间把日志按时间顺序拼成 (z_t → z_{t+1}) 序列, 训一个小 MLP, 才是"提取泛化"。

口径:
  z = [Θ/100mm, p/0.05, H/0.1]   (与相位窗口/能量模块同源)
  基线 = 持续性预测(y = x)      ← 任何模型必须显著赢它才有意义(否则只是"没学坏")
  闸门 = 留出集 RMSE ≤ 基线 × 0.97  且  留出集 H 的物理 RMSE 有改善

产物:
  zmax_data/daynight/models/dyn_<ver>.pt        权重
  zmax_data/daynight/models/dyn_<ver>.json      参数量/轮数/时长/RMSE
  通过 → 原子写入 current.json 的 dyn 段(在线只读 current.json)
"""
from __future__ import annotations

import json
import math
import os
import time

from . import daylog
from .phase import DN_DIR, read_state, start_night, end_night, write_state

MODEL_DIR = os.path.join(DN_DIR, "models")
PRIOR = os.path.join(DN_DIR, "current.json")
SCALE = (100.0, 0.05, 0.1)

GATE_IMPROVE = 0.03


def _dev():
    dev = os.environ.get("ZMAX_DN_DEVICE", "").strip()
    if dev:
        return dev
    try:
        import torch
        if hasattr(torch, "xpu") and torch.xpu.is_available():
            return "xpu"
        if torch.cuda.is_available():
            return "cuda"
    except Exception:                                              # noqa: BLE001
        pass
    return "cpu"


def build_pairs(recs: list[dict], max_gap_s: float = 0.6, horizon: int = 20) -> tuple[list, list]:
    """(z_t → z_{t+horizon})。为什么要跨步:

    98Hz 采样下相邻帧几乎相同 ⇒ "预测下一帧=复制当前帧"(persistence)近乎无敌,
    实测 1 步 MLP 反而输给它 3.3%(闸门正确拒绝)。跨 20 步(≈0.2s)才是动力学该赢的地方。
    """
    z = []
    for r in recs:
        z.append((float(r["th_mm"]) / SCALE[0], float(r["p"]) / SCALE[1],
                  float(r["H"]) / SCALE[2], float(r["ts"])))
    xs, ys = [], []
    for i in range(len(z) - horizon):
        a, b = z[i], z[i + horizon]
        if 1e-4 < b[3] - a[3] <= max_gap_s * horizon:
            xs.append(a[:3])
            ys.append(b[:3])
    return xs, ys


def train(day_id: str = "", epochs: int = 30, promote_if_pass: bool = True, tag: str = "",
          horizon: int = 20) -> dict:
    os.makedirs(MODEL_DIR, exist_ok=True)
    import torch
    import torch.nn as nn

    st = start_night("夜间训练" + (("(%s)" % tag) if tag else ""))
    if not day_id:
        day_id = daylog.latest_with_data()
        if not day_id:
            end_night(False, why="夜间训练中止: 没有白天日志")
            return {"ok": False, "why": "没有白天日志"}

    recs = [r for r in daylog.read(day_id)
            if all(isinstance(r.get(k), (int, float)) for k in ("ts", "th_mm", "p", "H"))]
    recs.sort(key=lambda r: r["ts"])
    xs, ys = build_pairs(recs, horizon=horizon)
    if len(xs) < 200:
        end_night(False, why="夜间训练中止: 序列样本 %d < 200" % len(xs))
        return {"ok": False, "why": "序列样本不足", "n": len(xs)}

    cut = int(len(xs) * 0.8)
    Xtr = torch.tensor(xs[:cut], dtype=torch.float32)
    Ytr = torch.tensor(ys[:cut], dtype=torch.float32)
    Xho = torch.tensor(xs[cut:], dtype=torch.float32)
    Yho = torch.tensor(ys[cut:], dtype=torch.float32)

    dev = _dev()
    torch.manual_seed(0)
    net = nn.Sequential(nn.Linear(3, 64), nn.SiLU(), nn.Linear(64, 64), nn.SiLU(), nn.Linear(64, 3)).to(dev)
    nparam = sum(p.numel() for p in net.parameters())
    opt = torch.optim.Adam(net.parameters(), lr=1e-3)
    lossf = nn.MSELoss()
    bs = 512
    t0 = time.time()
    hist = []

    print("夜间训练: 设备=%s 参数量=%d 跨度=%d帧 样本 训练 %d / 留出 %d 轮数=%d batch=%d"
          % (dev, nparam, horizon, len(Xtr), len(Xho), epochs, bs), flush=True)
    for ep in range(1, epochs + 1):
        perm = torch.randperm(len(Xtr))
        tot = 0.0
        nb = 0
        for i in range(0, len(Xtr), bs):
            idx = perm[i:i + bs]
            xb, yb = Xtr[idx].to(dev), Ytr[idx].to(dev)
            opt.zero_grad()
            out = xb + net(xb)          # 残差学习: 学 Δ 而非绝对值
            loss = lossf(out, yb)
            loss.backward()
            opt.step()
            tot += float(loss.detach().cpu())
            nb += 1
        hist.append(round(tot / max(1, nb), 8))
        if ep == 1 or ep % 5 == 0 or ep == epochs:
            print("  epoch %2d/%d  loss=%.3e  (%d 步)  %.1fs" % (ep, epochs, tot / max(1, nb), nb, time.time() - t0), flush=True)

    net.eval()
    with torch.no_grad():
        pred = (Xho.to(dev) + net(Xho.to(dev))).cpu()
        rmse_new = float(torch.sqrt(((pred - Yho) ** 2).mean()))
        rmse_base = float(torch.sqrt(((Xho - Yho) ** 2).mean()))          # 持续性基线
        # H 的物理口径 (dim2 归一化系数 0.1 J)
        h_new = float(torch.sqrt((((pred[:, 2] - Yho[:, 2]) * SCALE[2]) ** 2).mean()))
        h_base = float(torch.sqrt((((Xho[:, 2] - Yho[:, 2]) * SCALE[2]) ** 2).mean()))

    improve = (rmse_base - rmse_new) / rmse_base if rmse_base > 0 else 0.0
    gate = {"rmse_new": round(rmse_new, 6), "rmse_base": round(rmse_base, 6),
            "improve_pct": round(improve * 100, 2), "need_pct": GATE_IMPROVE * 100,
            "h_rmse_J_new": round(h_new, 6), "h_rmse_J_base": round(h_base, 6),
            "passed": bool(improve >= GATE_IMPROVE and h_new <= h_base)}

    ver = "dyn_%s" % time.strftime("%Y%m%d_%H%M%S")
    ckpt = os.path.join(MODEL_DIR, ver + ".pt")
    torch.save({"state_dict": net.state_dict(), "scale": SCALE, "arch": "3-64-64-3"}, ckpt)
    dur = round(time.time() - t0, 1)
    meta = {"ver": ver, "day_id": day_id, "device": dev, "params": nparam, "horizon": horizon,
            "epochs": epochs, "batch": bs, "steps_per_epoch": max(1, math.ceil(len(Xtr) / bs)),
            "train_n": len(Xtr), "holdout_n": len(Xho), "dur_s": dur,
            "loss_hist": hist, "gate": gate, "ckpt": ckpt, "ts": time.time()}
    mp = os.path.join(MODEL_DIR, ver + ".json")
    with open(mp, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)

    meta["ok"] = True
    meta["meta_path"] = mp
    if gate["passed"] and promote_if_pass:
        _promote_dyn(ver, ckpt, gate)
        end_night(True, model_ver=ver, why="夜间训练过闸 → %s" % ver)
        meta["promoted"] = True
    else:
        end_night(False, why="夜间训练未过闸 → 保留旧模型")
        meta["promoted"] = False
    return meta


def _promote_dyn(ver: str, ckpt: str, gate: dict) -> None:
    """只把 dyn 段原子写进 current.json; 先验(统计段)由 consolidate 管, 互不覆盖。"""
    try:
        with open(PRIOR, encoding="utf-8") as f:
            prior = json.load(f)
    except Exception:                                              # noqa: BLE001
        prior = {"ver": "v0", "th_mm": 0.0, "p": 0.0, "H": 0.02, "k_share": 0.0, "n": 0}
    prior["dyn"] = {"ver": ver, "ckpt": ckpt, "gate": gate, "ts": time.time()}
    tmp = PRIOR + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(prior, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, PRIOR)
    st = read_state()
    st["model_ver"] = ver
    write_state(st, "promote: 夜间动力学模型 %s" % ver)
