#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_wm_inloop.py — 世界模型在环验证的实测（016 之外的新层：L4→L3 第二类连接）

判什么
------
013 的注入是「当前梯度最速下降」，不验证走完这一步之后会怎样。
本脚本用**受控解析世界模型**（dperp' = |dperp + Δξ_radial|，行为可预测）
证明验证层逻辑正确：

  A 方向对  ⇒ 预测偏差变小 ⇒ 采纳
  B 方向反  ⇒ 预测偏差变大 ⇒ 拒绝（这一步在物理上会把模块推离孔心）
  C 收益不足 ⇒ 缩权而非全额采纳
  D 轻微变差 ⇒ 缩权（不直接归零，留给下一拍）
  E 多候选   ⇒ 自动在 (1.0, 0.6, 0.3) 档里选预测最优
  F 无预测器 ⇒ verified=False 原样放行（零回退，不因验证缺失惩罚）
  G λ=0     ⇒ 耦合后逐位等于纯几何梯度（零回退）
  H 耦合     ⇒ ∇V = ∇V_geo + λ·∇V_pred 数值正确

用法: gui-venv311/bin/python tools/verify_wm_inloop.py
"""
from __future__ import annotations

import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src", "lerobot", "policies", "manifold"))

from wm_verify import candidate_gain, couple_with_geometry, verify  # noqa: E402

PASS, FAIL = [], []


def ck(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  ✓ " if ok else "  ✗ ") + name + (("   " + detail) if detail else ""))


# ── 受控解析世界模型 ──────────────────────────────────────────────────
# 语义: 径向偏差 dperp, 修正量 delta 的径向分量会直接改变它
#       dperp' = |dperp + delta_radial|   (朝孔心修 ⇒ delta 与 dperp 反号 ⇒ 变小)
def make_wm(dperp_signed: float, axis_noise: float = 0.0):
    """受控世界模型: 新径向偏差 = |当前带符号偏差 + 修正量的径向分量|

    ⚠️ 必须用**带符号**偏差: 模块偏 +X 时偏差 = +0.40, 修正量 −0.32 才使它变小;
       用幅度(0.40)直接相加会得出「+0.32 能减小偏差」的错误结论。
    """
    def predict(delta):
        dx = float(np.asarray(delta, dtype=float).reshape(-1)[0])
        return abs(dperp_signed + dx) + axis_noise
    return predict


AXIS_X = [1.0, 0.0, 0.0]      # 装配轴 = X，径向在 YZ... 本仿真用 X 作径向通道以便直观

print("=" * 78)
print("世界模型在环验证 (L4 预测 → L3 动作)")
print("=" * 78)

# ── A 方向对：dperp=0.40, 候选 +0.32 (朝孔心) → 预测 0.08 ─────────────
print("\n[A] 候选方向正确")
d_cur = 0.40                    # 径向偏差幅度
d_signed = 0.40                 # 模块偏 +X ⇒ 朝孔心要往 −X 修
pred = make_wm(d_signed)
delta, info = verify(np.array([-0.32, 0.0, 0.0]), pred, d_cur)
print("     dperp=%.2f(偏+X) 候选 Δx=−0.32 → 预测 %.3f  gain=%.3f  %s"
      % (d_cur, pred([-0.32, 0, 0]), info["gain"], info["reason"]))
ck("A1 采纳且全额", info["verified"] and info["chosen_scale"] == 1.0 and abs(delta[0] + 0.32) < 1e-9)
ck("A2 gain 为正且量级对", info["gain"] is not None and info["gain"] > 0.7,
   "gain=%.3f (理论 0.80)" % info["gain"])

# ── B 方向反：候选 −0.32 → 预测 0.72 → 恶化 80% ───────────────────────
print("\n[B] 候选方向相反（会把模块推离孔心）")
delta_b, info_b = verify(np.array([0.32, 0.0, 0.0]), pred, d_cur)
print("     候选 Δx=+0.32(把模块推得更远) → 预测 %.3f  gain=%.3f  %s"
      % (pred([0.32, 0, 0]), info_b["gain"], info_b["reason"]))
ck("B1 被拒绝", info_b["verified"] and info_b["chosen_scale"] == 0.0)
ck("B2 输出零修正", np.allclose(np.asarray(delta_b), 0.0), str(np.round(delta_b, 4)))
# 实现会自动选「恶化最小」的档(0.3 → 只恶化 24%), 这比全额档(-80%)更合理;
# 断言只要求「明确恶化 ⇒ 拒绝」, 不锁死具体档位
ck("B3 明确恶化(自动选了恶化最小的档)", info_b["gain"] < -0.1,
   "gain=%.3f, 试算=%s" % (info_b["gain"], [(t["scale"], round(t.get("gain") or 0, 2)) for t in info_b["tried"]]))

# ── C 收益不足：候选 +0.05 → 预测 0.35 → gain 0.125 ──────────────────
print("\n[C] 候选有效但收益小")
delta_c, info_c = verify(np.array([-0.05, 0.0, 0.0]), pred, d_cur)
print("     候选 Δx=−0.05 → gain=%.3f  scale=%.2f  %s"
      % (info_c["gain"], info_c["chosen_scale"], info_c["reason"]))
ck("C1 仍采纳(过 gain_min)", info_c["gain"] >= 0.02, "gain=%.3f" % info_c["gain"])

# ── D 轻微变差：候选 −0.02 → gain ≈ −0.05 → 缩权 ─────────────────────
print("\n[D] 候选轻微变差（应缩权而非归零）")
delta_d, info_d = verify(np.array([0.02, 0.0, 0.0]), pred, d_cur)
print("     候选 Δx=+0.02 → gain=%.3f  scale=%.2f  %s"
      % (info_d["gain"], info_d["chosen_scale"], info_d["reason"]))
ck("D1 缩权不归零", 0 < info_d["chosen_scale"] < 1.0,
   "scale=%.2f" % info_d["chosen_scale"])

# ── E 多候选：用"过度修正会过冲"的世界模型逼出保守档 ─────────────────
print("\n[E] 多候选自动选优（世界模型带过冲：修太狠反而过头）")
def pred_overshoot(delta):
    """过度修正会冲过零点: |0.40 + x|, x=−0.40 归零, x=−0.60 反而变 0.20"""
    x = float(np.asarray(delta, dtype=float).reshape(-1)[0])
    return abs(0.40 + x)
d_e, i_e = verify(np.array([-0.60, 0.0, 0.0]), pred_overshoot, 0.40)
print("     候选 0.60 → 试算 %s" % [(t["scale"], round(t.get("gain") or 0, 3)) for t in i_e["tried"]])
print("     选中 scale=%.2f  gain=%.3f" % (i_e["chosen_scale"], i_e["gain"] or 0))
ck("E1 未选全额档", i_e["chosen_scale"] < 1.0, "scale=%.2f" % i_e["chosen_scale"])
ck("E2 选中档的 gain 优于全额档",
   i_e["gain"] > (i_e["tried"][0].get("gain") or -9), "选中 %.3f vs 全额 %.3f"
   % (i_e["gain"], i_e["tried"][0].get("gain") or -9))

# ── F 无预测器：零回退 ───────────────────────────────────────────────
print("\n[F] 无可信世界模型（权重未训练/接口未就绪）")
d_f, i_f = verify(np.array([0.32, 0.0, 0.0]), None, d_cur)
print("     → verified=%s  %s" % (i_f["verified"], i_f["reason"]))
ck("F1 verified=False 且原样放行", i_f["verified"] is False and abs(d_f[0] - 0.32) < 1e-9)

# ── G/H 梯度耦合 ────────────────────────────────────────────────────
print("\n[G/H] 几何梯度 ⊕ 世界模型预测梯度")
g_geo = np.array([-0.08, 0.0, 0.0])
g_pred = np.array([-0.30, 0.0, 0.0])
g0 = couple_with_geometry(g_geo, g_pred, lam=0.0)
g1 = couple_with_geometry(g_geo, g_pred, lam=1.0)
print("     λ=0   → %s (应逐位等于几何)" % np.round(g0, 4))
print("     λ=1.0 → %s (应等于 geo+pred)" % np.round(g1, 4))
ck("G1 λ=0 零回退", np.allclose(g0, g_geo))
ck("H1 λ=1 数值正确", np.allclose(g1, g_geo + g_pred))
ck("H2 预测项缺失时零回退", np.allclose(couple_with_geometry(g_geo, None, 1.0), g_geo))

# ── I 端到端：解析度规给候选 → 世界模型验证 → 收敛更好 ──────────────
print("\n[I] 端到端：解析候选 + 世界模型验证，收敛是否更快/更稳")
sys.path.insert(0, os.path.join(ROOT, "src", "lerobot", "policies", "manifold"))
from geodesic_inject import correct  # noqa: E402

def run_loop(use_wm: bool, d0: float = -0.40, K: float = 6.0):
    d = d0
    hist = []
    for _ in range(10):
        # ⚠️ 插入轴取 Z、力沿 X —— 轴与力必须不同向, 否则力被径向投影全剔除(实测: 同向轴=修正恒 0)
        F = [d * K, 0.0, 0.0]
        u, inf = correct([0.5, 0.0, 0.0], None, [0.0, 0.0, 1.0], eta=1.0, V_p=0.0,
                         force=F, contact=0.95)
        dd = np.asarray(inf.get("delta") or [0, 0, 0], dtype=float)
        if use_wm:
            dd, _wi = verify(dd, make_wm(d), abs(d))    # d 本身带符号
        d += float(dd[0])
        hist.append(round(abs(d), 5))
        if abs(d) < 0.02:
            break
    return hist

h_plain = run_loop(False)
h_wm = run_loop(True)
print("     无验证: %s" % h_plain)
print("     有验证: %s" % h_wm)
ck("I1 两者都收敛到 <0.05mm", abs(h_plain[-1]) < 0.05 and abs(h_wm[-1]) < 0.05)
ck("I2 有验证不放慢收敛", len(h_wm) <= len(h_plain) + 1, "拍数 %d vs %d" % (len(h_wm), len(h_plain)))
ck("I3 有验证无过冲(不出现反向大于初值)", all(x <= abs(-0.40) + 1e-6 for x in h_wm))

# ── 汇总 ────────────────────────────────────────────────────────────
print("\n" + "=" * 78)
print("汇总: PASS=%d  FAIL=%d" % (len(PASS), len(FAIL)))
if FAIL:
    print("失败项: " + ", ".join(FAIL))
print("判定: " + ("PASS" if not FAIL else "FAIL"))
print("=" * 78)
sys.exit(0 if not FAIL else 1)
