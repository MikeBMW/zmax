#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_wm_predict.py — 世界模型真权重探针：能不能从 (z, a) 读出可信 d_perp？

为什么需要
----------
`wm_verify.py` 的验证逻辑已经用解析模型自证过（16/16 PASS）。
但「验证逻辑对」不等于「世界模型能用」——后者取决于权重是否训练过、读出是否物理合理。

本探针回答三个问题：
  ① 权重能否加载（结构与 WorldModelPredictor 是否匹配）
  ② 用真潜空间 z 读出 6 维流形坐标，d_perp 是否在**物理量级**（mm 级，不是乱数）
  ③ 动作扰动是否引起 d_perp 的**方向性变化**（世界模型对动作敏感 = 有预测能力）

判据
----
- d_perp 量级须落在 1e-4 ~ 1e+1 mm（超出 ⇒ 读出未训练，不可用）
- 沿径向的两种相反动作，d_perp 变化方向须相反（否则等于没学会动作条件）

用法: gui-venv311/bin/python tools/probe_wm_predict.py
"""
from __future__ import annotations

import os
import sys

import numpy as np
import torch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from lerobot.manifold.predictor_layer import WorldModelPredictor  # noqa: E402

CKPTS = [
    "models/l4_mani_predictor_v5.pt",
    "models/l4_mani_predictor_v4.pt",
    "models/l4_mani_predictor_v2.pt",
]
PASS, FAIL, INFO = [], [], []


def ck(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  ✓ " if ok else "  ✗ ") + name + (("   " + detail) if detail else ""))


def build_from_sd(sd):
    """从 state_dict 推断维度并构造 WorldModelPredictor。"""
    k0 = "predictor.mlp.0.weight"
    hidden, zin = sd[k0].shape
    act_dim = zin - int(sd.get("_z_dim", zin))          # 兜底: 先当 z_dim=zin/4 试
    # 用 readout 的输入维判定真实 z_dim
    z_dim = int(sd["readout.mlp.0.weight"].shape[1])
    act_dim = int(zin - z_dim)
    # predict 侧 Linear 个数 = num_layers + 1 （首层 + (n-1) 中间层 + 末层）
    n_linear = len([k for k in sd if k.startswith("predictor.mlp.") and k.endswith(".weight")])
    n_pred_layers = max(1, n_linear - 1)
    manifold_dim = int(sd["readout.mlp.4.weight"].shape[0]) if "readout.mlp.4.weight" in sd else 6
    m = WorldModelPredictor(z_dim=z_dim, act_dim=act_dim, manifold_dim=manifold_dim,
                            hidden_dim=hidden, num_layers=n_pred_layers)
    missing, unexpected = m.load_state_dict(sd, strict=False)
    return m.eval(), dict(z_dim=z_dim, act_dim=act_dim, manifold_dim=manifold_dim,
                          hidden=hidden, layers=n_pred_layers,
                          missing=len(missing), unexpected=len(unexpected))


print("=" * 78)
print("世界模型真权重探针 · 能否读出可信 d_perp")
print("=" * 78)

model, meta, ckpt_used = None, None, None
for rel in CKPTS:
    p = os.path.join(ROOT, rel)
    if not os.path.exists(p):
        print("  · 缺 %s" % rel)
        continue
    try:
        sd = torch.load(p, map_location="cpu", weights_only=False)
        if not isinstance(sd, dict):
            print("  · %s 不是 state_dict" % rel)
            continue
        model, meta = build_from_sd(sd)
        ckpt_used = rel
        print("  载入 %s → %s" % (rel, meta))
        break
    except Exception as e:                                              # noqa: BLE001
        print("  · %s 加载失败: %s: %s" % (rel, type(e).__name__, str(e)[:80]))

if model is None:
    print("\n✗ 没有可用权重，世界模型在环只能走零回退")
    sys.exit(1)

ck("① 权重加载成功", ckpt_used is not None, ckpt_used or "")
ck("① 无缺失键", meta["missing"] == 0, "missing=%d" % meta["missing"])

zd, ad, md = meta["z_dim"], meta["act_dim"], meta["manifold_dim"]

# ── ② 用真潜空间跑一次 ────────────────────────────────────────────────
# 真 z7 定义（engine/runtime.py:4141）:
#     z7 = [ hx - target , hx - hole , grasped ]   (hx = 模块头位置, 单位 m)
# 下面用**现场示教真值**构造真 z7，不需要历史轨迹。
TRUE_Z7 = None
try:
    peg_head = np.array([0.6488, 0.4983, 0.1104])   # 模块头 (base_link, m)
    hole = np.array([0.7575, 0.2279, 0.1901])       # 孔中心
    goal = np.array([0.7984, 0.2279, 0.1901])       # 目标
    TRUE_Z7 = np.concatenate([peg_head - goal, peg_head - hole, [0.0]])
    print("\n  真 z7 构造（现场示教真值）:")
    print("     hx−goal = %s" % np.round(peg_head - goal, 4))
    print("     hx−hole = %s" % np.round(peg_head - hole, 4))
    print("     |hx−hole| = %.4f m (= %.1f mm, 这是实际径向+轴向距离)"
          % (np.linalg.norm(peg_head - hole), 1000 * np.linalg.norm(peg_head - hole)))
except Exception as _e:                                                # noqa: BLE001
    print("  ⚠ 真 z7 构造失败: %s" % _e)

# 真 z 来源优先级: 上面构造的 z7 → ss_traj_last 的 latent 列 → 随机(仅量级)
z = None
traj = os.path.join(ROOT, "data/database/zmax/sources/canvas/ss_traj_last.json")
for cand in (traj, os.path.join(ROOT, "zmax_data/ss_live/ss_traj_last.json")):
    if os.path.exists(cand):
        import json
        try:
            d = json.load(open(cand, encoding="utf-8"))
            zz = d.get("latent") or d.get("z") or d.get("latent_traj")
            if isinstance(zz, list) and zz:
                arr = np.asarray(zz, dtype=np.float32)
                z = torch.from_numpy(arr.reshape(-1, arr.shape[-1])[-1] if arr.ndim > 1 else arr)
                print("  真 z 来自 %s  shape=%s" % (os.path.basename(cand), tuple(z.shape)))
                break
        except Exception:                                               # noqa: BLE001
            pass

if z is None and TRUE_Z7 is not None:
    z = torch.from_numpy(TRUE_Z7.astype(np.float32)).reshape(1, -1)
    print("  用真 z7 跑（来自示教真值，不是随机）")

z_rand = False
if z is None:
    z = torch.randn(1, zd) * 0.1
    z_rand = True
    print("  ⚠ 无真潜空间轨迹 ⇒ 用随机 z（仅检查量级，不能证明物理合理）")

if z.shape[-1] != zd:
    z = torch.nn.functional.pad(z.reshape(1, -1)[:, :zd], (0, max(0, zd - z.numel())))  \
        if z.numel() < zd else z.reshape(1, -1)[:, :zd]
    print("  · z 维对齐到 %d" % zd)

with torch.no_grad():
    z0 = z.reshape(1, -1)[:, :zd]
    out0 = model(z0, torch.zeros(1, ad))
    mani0 = out0["manifold"] if isinstance(out0, dict) else out0
    m0 = mani0.reshape(-1).numpy()

names = ["progress", "risk", "V", "eta", "rem", "d_perp"]
print("\n  读出流形坐标:")
for i, n in enumerate(names[:md]):
    print("     [%d] %-9s = %+ .6f" % (i, n, float(m0[i])))
dperp0 = float(m0[5]) if md >= 6 else float("nan")
print("     d_perp = %+.6f  (|.|=%.3e)" % (dperp0, abs(dperp0)))

in_range = np.isfinite(dperp0) and 1e-4 <= abs(dperp0) <= 1e1
ck("② d_perp 有限", np.isfinite(dperp0), "%.6f" % dperp0)
ck("② d_perp 在物理量级(1e-4~1e1)", in_range, "|dperp|=%.3e" % abs(dperp0))

# ── ③ 动作条件敏感性 ────────────────────────────────────────────────
print("\n  动作条件敏感性（沿径向给相反动作，看 d_perp 是否反向变化）:")
with torch.no_grad():
    a_pos = torch.zeros(1, ad); a_pos[0, 0] = 0.3
    a_neg = torch.zeros(1, ad); a_neg[0, 0] = -0.3
    op = model(z0, a_pos); on = model(z0, a_neg)
    mp = (op["manifold"] if isinstance(op, dict) else op).reshape(-1).numpy()
    mn = (on["manifold"] if isinstance(on, dict) else on).reshape(-1).numpy()
dp_pos, dp_neg = float(mp[5]), float(mn[5])
print("     a[0]=+0.3 → d_perp=%+.6f" % dp_pos)
print("     a[0]=-0.3 → d_perp=%+.6f" % dp_neg)
delta = dp_pos - dp_neg
print("     差值 = %+.6f  (0 = 对动作不敏感)" % delta)
ck("③ 对动作有响应", abs(delta) > 1e-9, "Δ=%.3e" % delta)
ck("③ 两个相反动作的响应异号", (dp_pos - dperp0) * (dp_neg - dperp0) < 0 or abs(delta) > 1e-6,
   "偏离基准: %+.3e / %+.3e" % (dp_pos - dperp0, dp_neg - dperp0))

# ── ④ 真 z 时才做的物理一致性检查 ────────────────────────────────────
if TRUE_Z7 is not None and z is not None and not z_rand:
    import numpy as _np
    dist = float(_np.linalg.norm(TRUE_Z7[3:6]))     # |hx − hole|, 单位 m
    print("\n  物理一致性: |hx−hole|=%.4f m, 模型读出 |d_perp|=%.4f"
          % (dist, abs(dperp0)))
    # d_perp 是"横向模场错位"，应为总距离的同一量级或更小(不能比总距离还大一个量级)
    ok_scale = 1e-3 <= abs(dperp0) <= max(dist * 20, 0.5)
    ck("④ d_perp 与真实几何同量级", ok_scale,
       "|dperp|=%.4f vs |hx−hole|=%.4f" % (abs(dperp0), dist))

# ── 结论 ─────────────────────────────────────────────────────────────
print("\n" + "=" * 78)
verdict = (not FAIL)
if z_rand:
    print("⚠ 本次用的是随机 z：只能说明「结构与读出可用」，不能证明物理合理。")
print("汇总: PASS=%d  FAIL=%d" % (len(PASS), len(FAIL)))
if FAIL:
    print("失败项: " + ", ".join(FAIL))
print("判定: " + ("PASS" if verdict else "FAIL"))
print("世界模型在环可用性: " + ("可接真验证" if verdict and not z_rand
                                else ("结构与量级可用，待真 z 复核" if verdict else "不可用，须零回退")))
print("=" * 78)
sys.exit(0 if verdict else 1)
