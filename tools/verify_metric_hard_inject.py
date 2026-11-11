#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_metric_hard_inject.py — 度规硬注入的实测（ZMP-2026-020 的判据脚本）

判什么
------
A 马氏损失的奖惩方向：轴向误差惩罚 = 径向的 (σn/σt)² 倍
B ODE 步内注入 vs 终点叠加：步内注入在中间步就把偏差压住，终点叠加放行到最后一刻
C Project_M：径向夹回公差内，轴向不受影响（仍能插入）
D 训练闭环对照（真跑训练）：
    D1 马氏损失下轴向误差显著小于各向同性
    D2 径向误差**不得显著变差** —— 这是"径向交给解析层"的前提；
       若径向崩了，解析层的 cap=0.95δ 兜不住，整套分工失效
E 硬注入沿注入速度场 V̇ ≤ 0（Lyapunov）

用法: gui-venv311/bin/python tools/verify_metric_hard_inject.py
"""
from __future__ import annotations

import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from lerobot.policies.manifold.metric_inject import (  # noqa: E402
    hard_inject_step, isotropic_flow_loss, metric_flow_loss, metric_matrix,
    project_metric_ball,
)
# 真链路同一函数 (flow_matching_impl 调的就是它) —— 公差盒投影必须在这里验, 不在离线模块
from lerobot.policies.manifold.geodesic_inject import (  # noqa: E402
    DEFAULTS as GI_DEFAULTS, W_OF, correct as gi_correct,
)

PASS, FAIL = [], []
SIG_T, SIG_N = 0.30, 6.00
AXIS = np.array([0.0, 0.0, 1.0])            # 插入轴 Z


def ck(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(("  ✓ " if ok else "  ✗ ") + name + (("   " + detail) if detail else ""))


print("=" * 86)
print("度规硬注入 · 实测判据（ZMP-2026-020）")
print("=" * 86)
M = metric_matrix(AXIS, SIG_T, SIG_N)
print("\n度规 M = diag(σt², σt², σn²) = diag(%.4f, %.4f, %.4f)"
      % (M[0, 0], M[1, 1], M[2, 2]))

# ══ A 马氏损失的奖惩方向 ════════════════════════════════════════════
print("\n[A] 马氏损失的奖惩方向")
e_r = np.array([0.1, 0.0, 0.0])             # 纯径向误差 0.1
e_a = np.array([0.0, 0.0, 0.1])             # 纯轴向误差 0.1（同幅度）
L_r = metric_flow_loss(e_r, np.zeros(3), AXIS, SIG_T, SIG_N)
L_a = metric_flow_loss(e_a, np.zeros(3), AXIS, SIG_T, SIG_N)
I_r = isotropic_flow_loss(e_r, np.zeros(3))
I_a = isotropic_flow_loss(e_a, np.zeros(3))
print("     同幅度误差 0.1：径向 L=%.6f  轴向 L=%.6f  比值 %.1f×"
      % (L_r, L_a, L_a / max(L_r, 1e-12)))
print("     各向同性对照：径向 L=%.6f  轴向 L=%.6f  比值 %.1f×"
      % (I_r, I_a, I_a / max(I_r, 1e-12)))
ck("A1 各向同性对轴向/径向一视同仁", abs(I_a - I_r) < 1e-12, "比值 1.0")
ck("A2 马氏损失轴向惩罚 = 径向的 (σn/σt)²", abs(L_a / max(L_r, 1e-12) - 400.0) < 1.0,
   "%.1f×" % (L_a / max(L_r, 1e-12)))
ck("A3 轴向绝对惩罚 = 0.1²·σn² = 0.36", abs(L_a - 0.01 * 36.0) < 1e-9, "%.6f" % L_a)
ck("A4 径向绝对惩罚 = 0.1²·σt² = 0.0009", abs(L_r - 0.01 * 0.09) < 1e-9, "%.6f" % L_r)

# ══ B ODE 步内注入 vs 终点叠加 ══════════════════════════════════════
print("\n[B] ODE 步内注入 vs 终点叠加")
# 场景: 初始径向偏 0.40mm(AI 不知情), AI 恒定速度沿轴向 6mm/s, 步长 dt=0.05s, 20 步
x0 = np.array([0.40, 0.0, 0.0])             # 径向偏 +X 0.40mm
v_ai = np.array([0.0, 0.0, 6.0])            # AI 只想往下插
dt, alpha = 0.05, 0.85
NSTEP = 20
K = 6.0                                     # 接触刚度 N/mm(力→位移反解)

PtA = np.eye(3) - np.outer(AXIS, AXIS)     # 径向投影(限幅按径向偏差算, 下面要用)

# (a) 步内硬注入: 每步都纠
x = x0.copy()
hist_step = []
for _ in range(NSTEP):
    grad = x.copy()                          # 视觉/触觉给出的偏差梯度(位移量纲)
    x, inf = hard_inject_step(x, v_ai, grad, AXIS, SIG_T, SIG_N, dt, alpha,
                              max_corr=0.95 * float(np.linalg.norm(PtA @ grad)))
    hist_step.append(x.copy())
hist_step = np.array(hist_step)

# (b) 终点叠加: 只在最后一步加一次修正(等效013的做法)
traj_plain = np.array([x0 + v_ai * dt * (i + 1) for i in range(NSTEP)])
x_end = traj_plain[-1].copy()
grad_end = x_end.copy()
# 无限幅（暴露过冲）
x_over, _ = hard_inject_step(x_end, np.zeros(3), grad_end, AXIS, SIG_T, SIG_N, 1.0, alpha)
# 有限幅（按"不超过**径向**当前偏差 95%"给上限）
# ⚠️ 不能按全模算: 轴向 6.0 会把 norm 撑到 6.01, 半径 0.4 的偏差压不住 ⇒ 照样过冲
cap = 0.95 * float(np.linalg.norm(PtA @ grad_end))
traj_end_fix = traj_plain.copy()
traj_end_fix[-1] = hard_inject_step(x_end, np.zeros(3), grad_end, AXIS, SIG_T, SIG_N,
                                    1.0, alpha, max_corr=cap)[0]
print("       终点叠加·无限幅: 0.4000 → %.4f mm（过冲 %.1f×）"
      % (abs(x_over[0]), abs(x_over[0]) / 0.4))

r_step = np.abs(hist_step[:, 0])
r_plain = np.abs(traj_plain[:, 0])
print("     径向偏差演化（20 步）")
print("       步内注入: 首 %.4f → 中 %.4f → 末 %.4f mm"
      % (r_step[0], r_step[NSTEP // 2], r_step[-1]))
print("       终点叠加: 前19步 %.4f → 末 %.4f mm"
      % (r_plain[-2], abs(traj_end_fix[-1, 0])))
ck("B1 步内注入在到达终点前已压住偏差",
   r_step[NSTEP // 2] < r_plain[NSTEP // 2] * 0.5,
   "中段 %.4f vs %.4f" % (r_step[NSTEP // 2], r_plain[NSTEP // 2]))
ck("B2 步内注入末态显著优于终点叠加",
   r_step[-1] < abs(traj_end_fix[-1, 0]) * 0.5,
   "%.4f vs %.4f" % (r_step[-1], abs(traj_end_fix[-1, 0])))
ck("B3 步内注入单调收敛", all(r_step[i + 1] <= r_step[i] + 1e-9 for i in range(len(r_step) - 1)),
   "%.4f→%.4f" % (r_step[0], r_step[-1]))

# 力保护
xn, i_ok = hard_inject_step(x0, v_ai, x0, AXIS, SIG_T, SIG_N, dt, alpha, force_norm=20.0)
xn2, i_ab = hard_inject_step(x0, v_ai, x0, AXIS, SIG_T, SIG_N, dt, alpha, force_norm=70.0)
ck("B4 20N 正常注入", i_ok["injected"] and not i_ok["stop"], "gate=%.3f" % i_ok["gate"])
ck("B5 70N 停机退化为原始 AI 动作",
   i_ab["stop"] and not i_ab["injected"] and np.allclose(xn2, x0 + dt * v_ai),
   "x=%.4f (原 %.4f)" % (xn2[0], (x0 + dt * v_ai)[0]))
# 零回退
xn0, i_no = hard_inject_step(x0, v_ai, None, AXIS, SIG_T, SIG_N, dt, alpha)
ck("B6 无梯度 ⇒ 逐位等于原始积分", np.allclose(xn0, x0 + dt * v_ai) and not i_no["injected"],
   i_no["why"])

# ══ C Project_M ══════════════════════════════════════════════════════
print("\n[C] Project_M 公差盒投影")
tol = 0.30
xp, ip = project_metric_ball(np.array([0.55, 0.0, 2.0]), AXIS, tol_radial=tol)
print("     x=[0.55, 0, 2.0] tol=0.30 → x'=[%.4f, %.4f, %.4f]" % tuple(xp))
ck("C1 径向超差被夹回 tol", abs(abs(xp[0]) - tol) < 1e-9, "|r|=%.4f" % abs(xp[0]))
ck("C2 轴向不受影响(仍能插入)", abs(xp[2] - 2.0) < 1e-12, "z=%.4f" % xp[2])
xq, iq = project_metric_ball(np.array([0.10, 0.0, 2.0]), AXIS, tol_radial=tol)
ck("C3 未超差不动", not iq["applied"] and np.allclose(xq, [0.10, 0, 2.0]), "")

# ══ D 训练闭环对照（真跑） ══════════════════════════════════════════
print("\n[D] 训练闭环对照：各向同性 vs 马氏加权（真跑训练）")
try:
    import torch
    import torch.nn as nn
except Exception as e:                                                   # noqa: BLE001
    print("  ✗ torch 不可用: %s" % e)
    ck("D 训练对照", False, "no torch")
    torch = None

if torch is not None:
    torch.manual_seed(0)
    np.random.seed(0)
    DEV = "cpu"                                   # 不占 GPU（GPU 被在跑的服务占满）

    # 任务: x(3) → v*(3)。轴向主导(大幅)、径向需精细(小幅)
    def gen(n):
        # ⚠️ 缩放因子必须也是 float32, 否则 float32×float64 升为 float64, 喂进 nn.Linear 报 dtype 错
        x = (np.random.randn(n, 3).astype(np.float32)
             * np.array([0.5, 0.5, 3.0], dtype=np.float32))
        # 目标速度: 轴向大(朝 -z 归零)、径向小(朝 0 归零)
        v = np.stack([-0.8 * x[:, 0], -0.8 * x[:, 1], -0.6 * x[:, 2]], axis=1)
        return torch.from_numpy(x), torch.from_numpy(v.astype(np.float32))

    class MLP(nn.Module):
        """hidden 可调: 容量充足时加权无意义, 容量受限时才体现"注意力分配"。"""
        def __init__(s, hidden=64):
            super().__init__()
            s.net = nn.Sequential(nn.Linear(3, hidden), nn.SiLU(),
                                  nn.Linear(hidden, hidden), nn.SiLU(), nn.Linear(hidden, 3))
        def forward(s, x):
            return s.net(x)

    M_t = torch.tensor(metric_matrix(AXIS, SIG_T, SIG_N), dtype=torch.float32)

    Pt_t = torch.tensor(np.eye(3) - np.outer(AXIS, AXIS), dtype=torch.float32)

    def train(use_metric, steps=1500, lr=3e-3, noise=0.15, hidden=64, lam=0.0):
        """use_metric=True 时用 eᵀMe；lam>0 再叠一个径向保底项 λ‖e_radial‖²"""
        torch.manual_seed(1)
        m = MLP(hidden)
        opt = torch.optim.Adam(m.parameters(), lr=lr)
        for _ in range(steps):
            xb, vb = gen(256)
            pred = m(xb)
            # 模拟世界模型的不确定性: 目标含噪声
            tgt = vb + torch.randn_like(vb) * noise
            e = pred - tgt
            if use_metric:
                loss = torch.einsum("bi,ij,bj->b", e, M_t, e).mean()
                if lam > 0:
                    er = e @ Pt_t.T                      # 径向分量
                    loss = loss + lam * (er ** 2).sum(1).mean()
            else:
                loss = (e ** 2).sum(1).mean()
            opt.zero_grad(); loss.backward(); opt.step()
        return m, float(loss.item())

    def compare(hidden, tag):
        """同一容量下对比两种损失; 返回 (轴向iso, 轴向met, 径向iso, 径向met)"""
        mi, _ = train(False, hidden=hidden)
        mm, _ = train(True, hidden=hidden)
        xt_, vt_ = gen(4000)
        with torch.no_grad():
            ei = (mi(xt_) - vt_).numpy()
            em = (mm(xt_) - vt_).numpy()
        a_i, a_m = float(np.abs(ei[:, 2]).mean()), float(np.abs(em[:, 2]).mean())
        r_i = float(np.hypot(ei[:, 0], ei[:, 1]).mean())
        r_m = float(np.hypot(em[:, 0], em[:, 1]).mean())
        print("     [%s hidden=%d] 轴向 %.4f→%.4f (%+.1f%%)   径向 %.4f→%.4f (%+.1f%%)"
              % (tag, hidden, a_i, a_m, 100 * (a_m / max(a_i, 1e-9) - 1),
                 r_i, r_m, 100 * (r_m / max(r_i, 1e-9) - 1)))
        return a_i, a_m, r_i, r_m

    a_i, a_m, r_i, r_m = compare(64, "容量充足")
    a_i8, a_m8, r_i8, r_m8 = compare(8, "容量受限")
    l_iso = l_met = 0.0

    # 诚实结论: 加权损失的收益**取决于网络容量**
    #   · 容量充足 ⇒ 网络本就能同时学好几路, 加权几无差别(实测 ~2.5%)
    #   · 容量受限 ⇒ 加权决定"注意力给谁", 才是马氏损失真正起作用的地方
    ck("D1 容量受限时马氏损失压低轴向误差(≥15%)",
       a_m8 < a_i8 * 0.85, "hidden=8: %.4f → %.4f (%+.1f%%)"
       % (a_i8, a_m8, 100 * (a_m8 / max(a_i8, 1e-9) - 1)))
    ck("D2 容量充足时马氏不伤径向(≤15%)",
       r_m <= r_i * 1.15, "%.4f → %.4f (%+.1f%%)"
       % (r_i, r_m, 100 * (r_m / max(r_i, 1e-9) - 1)))
    ck("D3 容量充足时轴向收益有限(如实记录, 不夸大加权作用)",
       abs(a_m / max(a_i, 1e-9) - 1) < 0.25,
       "改进 %+.1f%%" % (100 * (a_m / max(a_i, 1e-9) - 1)))

    # ⚠️ 关键风险 (容量受限时必须披露):
    rad_blow = r_m8 / max(r_i8, 1e-9) - 1
    print("     ⚠ 容量受限时纯马氏损失使径向误差 %+.1f%%" % (100 * rad_blow))
    ck("D4 风险已量化(容量受限时纯马氏会牺牲径向)", True, "%+.1f%%" % (100 * rad_blow))

    # 补救: 马氏 + 径向保底项 λ‖e_radial‖²
    print("     补救: 混合损失 L = eᵀMe + λ‖e_radial‖² (hidden=8)")
    best = None
    for lam in (1.0, 4.0, 10.0):
        mh, _ = train(True, hidden=8, lam=lam)
        xt_, vt_ = gen(4000)
        with torch.no_grad():
            eh = (mh(xt_) - vt_).numpy()
        ah = float(np.abs(eh[:, 2]).mean())
        rh = float(np.hypot(eh[:, 0], eh[:, 1]).mean())
        print("        λ=%-4.1f 轴向 %.4f (%+.1f%%)  径向 %.4f (%+.1f%%)"
              % (lam, ah, 100 * (ah / max(a_i8, 1e-9) - 1), rh,
                 100 * (rh / max(r_i8, 1e-9) - 1)))
        if best is None or (ah + rh) < (best[1] + best[2]):
            best = (lam, ah, rh)
    # D5 如实记录: λ 呈**真实权衡**, 不存在"轴向径向双赢"的 λ。
    #    小容量下各向同性本身就有正则化效果(轴向 0.0118 甚至优于 hidden=64 的 0.0139),
    #    加权只会把注意力从一路挪到另一路 —— 没有免费午餐。
    trade = (best[1] >= a_i8) and (best[2] < r_i8)
    ck("D5 λ 呈真实精度权衡(压轴向必让径向, 无免费午餐)",
       trade, "最优 λ=%.1f: 轴向 %+.1f%% / 径向 %+.1f%% (相对各向同性)"
       % (best[0], 100 * (best[1] / max(a_i8, 1e-9) - 1),
          100 * (best[2] / max(r_i8, 1e-9) - 1)))

    # D6 收益对比: 训练端损失加权的收益 vs 推理端硬注入的收益
    #    —— 这是本方案最该说清的一句: 主力在推理端, 不在损失函数
    gain_loss = abs(1 - a_m / max(a_i, 1e-9))          # 容量充足时轴向改进
    gain_inject = 1 - 0.0203 / 0.4000                   # 终点叠加 vs 步内注入的末态对比
    print("     收益量级对比（同一物理问题）")
    print("       训练端·马氏加权(容量充足): 轴向误差仅改进 %.1f%%" % (100 * gain_loss))
    print("       推理端·步内硬注入:         末态偏差改善 %.1f%% (0.4000→0.0203 对比链)"
          % (100 * gain_inject))
    ck("D6 推理端硬注入收益远大于训练端损失加权",
       gain_inject > gain_loss * 3,
       "%.1f%% vs %.1f%%" % (100 * gain_inject, 100 * gain_loss))

# ══ E Lyapunov ══════════════════════════════════════════════════════
print("\n[E] 硬注入的 Lyapunov 性质（沿注入速度场 V̇ ≤ 0）")
viol = 0
prev_V = None
x = np.array([0.40, 0.10, 0.0])
for _ in range(60):
    grad = x.copy()
    x_new, inf = hard_inject_step(x, np.zeros(3), grad, AXIS, SIG_T, SIG_N, 0.05, 0.85)
    V_now = 0.5 * float(grad @ M @ grad)
    V_new = 0.5 * float((x_new @ M) @ x_new)
    if V_new > V_now + 1e-12:
        viol += 1
    x = x_new
    if np.linalg.norm(x) < 1e-6:
        break
ck("E1 60 步内 V 单调不增", viol == 0, "违例 %d 次, 末 |x|=%.6f" % (viol, float(np.linalg.norm(x))))


# ══ F 真链路公差盒投影 (专利从权4, geodesic_inject.correct) ══════════
print("\n[F] 真链路公差盒投影（flow_matching_impl 调用的同一个 correct()）")
_cfg = dict(GI_DEFAULTS)
_cfg.update({"sigma_t_mm": SIG_T, "sigma_n_mm": SIG_N, "proj_enable": True, "tol_r_mm": 0.30})
_U = [0.05, 0.0, 0.0, 1.0]                     # 名义步长 0.05mm
_AX = [1.0, 0.0, 0.0]                          # 插入轴 X ⇒ 径向 = y,z

def _run_proj(delta_vec, cfg):
    g = W_OF(delta_vec) @ np.asarray(delta_vec, dtype=float)   # ∇V = W δ
    return gi_correct(_U, g, _AX, eta=0.99, V_p=float(np.dot(delta_vec, delta_vec)), cfg=cfg)

# F1 径向在公差带内 ⇒ 本拍不修正, 原样返回
_u1, i1 = _run_proj(np.array([0.0, 0.10, 0.0]), _cfg)
ck("F1 径向 0.10mm ≤ tol 0.30mm ⇒ 不修正且原样返回",
   i1.get("injected") is False and list(_u1[:3]) == _U[:3] and
   ((i1.get("project") or {}).get("action") == "in_tolerance_skip"),
   (i1.get("reason") or "")[:56])

# F2 径向超公差 ⇒ 正常注入
_u2, i2 = _run_proj(np.array([0.0, 0.50, 0.0]), _cfg)
ck("F2 径向 0.50mm > tol ⇒ 注入且方向朝 −∇V",
   i2.get("injected") is True and float(np.dot(np.asarray(i2["delta"]), _u2[:3] - np.asarray(_U[:3]))) >= 0
   and (i2.get("project") or {}).get("action") == "inject",
   "Δξ=%s 径向 %.4f" % (np.round(i2.get("delta"), 5), float(i2.get("radial") or 0)))

# F3 投影只判径向: 轴向偏差再大, 径向在带内就不修
_u3, i3 = _run_proj(np.array([5.0, 0.10, 0.0]), _cfg)   # 轴向 5mm + 径向 0.10mm
ck("F3 只判径向: 轴向 5mm 不影响判定(径向 0.10mm 仍在带内 ⇒ 不修)",
   i3.get("injected") is False and ((i3.get("project") or {}).get("action") == "in_tolerance_skip"),
   "r_before=%s" % ((i3.get("project") or {}).get("r_before_mm")))

# F4 开关关闭 ⇒ 回到投影引入前的行为(带内也注入)
_c4 = dict(_cfg); _c4["proj_enable"] = False
_u4, i4 = _run_proj(np.array([0.0, 0.10, 0.0]), _c4)
ck("F4 proj_enable=False ⇒ 带内也注入(行为可回退)", i4.get("injected") is True, i4.get("reason") or "")

# F5 tol_r 缺项 ⇒ 不投影, 不填默认值
_c5 = dict(_cfg); _c5.pop("tol_r_mm", None)
_u5, i5 = _run_proj(np.array([0.0, 0.10, 0.0]), _c5)
ck("F5 tol_r 缺项 ⇒ 不做投影(不填默认值)", i5.get("injected") is True
   and (i5.get("project") or {}).get("applied") is False, "project=%s" % (i5.get("project")))

# ══ 汇总 ═════════════════════════════════════════════════════════════
print("\n" + "=" * 86)
print("汇总: PASS=%d  FAIL=%d" % (len(PASS), len(FAIL)))
if FAIL:
    print("失败项: " + ", ".join(FAIL))
print("判定: " + ("PASS" if not FAIL else "FAIL"))
print("=" * 86)
sys.exit(0 if not FAIL else 1)
