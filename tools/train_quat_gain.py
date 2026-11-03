#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""train_quat_gain.py — 550A(4060) 训练: 记忆真值(会漂) + 带噪测量 → **自适应补偿增益**

任务为什么这样定 (不是编标签)
  真机目前没有姿态测量真值 (段表 0 段 quat、数据集无 quat 标签), 所以不做假监督。
  能诚实训练且有意义的是**补偿器的增益策略**:
    · q_true 物理真值 (记忆轴向 + 随机 yaw)
    · q_mem  = q_true ⊗ 系统漂移 (0~5°): 记忆里的标称姿态不可能是精确的
    · q_meas = q_true ⊗ 测量噪声 (0~15°), 10% 样本无测量
    · 融合 q̂ = slerp(q_mem, q_meas, w·g), w = 新鲜度
  基线 = 现有解析解 (固定 α=0.5 ⇒ g≡0.5)。模型学 g(相对旋转, 新鲜度, 是否有效)。
  注意: 若把记忆真值当精确 (漂移=0), 最优解是"忽略测量", 任务退化 —— 第一版 train_quat_head.py
  就是这样, 头 6.50° 劣于基线 1.68°, 报告已作废; 所以这里必须有漂移, 融合才有增益空间。

判据: 每个噪声档都 ≤ 基线, 且总体严格更小 ⇒ ok=true, 才允许进默认档 (老倪门槛)。
产出: zmax_data/quat_head/{quat_head.pt, report.json}
"""
from __future__ import annotations

import json
import os
import time

import numpy as np
import torch
import torch.nn as nn

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "zmax_data", "quat_head")
os.makedirs(OUT, exist_ok=True)
torch.manual_seed(7)
np.random.seed(7)
DEV = "cuda" if torch.cuda.is_available() else "cpu"
AXES = [(0, 0, 1), (0, 0, -1), (1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0)]


def qmul(a, b):
    aw, ax, ay, az = a[..., 0], a[..., 1], a[..., 2], a[..., 3]
    bw, bx, by, bz = b[..., 0], b[..., 1], b[..., 2], b[..., 3]
    return np.stack([aw * bw - ax * bx - ay * by - az * bz,
                     aw * bx + ax * bw + ay * bz - az * by,
                     aw * by - ax * bz + ay * bw + az * bx,
                     aw * bz + ax * by - ay * bx + az * bw], axis=-1)


def qexp(rv):
    rv = np.asarray(rv, float)
    ang = np.linalg.norm(rv, axis=-1, keepdims=True)
    n = np.maximum(ang, 1e-12)
    return np.concatenate([np.cos(ang / 2), np.sin(ang / 2) * rv / n], axis=-1)


def rel_rotvec(qa, qb):
    qa = np.atleast_2d(np.asarray(qa, float))
    qb = np.atleast_2d(np.asarray(qb, float))
    inv = np.concatenate([qa[:, :1], -qa[:, 1:]], axis=1)
    q = qmul(inv, qb)
    q[q[:, 0] < 0] *= -1
    v = q[:, 1:]
    n = np.linalg.norm(v, axis=1, keepdims=True)
    ang = 2 * np.arctan2(n, np.clip(q[:, :1], -1, 1))
    return (v / np.maximum(n, 1e-12)) * ang


def q_from_axis(axis, yaw):
    a = np.asarray(axis, float)
    a = a / np.linalg.norm(a)
    z = np.array([0.0, 0, 1.0])
    v = np.cross(z, a)
    c = float(np.dot(z, a))
    s = np.linalg.norm(v)
    if s < 1e-9:
        q0 = np.array([1.0, 0, 0, 0]) if c > 0 else np.array([0.0, 1, 0, 0])
    else:
        ang = np.arctan2(s, c)
        q0 = np.concatenate([[np.cos(ang / 2)], np.sin(ang / 2) * (v / s)])
    return qmul(q0, np.concatenate([[np.cos(yaw / 2)], np.sin(yaw / 2) * a]))


def ang_deg(q1, q2):
    d = np.abs(np.sum(np.asarray(q1) * np.asarray(q2), axis=-1))
    return np.degrees(2 * np.arccos(np.clip(d, -1, 1)))


def make(n, rng):
    mem, meas, feat, true, meta = [], [], [], [], []
    for _ in range(n):
        q_true = q_from_axis(AXES[rng.integers(len(AXES))], rng.uniform(0, 2 * np.pi))
        sigma = rng.uniform(0, 15.0)
        drift = rng.uniform(0, 5.0)
        da = rng.normal(size=3); da /= np.linalg.norm(da)
        q_mem = qmul(q_true, qexp(da * np.radians(drift)))
        q_mem /= np.linalg.norm(q_mem)
        if q_mem[0] < 0:
            q_mem = -q_mem
        if rng.random() < 0.10:
            q_meas, valid = np.zeros(4), 0.0
        else:
            na = rng.normal(size=3); na /= np.linalg.norm(na)
            q_meas = qmul(q_true, qexp(na * np.radians(sigma)))
            q_meas /= np.linalg.norm(q_meas)
            if q_meas[0] < 0:
                q_meas = -q_meas
            valid = 1.0
        w = float(rng.uniform(0, 1))
        rel = rel_rotvec(q_mem, q_meas)[0] if valid > 0 else np.zeros(3)
        mem.append(q_mem); meas.append(q_meas); true.append(q_true)
        feat.append(np.concatenate([rel, [w, valid, float(np.linalg.norm(rel))]]))
        meta.append({"sigma": sigma, "drift": drift, "w": w, "valid": valid})
    return {"mem": np.asarray(mem, np.float32), "meas": np.asarray(meas, np.float32),
            "feat": np.asarray(feat, np.float32), "true": np.asarray(true, np.float32), "meta": meta}


class Gain(nn.Module):
    """自适应补偿增益 g∈(0,1): q̂ = slerp(q_mem, q_meas, w·g)"""

    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(6, 192), nn.SiLU(), nn.Linear(192, 192), nn.SiLU(),
                                 nn.Linear(192, 96), nn.SiLU(), nn.Linear(96, 1))
        # 零初始化输出 ⇒ 起点 g=0.5, 正好等于解析基线 (保证"先不回退, 只在有增益处改进")
        nn.init.zeros_(self.net[-1].weight)
        nn.init.zeros_(self.net[-1].bias)

    def forward(self, x):
        return torch.sigmoid(self.net(x)).squeeze(1)


def slerp_t(mem, meas, t):
    d = (mem * meas).sum(1)
    sign = torch.where(d < 0, -torch.ones_like(d), torch.ones_like(d))
    meas = meas * sign[:, None]
    d = (d * sign).clamp(-1, 1)
    th = torch.acos(d)
    s = torch.sin(th).clamp_min(1e-7)
    q = (torch.sin((1 - t) * th) / s)[:, None] * mem + (torch.sin(t * th) / s)[:, None] * meas
    small = d > 0.9995
    if bool(small.any()):
        q[small] = (1 - t[small])[:, None] * mem[small] + t[small][:, None] * meas[small]
    return q / q.norm(dim=1, keepdim=True).clamp_min(1e-9)


def slerp_np(mem, meas, t):
    sign = np.where((mem * meas).sum(1) < 0, -1.0, 1.0)[:, None]
    meas = meas * sign
    d = np.clip((mem * meas).sum(1), -1, 1)
    th = np.arccos(d)
    s = np.maximum(np.sin(th), 1e-9)
    q = (np.sin((1 - t) * th) / s)[:, None] * mem + (np.sin(t * th) / s)[:, None] * meas
    small = d > 0.9995
    if small.any():
        q[small] = (1 - t[small, None]) * mem[small] + t[small, None] * meas[small]
    return q / np.linalg.norm(q, axis=1, keepdims=True)


def main(epochs=22, n_train=600_000, bs=16384):
    t0 = time.time()
    rng = np.random.default_rng(7)
    tr, te = make(n_train, rng), make(40_000, rng)
    dev_t = lambda a: torch.tensor(a, device=DEV)                               # noqa: E731
    m_mem, m_meas, m_feat, m_true = (dev_t(tr["mem"]), dev_t(tr["meas"]),
                                     dev_t(tr["feat"]), dev_t(tr["true"]))
    model = Gain().to(DEV)
    opt = torch.optim.AdamW(model.parameters(), lr=2e-3, weight_decay=1e-4)
    sch = torch.optim.lr_scheduler.CosineAnnealingLR(opt, epochs)
    npar = sum(p.numel() for p in model.parameters())
    print("设备 %s | 训练 %d | 参数 %d | 特征=相对旋转(3)+新鲜度+有效+模长" % (DEV, n_train, npar))
    for ep in range(1, epochs + 1):
        model.train()
        perm = torch.randperm(n_train, device=DEV)
        tot = 0.0
        for i in range(0, n_train, bs):
            idx = perm[i:i + bs]
            g = model(m_feat[idx])
            t = (m_feat[idx][:, 3] * g).clamp(0, 1)
            q = slerp_t(m_mem[idx], m_meas[idx], t)
            inv = m_feat[idx][:, 4] > 0.5
            if not bool(inv.all()):
                q = torch.where(inv[:, None], q, m_mem[idx])
            d = (q * m_true[idx]).sum(1).abs().clamp(max=1.0)
            loss = (1 - d).mean()
            opt.zero_grad(set_to_none=True)
            loss.backward()
            opt.step()
            tot += float(loss.detach())
        sch.step()
        print("epoch %2d/%d  loss=%.6f  %.0fs" % (ep, epochs, tot / (n_train / bs), time.time() - t0))
    model.eval()
    with torch.no_grad():
        g = model(dev_t(te["feat"])).cpu().numpy()
    q_head = slerp_np(te["mem"], te["meas"], te["feat"][:, 3] * g)
    nod = te["feat"][:, 4] < 0.5
    q_head[nod] = te["mem"][nod]
    q_base = slerp_np(te["mem"], te["meas"], te["feat"][:, 3] * 0.5)
    q_base[nod] = te["mem"][nod]
    eh, eb = ang_deg(q_head, te["true"]), ang_deg(q_base, te["true"])
    rows = []
    for lo, hi in [(0, 3), (3, 6), (6, 10), (10, 15)]:
        m = np.array([(lo <= r["sigma"] < hi) for r in te["meta"]])
        if m.sum():
            rows.append({"sigma_deg": "%d-%d" % (lo, hi), "n": int(m.sum()),
                         "head_deg": round(float(eh[m].mean()), 4),
                         "baseline_deg": round(float(eb[m].mean()), 4),
                         "delta_deg": round(float(eh[m].mean() - eb[m].mean()), 4)})
    rep = {"task": "记忆真值(含0~5°漂移)+带噪测量(0~15°)+新鲜度 → 自适应补偿增益",
           "device": DEV, "n_train": n_train, "epochs": epochs, "params": npar,
           "train_seconds": round(time.time() - t0, 1),
           "overall": {"head_deg": round(float(eh.mean()), 4), "baseline_deg": round(float(eb.mean()), 4),
                       "delta_deg": round(float(eh.mean() - eb.mean()), 4),
                       "p95_head": round(float(np.percentile(eh, 95)), 4),
                       "p95_baseline": round(float(np.percentile(eb, 95)), 4)},
           "by_sigma": rows, "gain_mean": round(float(g.mean()), 4),
           "no_measurement": {"n": int(nod.sum()),
                              "head_deg": round(float(eh[nod].mean()), 4) if nod.any() else None,
                              "baseline_deg": round(float(eb[nod].mean()), 4) if nod.any() else None},
           "note": "标签=模拟漂移+噪声下的已知真值; 真机尚无姿态测量真值, 上线前须真机标定核对"}
    rep["ok"] = bool(rep["overall"]["delta_deg"] < 0 and all(r["delta_deg"] <= 0 for r in rows))
    torch.save({"state": model.state_dict(), "arch": "gain192-192-96", "in_dim": 6},
               os.path.join(OUT, "quat_head.pt"))
    with open(os.path.join(OUT, "report.json"), "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1)
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    return rep


if __name__ == "__main__":
    main()
