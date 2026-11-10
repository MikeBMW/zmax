#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_wm_inloop_e2e.py — 世界模型在环 · 真权重端到端

与 `verify_wm_inloop.py` 的区别
------------------------------
那个用**解析世界模型**证明"验证逻辑对"；这个用**真权重 + 真 z7** 证明
"世界模型真的能对候选动作给出方向性判断"。

链路（与引擎 runtime.py 同构）
------------------------------
    z7 = [hx−target, hx−hole, grasped]      (m)
    a4 = 候选动作 (现行动作 + Δξ/1000)
    WorldModelPredictor → z' → ManifoldReadout → d_perp
    gain = (|d_perp_cur| − |d_perp_cand|)/|d_perp_cur|
    gain>0 采纳 / gain<-15% 拒绝 / 其余缩权

判据
----
① 权重加载成功（z_dim=7, act_dim=4, manifold=6）
② 真 z7 下 d_perp 与真实几何同量级
③ **朝孔心的候选**预测 d_perp 下降（gain>0）
④ **背离孔心的候选**预测 d_perp 不降（gain≤朝孔心那个）
⑤ 验证后的修正量与解析候选方向一致（没有被验证层反向带偏）

用法: gui-venv311/bin/python tools/probe_wm_inloop_e2e.py
"""
from __future__ import annotations

import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "src", "lerobot", "policies", "manifold"))

from lerobot.policies.manifold import wm_adapter as A          # noqa: E402
from lerobot.policies.manifold.geodesic_inject import correct  # noqa: E402
from wm_verify import verify                                    # noqa: E402

PASS, FAIL = [], []


def ck(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  ✓ " if ok else "  ✗ ") + name + (("   " + detail) if detail else ""))


print("=" * 80)
print("世界模型在环 · 真权重端到端 (ZMP-2026-019)")
print("=" * 80)

# ── ① 加载 ───────────────────────────────────────────────────────────
ok, why = A.available()
print("\n[①] 加载世界模型: %s" % why)
ck("① 权重可用", ok, why)
if not ok:
    print("✗ 无法继续，世界模型在环只能零回退")
    sys.exit(1)
box = A.load()
print("     meta = %s" % box.get("meta"))

# ── ② 真 z7（现场示教真值）────────────────────────────────────────────
peg_head = np.array([0.6488, 0.4983, 0.1104])   # 模块头 (base_link, m)
hole = np.array([0.7575, 0.2279, 0.1901])
goal = np.array([0.7984, 0.2279, 0.1901])
z7 = np.concatenate([peg_head - goal, peg_head - hole, [0.0]]).astype(np.float32)
dist = float(np.linalg.norm(peg_head - hole))
print("\n[②] 真 z7 = [hx−goal, hx−hole, grasped]")
print("     |hx−hole| = %.4f m (%.1f mm)" % (dist, 1000 * dist))

pred = A.make_predictor(z7)
ck("② 预测器构造成功", pred is not None)
dp0 = A.predict_dperp(z7, np.zeros(3), model_box=box)
print("     当前 d_perp(零修正) = %+.6f" % (dp0 or 0))
ck("② d_perp 有限且非零", dp0 is not None and abs(dp0) > 1e-6, "%.6f" % (dp0 or 0))

# ── ③④ 朝孔心 vs 背离孔心 ────────────────────────────────────────────
# 几何: 模块偏 −X 与 +Y（hx−hole 的 x、y 分量为负/正），朝孔心需 +X、−Y
to_hole = -np.array([peg_head[0] - hole[0], peg_head[1] - hole[1], 0.0])
to_hole = to_hole / max(np.linalg.norm(to_hole), 1e-9)
step_mm = 5.0
d_toward = (to_hole * step_mm).astype(np.float64)
d_away = (-to_hole * step_mm).astype(np.float64)

dp_t = A.predict_dperp(z7, d_toward, model_box=box)
dp_a = A.predict_dperp(z7, d_away, model_box=box)
gain_t = (abs(dp0) - abs(dp_t)) / max(abs(dp0), 1e-12) if dp_t is not None else None
gain_a = (abs(dp0) - abs(dp_a)) / max(abs(dp0), 1e-12) if dp_a is not None else None
print("\n[③④] 动作方向敏感性（步长 %.1f mm）" % step_mm)
print("     朝孔心 Δ=%s mm → d_perp=%+.6f  gain=%+.3f"
      % (np.round(d_toward, 2), dp_t or 0, gain_t or 0))
print("     背离孔心 Δ=%s mm → d_perp=%+.6f  gain=%+.3f"
      % (np.round(d_away, 2), dp_a or 0, gain_a or 0))
ck("③ 朝孔心预测更优(gain 更高)", gain_t is not None and gain_a is not None and gain_t > gain_a,
   "%.3f vs %.3f" % (gain_t or 0, gain_a or 0))

# ── ⑤ 完整链路: 解析候选 → 世界模型验证 ──────────────────────────────
print("\n[⑤] 解析候选 → 世界模型验证 → 最终修正量")
# 用近孔场景: 径向偏差 0.4mm（模仿 verify_l4_injection 的受控扰动）
d_perp_cur = 0.40
# 解析注入给出候选（触觉路径，K=6N/mm，轴 Z 使力沿 X 成为纯径向）
u, inj = correct([0.5, 0.0, 0.0], None, [0.0, 0.0, 1.0], eta=1.0, V_p=0.0,
                 force=[-d_perp_cur * 6.0, 0.0, 0.0], contact=0.95)
cand = np.asarray(inj.get("delta") or [0, 0, 0], dtype=float)
print("     解析候选 Δξ = %s mm (径向 %.4f)  injected=%s"
      % (np.round(cand, 4), inj.get("radial", 0), inj.get("injected")))

# 用真世界模型验证「解析候选」与「反向候选」
fin, info = verify(cand, pred, abs(dp0))
rev, info_r = verify(-cand, pred, abs(dp0))
print("     验证(原向): verified=%s scale=%.2f gain=%s  → Δ=%s"
      % (info["verified"], info["chosen_scale"], info["gain"], np.round(fin, 4)))
print("     验证(反向): verified=%s scale=%.2f gain=%s  → Δ=%s"
      % (info_r["verified"], info_r["chosen_scale"], info_r["gain"], np.round(rev, 4)))
ck("⑤ 原向优于反向", (info["gain"] or -9) >= (info_r["gain"] or -9),
   "%s vs %s" % (info["gain"], info_r["gain"]))
ck("⑤ 验证层未把方向带反", float(np.dot(fin, cand)) >= -1e-12 if np.linalg.norm(fin) > 0 else True,
   "dot=%.3e" % float(np.dot(fin, cand)))
# 原向 gain 很小时, 验证层应当缩权而非全额采纳 —— 这是"没把握就不放大"的正确行为
ck("⑤ 增益不足时缩权(不盲目全额采纳)",
   (info["chosen_scale"] < 1.0) if (info["gain"] is not None and info["gain"] < 0.02) else True,
   "gain=%s scale=%.2f" % (info["gain"], info["chosen_scale"]))

# ── ⑥ 步长灵敏度扫描（决定它适合粗筛还是精调）──────────────────────
print("\n[⑥] 步长灵敏度扫描（世界模型对多大的修正量才有可分辨响应）")
print("     步长(mm)  朝孔心 d_perp     gain      背离 d_perp     gain")
rows = []
for step in (5.0, 20.0, 50.0, 100.0, 200.0):
    dt = (to_hole * step).astype(np.float64)
    da = (-to_hole * step).astype(np.float64)
    pt = A.predict_dperp(z7, dt, model_box=box)
    pa = A.predict_dperp(z7, da, model_box=box)
    gt = (abs(dp0) - abs(pt)) / max(abs(dp0), 1e-12) if pt is not None else None
    ga = (abs(dp0) - abs(pa)) / max(abs(dp0), 1e-12) if pa is not None else None
    rows.append((step, pt, gt, pa, ga))
    print("     %7.0f   %+ .6f   %+ .4f    %+ .6f   %+ .4f"
          % (step, pt or 0, gt or 0, pa or 0, ga or 0))
best = max(rows, key=lambda r: abs((r[2] or 0) - (r[4] or 0)))
sep = abs((best[2] or 0) - (best[4] or 0))
print("     → 方向可分辨性最强在 %.0f mm (|Δgain|=%.4f)" % (best[0], sep))
ck("⑥ 存在可分辩的步长档(|Δgain|>0.01)", sep > 0.01, "最佳 %.0fmm, Δgain=%.4f" % (best[0], sep))

# ── 汇总 ─────────────────────────────────────────────────────────────
print("\n" + "=" * 80)
print("汇总: PASS=%d  FAIL=%d" % (len(PASS), len(FAIL)))
if FAIL:
    print("失败项: " + ", ".join(FAIL))
print("判定: " + ("PASS" if not FAIL else "FAIL"))
print("=" * 80)
sys.exit(0 if not FAIL else 1)
