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
        pred = (Xpos_ho.to(dev) + net(Xho.to(dev))).cpu()
        rmse_new = float(torch.sqrt(((pred - Yho) ** 2).mean()))
        rmse_base = float(torch.sqrt(((Xpos_ho - Yho) ** 2).mean()))          # 持续性基线
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


def _train_series(j: list[list[float]], ts: list[float], kind: str, source: str,
                  epochs: int = 400, horizon: int = 1, promote_if_pass: bool = False,
                  hold: float = 0.2, width: int = 16, lag: int = 50,
                  segs: list | None = None) -> dict:
    """通用六轴序列训练: 学 q(t+h) 的残差, 与持续性基线同台比, 过闸才上线。"""
    import torch
    import torch.nn as nn

    st = start_night("夜间训练(%s)" % kind)
    if len(j) < 50:
        end_night(False, why="训练中止: 序列太短")
        return {"ok": False, "why": "序列太短", "n": len(j)}
    if len(ts) > 2 and ts[-1] > ts[0]:
        diffs = sorted(b - a for a, b in zip(ts, ts[1:]) if b > a)
        dt_native = diffs[len(diffs) // 2] if diffs else 0.2
    else:
        dt_native = 0.2
    hz_native = round(1.0 / dt_native, 3) if dt_native > 0 else 5.0

    # 🔴 必须给速度线索: 只喂 q(t) 的网学不出"往哪走", 只能拟合平均漂移 ⇒ 实测输给持续性 60~113%。
    #    特征 = [q(t), q(t) - q(t-lag)] (位置 + 差分速度), 输出仍是 Δ。
    lag = max(0, int(lag))
    if segs:      # 多段拼接时必须按段取样, 否则段与段的"跳变"会被当成动力学学进去
        idx = []
        for a, b in segs:
            idx.extend(range(max(a + lag, lag), min(b - horizon, len(j) - horizon)))
    else:
        idx = list(range(lag, len(j) - horizon))
    feats = []
    for i in idx:
        q = j[i]
        v = [q[k] - j[i - lag][k] for k in range(6)] if lag else [0.0] * 6
        feats.append(q + v)
    X = torch.tensor(feats, dtype=torch.float32)
    Y = torch.tensor([j[i + horizon] for i in idx], dtype=torch.float32)
    Xpos = torch.tensor([j[i] for i in idx], dtype=torch.float32)
    cut = int(len(X) * (1 - hold))
    Xtr, Ytr, Xho, Yho = X[:cut], Y[:cut], X[cut:], Y[cut:]
    Xpos_tr, Xpos_ho = Xpos[:cut], Xpos[cut:]

    dev = _dev()
    torch.manual_seed(0)
    net = nn.Sequential(nn.Linear(12 if lag else 6, width), nn.SiLU(), nn.Linear(width, 6)).to(dev)
    nparam = sum(p.numel() for p in net.parameters())
    opt = torch.optim.Adam(net.parameters(), lr=3e-3, weight_decay=1e-3)
    lossf = nn.MSELoss()
    t0 = time.time()
    print("夜间训练(%s): 设备=%s 参数量=%d 样本 %d/%d 跨度=%d帧(%.2fs) lag=%d 轮数=%d"
          % (kind, dev, nparam, len(Xtr), len(Xho), horizon, horizon / hz_native, lag, epochs), flush=True)
    for ep in range(1, epochs + 1):
        opt.zero_grad()
        out = Xpos_tr.to(dev) + net(Xtr.to(dev))
        loss = lossf(out, Ytr.to(dev))
        loss.backward()
        opt.step()
        if ep == 1 or ep % 100 == 0 or ep == epochs:
            print("  epoch %3d/%d loss=%.3e %.1fs" % (ep, epochs, float(loss), time.time() - t0), flush=True)

    net.eval()
    with torch.no_grad():
        pred = (Xpos_ho.to(dev) + net(Xho.to(dev))).cpu()
        rmse_new = float(torch.sqrt(((pred - Yho) ** 2).mean()))
        rmse_base = float(torch.sqrt(((Xpos_ho - Yho) ** 2).mean()))
    improve = (rmse_base - rmse_new) / rmse_base if rmse_base > 0 else 0.0
    gate = {"rmse_new_deg": round(rmse_new, 4), "rmse_persistence_deg": round(rmse_base, 4),
            "improve_pct": round(improve * 100, 2), "need_pct": GATE_IMPROVE * 100,
            "kind": kind, "passed": bool(improve >= GATE_IMPROVE)}
    ver = "dyn%s_%s" % ("J" if kind == "joints" else "T", time.strftime("%Y%m%d_%H%M%S"))
    ckpt = os.path.join(MODEL_DIR, ver + ".pt")
    torch.save({"state_dict": net.state_dict(), "arch": "%d-%d-6" % (12 if lag else 6, width),
                "horizon": horizon, "lag": lag}, ckpt)
    meta = {"ok": True, "ver": ver, "kind": kind, "device": dev, "params": nparam, "width": width,
            "hz": hz_native, "dt_s": round(dt_native, 4), "epochs": epochs, "horizon": horizon, "lag": lag,
            "train_n": len(Xtr), "holdout_n": len(Xho), "dur_s": round(time.time() - t0, 1),
            "gate": gate, "ckpt": ckpt, "source": source, "ts": time.time()}
    mp = os.path.join(MODEL_DIR, ver + ".json")
    with open(mp, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    meta["meta_path"] = mp
    if gate["passed"] and promote_if_pass:
        _promote_dyn(ver, ckpt, gate)
        end_night(True, model_ver=ver, why="%s 动力学过闸 → %s" % (kind, ver))
        meta["promoted"] = True
    else:
        end_night(False, why="%s 未过闸(%s)" % (kind, round(improve * 100, 1)))
        meta["promoted"] = False
    return meta


def train_joints(traj_path: str, epochs: int = 400, horizon: int = 1,
                 promote_if_pass: bool = False, hold: float = 0.2, width: int = 16) -> dict:
    """示教轨迹口径: 真实的 0.2s/帧 路径时间。"""
    data = json.load(open(traj_path, encoding="utf-8"))
    frames = data["frames"] if isinstance(data, dict) else data
    j = [[float(v) for v in f["j"]] for f in frames]
    ts = [float(f.get("t") or 0.0) for f in frames]
    return _train_series(j, ts, "joints", traj_path, epochs, horizon, promote_if_pass, hold, width)


def train_telemetry(paths: list[str], epochs: int = 400, horizon: int = 20,
                    promote_if_pass: bool = False, hold: float = 0.2, width: int = 16) -> dict:
    """遥测口径(墙钟): 实测关节序列 meas_*.jsonl(弧度→度), 与自主值班同一时钟、同一采样率。"""
    j, ts = [], []
    segs = []
    for p in paths:
        start = len(j)
        with open(p, encoding="utf-8") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except Exception:                                  # noqa: BLE001
                    continue
                q = d.get("q")
                if isinstance(q, list) and len(q) >= 6 and isinstance(d.get("t"), (int, float)):
                    j.append([__import__("math").degrees(float(x)) for x in q[:6]])
                    ts.append(float(d["t"]))
        if len(j) > start:
            segs.append((start, len(j)))
    if not j:
        return {"ok": False, "why": "遥测为空"}
    order = sorted(range(len(ts)), key=lambda i: ts[i])
    j = [j[i] for i in order]
    ts = [ts[i] for i in order]
    # 丢重采样抖动造成的重复时间戳
    jj, tt = [j[0]], [ts[0]]
    for a, b in zip(j[1:], ts[1:]):
        if b - tt[-1] > 1e-4:
            jj.append(a)
            tt.append(b)
    # 段边界在重排/去重后要重新映射: 这里按时间排序后逐段重建
    order = sorted(range(len(tt)), key=lambda i: tt[i])
    segs2 = []
    pos = 0
    for (a, b) in segs:
        n = b - a
        segs2.append((pos, pos + n))
        pos += n
    return _train_series(jj, tt, "telemetry", ",".join(paths), epochs, horizon,
                         promote_if_pass, hold, width, segs=segs2)


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
