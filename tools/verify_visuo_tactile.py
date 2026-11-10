#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_visuo_tactile.py — 视触觉融合动作修正 六项实测

对应专利 ZMP-2026-013(v2) 的核心主张，逐条用真代码算，不 mock:
  A 触觉梯度方向: 力 → 反方向梯度 (∇V_tac ∝ −F_radial)，轴向必须为 0
  B 融合权重切换: 接触越深越信触觉 (w_tac 随 contact 单调升)
  C 盲插死区: 视觉误报 0.2mm / 真实 0.4mm 时，纯视觉修不到真值，触觉能
  D 力阈值保护: F<F_max 不介入 / F>F_max 置信度骤降 / F>1.5F_max 停机
  E 盲插收敛: 0.4mm 初始偏差在触觉反馈下几拍收敛到 <0.05mm
  F 降级不造数: 无视觉无触觉/无接触无残差 ⇒ injected=false

用法: gui-venv311/bin/python tools/verify_visuo_tactile.py
"""
from __future__ import annotations

import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src", "lerobot", "policies", "manifold"))

from geodesic_inject import (  # noqa: E402
    DEFAULTS, anisotropic_metric, correct, force_guard, fuse_gradient,
    split_components, tactile_to_gradient,
)

AXIS = [0.0, 0.0, 1.0]           # Z 为插入轴，径向 = XY
CFG = dict(DEFAULTS)
PASS, FAIL = [], []


def ck(name: str, ok: bool, detail: str = ""):
    (PASS if ok else FAIL).append(name)
    print(("  ✓ " if ok else "  ✗ ") + name + (("   " + detail) if detail else ""))


# ── A 触觉梯度方向 ────────────────────────────────────────────────────
print("[A] 触觉力 → 势能梯度方向")
F = [5.0, 0.0, 0.0]              # 孔壁把模块往 +X 推 ⇒ 模块偏在 -X 侧, 需往 +X 修
g, ti = tactile_to_gradient(F=F, axis=AXIS, cfg=CFG)
print("     src=%s  ∇V_tac=%s  radial=%.3f axial=%.3f" % (
    ti["src"], np.round(g, 4).tolist(), ti["radial_norm"], ti["axial_norm"]))
ck("A1 力源被正确识别", ti["src"] == "force", "src=" + str(ti["src"]))
ck("A2 梯度与力同向(力=排斥=势能上升)", float(g[0]) > 0 and abs(float(g[0]) - 5.0) < 1e-6,
   "g_x=%+.4f (应=+5)" % float(g[0]))
ck("A3 轴向分量被剔除", ti["axial_norm"] < 1e-9, "axial=%.2e" % ti["axial_norm"])
ck("A4 径向幅度 = |F|", abs(ti["radial_norm"] - 5.0) < 1e-6, "%.4f" % ti["radial_norm"])

# 轴向力不应产生修正（轴向是插深，不该靠力纠偏）
g_ax, ti_ax = tactile_to_gradient(F=[0.0, 0.0, 8.0], axis=AXIS, cfg=CFG)
ck("A5 纯轴向力不产生径向修正", (g_ax is None) or ti_ax["radial_norm"] < 1e-9,
   "radial=%.2e" % (ti_ax["radial_norm"] if g_ax is not None else 0.0))

# 有真力时优先于代理
g_pr, ti_pr = tactile_to_gradient(F=[3.0, 0.0, 0.0], contact=0.9,
                                  dir_xy=[1.0, 0.0], axis=AXIS, cfg=CFG)
ck("A6 真力优先于代理", ti_pr["src"] == "force", "src=" + str(ti_pr["src"]))

# ── B 融合权重 ────────────────────────────────────────────────────────
print("\n[B] 视觉/触觉权重随接触切换")
gv = np.array([-0.08, 0.0, 0.0])
gt = np.array([-5.0, 0.0, 0.0])
ws = []
for ct in (0.0, 0.15, 0.35, 0.70, 1.00):
    _, fi = fuse_gradient(gv, gt, contact=ct, cfg=CFG)
    ws.append(float(fi.get("w_tac") or 0.0))
    print("     contact=%.2f → w_tac=%.3f w_vis=%.3f mode=%s" % (
        ct, fi.get("w_tac") or 0, fi.get("w_vis") or 0, fi.get("mode")))
ck("B1 未接触时纯视觉", ws[0] == 0.0, "w_tac=%.3f" % ws[0])
ck("B2 接触越深越信触觉(单调)", all(ws[i] <= ws[i + 1] + 1e-9 for i in range(len(ws) - 1)),
   "→".join("%.2f" % w for w in ws))
ck("B3 深接触时触觉主导", ws[-1] >= 0.5, "w_tac=%.3f" % ws[-1])
ck("B4 触觉权重有上限(留视觉兜底)", ws[-1] <= DEFAULTS["tac_w_max"] + 1e-9,
   "w_tac=%.3f ≤ %.2f" % (ws[-1], DEFAULTS["tac_w_max"]))

# ── C 盲插死区：视觉误报 vs 触觉真值 ──────────────────────────────────
print("\n[C] 盲插区: 视觉误报 0.2mm / 真实 0.4mm")
delta_true = -0.40          # 模块实偏 -X 0.4mm
delta_vis = -0.20           # 视觉只看到 0.2mm
W = np.diag([0.4, 1.0, 1.0])
grad_vis = W @ np.array([delta_vis, 0.0, 0.0])      # ∇V_vis = Wδ
F_true = [-5.0, 0.0, 0.0]    # 模块偏 -X ⇒ 孔壁把它继续往 -X 排斥(远离孔心)

u_vis, i_vis = correct([0.5, 0.0, 0.0], grad_vis, AXIS, eta=1.0, V_p=0.02,
                       cfg=dict(CFG, tac_enable=False))
u_mix, i_mix = correct([0.5, 0.0, 0.0], grad_vis, AXIS, eta=1.0, V_p=0.02,
                       cfg=CFG, force=F_true, contact=0.95)
print("     纯视觉: src=%s Δ径向=%.4f mm  w_tac=%s" % (
    i_vis.get("grad_src"), i_vis["radial"], i_vis.get("w_tac")))
print("     视觉+触觉: src=%s Δ径向=%.4f mm  w_tac=%s  力=%.1fN 盾=%s" % (
    i_mix.get("grad_src"), i_mix["radial"], i_mix.get("w_tac"),
    i_mix.get("force_N") or 0, (i_mix.get("guard") or {}).get("why")))
ck("C1 视觉路修偏不足(受 0.2mm 假信息限制)", i_vis["radial"] < 0.30,
   "Δ=%.4fmm" % i_vis["radial"])
ck("C2 触觉路修正方向朝 +X(力的反方向)", i_mix["delta"][0] > 0,
   "Δx=%+.4f" % i_mix["delta"][0])
ck("C3 触觉路修幅显著大于纯视觉", i_mix["radial"] > i_vis["radial"] * 1.2,
   "%.4f vs %.4f (%.1f×)" % (i_mix["radial"], i_vis["radial"],
                             i_mix["radial"] / max(i_vis["radial"], 1e-9)))
ck("C4 融合后标注来源=force", i_mix.get("grad_src") == "force",
   "src=" + str(i_mix.get("grad_src")))
ck("C5 触觉主导时绕过视觉代价门控", i_mix.get("gate_mode") == "tactile_bypass_Vp",
   "gate_mode=" + str(i_mix.get("gate_mode")))

# ── D 力阈值保护 ──────────────────────────────────────────────────────
print("\n[D] 力阈值保护 (F_max=%.0fN)" % DEFAULTS["force_max"])
for Fn in (10.0, 20.0, 44.0, 52.0, 70.0):
    gd = force_guard(Fn, CFG)
    tag = "停机" if gd["abort"] else ("×%.3f" % gd["scale"])
    print("     F=%5.1fN → scale=%.3f abort=%s  %s" % (Fn, gd["scale"], gd["abort"], tag))
ck("D1 正常力不介入", force_guard(20.0, CFG)["scale"] == 1.0 and not force_guard(20.0, CFG)["abort"])
ck("D2 略超上限置信度骤降", 0 < force_guard(44.0, CFG)["scale"] < 0.7,
   "scale=%.3f (F/Fmax=1.1 ⇒ 0.55)" % force_guard(44.0, CFG)["scale"])
ck("D3 超 1.5 倍直接停机", force_guard(70.0, CFG)["abort"] is True)
_ab, _ai = correct([0.5, 0.0, 0.0], grad_vis, AXIS, eta=1.0, V_p=0.02,
                   cfg=CFG, force=[70.0, 0.0, 0.0], contact=0.95)
ck("D4 停机时输出零动作(不是原样推进)", _ai.get("aborted") is True
   and _ab[0] == 0.0 and _ab[1] == 0.0 and _ab[2] == 0.0,
   "u*=" + str(_ab[:3]) + " reason=" + str(_ai.get("reason"))[:30])

# ── E 盲插收敛 ────────────────────────────────────────────────────────
print("\n[E] 盲插收敛: 初始偏 0.40mm, 触觉每拍反馈 (K=6N/mm)")
d = -0.40
steps, hist = 0, []
for k in range(12):
    F_k = [d * 6.0, 0.0, 0.0]                 # 越偏力越大（刚度 6N/mm）
    u, inf = correct([0.5, 0.0, 0.0], None, AXIS, eta=1.0, V_p=0.0,
                     cfg=CFG, force=F_k, contact=0.95)
    d += float(inf["delta"][0])                # 只累加修正量(不是绝对动作)
    hist.append(round(abs(d), 5))
    steps = k + 1
    if abs(d) < 0.05:
        break
print("     偏差序列: " + " → ".join("%.4f" % h for h in hist))
ck("E1 盲插收敛到 <0.05mm", abs(d) < 0.05, "final=%.4fmm, %d 拍" % (abs(d), steps))
ck("E2 收敛过程单调(无振荡)", all(hist[i] >= hist[i + 1] - 1e-9 for i in range(len(hist) - 1)),
   "无来回翻转")
ck("E3 拍数可控(≤8)", steps <= 8, "%d 拍" % steps)

# ── F 降级不造数 ──────────────────────────────────────────────────────
print("\n[F] 降级 (不造数)")
u0, i0 = correct([0.5, 0.0, 0.0], None, AXIS, eta=1.0, cfg=CFG)
ck("F1 两路全缺 ⇒ 不注入", i0["injected"] is False and u0 == [0.5, 0.0, 0.0],
   "reason=" + str(i0.get("reason")))
u1, i1 = correct([0.5, 0.0, 0.0], None, AXIS, eta=1.0, V_p=0.02,
                 cfg=CFG, residual=[0.0, 0.0, 0.0])
ck("F2 无视觉+零残差 ⇒ 不注入", i1["injected"] is False, "reason=" + str(i1.get("reason")))
g_none, ti_none = tactile_to_gradient(None, None, None, None, AXIS, CFG)
ck("F3 无任何触觉信息 ⇒ 无梯度且标 why", g_none is None and ti_none["why"],
   ti_none["why"])

# ── 各向异性仍成立（触觉路也必须过 M⁻¹）──────────────────────────────
print("\n[G] 各向异性: 触觉梯度经 M⁻¹ 后径向放大 / 轴向压制")
M = anisotropic_metric(AXIS, DEFAULTS["sigma_t_mm"], DEFAULTS["sigma_n_mm"])
ratio = (DEFAULTS["sigma_n_mm"] / DEFAULTS["sigma_t_mm"]) ** 2
g_r = np.array([1.0, 0.0, 0.0])
g_a = np.array([0.0, 0.0, 1.0])
amp_r = float(np.linalg.norm(np.linalg.solve(M, g_r)))
amp_a = float(np.linalg.norm(np.linalg.solve(M, g_a)))
print("     径向 |M⁻¹g|=%.4f  轴向 |M⁻¹g|=%.4f  实测比=%.1f  理论(σn/σt)²=%.0f" % (
    amp_r, amp_a, amp_r / amp_a, ratio))
ck("G1 径向/轴向放大比 = (σn/σt)²", abs(amp_r / amp_a - ratio) / ratio < 1e-6,
   "%.1f vs %.0f" % (amp_r / amp_a, ratio))

# ── 汇总 ──────────────────────────────────────────────────────────────
print("\n" + "=" * 62)
print("汇总: PASS=%d  FAIL=%d" % (len(PASS), len(FAIL)))
if FAIL:
    print("失败项: " + ", ".join(FAIL))
print("判定: " + ("PASS" if not FAIL else "FAIL"))
print("=" * 62)
sys.exit(0 if not FAIL else 1)
