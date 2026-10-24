#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🌐 hjepa_manifold.py — H-JEPA-MR 混合黎曼表征分支 (老倪 2026-10-23)

设计原则 (老倪方案原文): 最小侵入式改造, 主干几乎不动; 几何分支独立、可插拔。

在现有 `hjepa_model.HJEPA3Level` 里的插入点:
    h = v_enc(img) + s_proj(state)        ← 256 维共享特征 (原样不动)
    ├── 原有语义分支 z1/z2/z3/z_pred/head  ← 一个字都不改
    └── 【本模块】几何分支:  h → geo_enc → {se3_head → ξ∈se(3)≅R⁶, sphere_head → v∈T S²}

为什么必须输出切空间向量而不是流形元素 (方案里的硬结论):
    网络输出 ξ∈se(3) 与 v∈T_nS², 再用 g = g₀·exp(ξ̂) / n = Retr_{n₀}(v) 回推。
    原生黎曼层/黎曼 BN 在精细操作这种小扰动场景下训练极不稳, 且有奇异点问题。

坐标口径 (与仓库既有实现对齐, 不另造一套):
    · SE(3) exp/log/hat      → src/lerobot/manifold/lie_intent.py (se3_exp/se3_log/_hat)
    · S²  距离/log/exp/测地线 → src/lerobot/manifold/sphere.py    (distance/log_map/exp_map)
    · 本模块只做"神经网络头 + 损失 + 动力学 rollout", 不重复实现几何算子。

三个子模块:
  1. GeometricBranch —— geo_enc + SE3Head + SphereHead + (可选) 动量 target 分支
  2. manifold_losses —— L_g (SE3 测地线) / L_n (球面) / 切空间 NLL (不确定性)
  3. ManifoldDynamics —— f_dyn(c_t, h_g_t, a_t) → ξ_{t+τ}, 流形动力学 rollout

自检: python3 -m lerobot.manifold.hjepa_manifold --selftest
"""
from __future__ import annotations

import math
import os
import sys

import numpy as np

# ── 几何算子复用仓库既有实现 (不重复造) ──
try:
    from .lie_intent import _hat, se3_exp, se3_log, so3_exp, so3_log
    from . import sphere as S2
except Exception:                                                      # noqa: BLE001
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from lie_intent import _hat, se3_exp, se3_log, so3_exp, so3_log     # type: ignore
    import sphere as S2                                                 # type: ignore

EPS = 1e-12

# 超参 (与方案一致: 几何 loss 量级远低于 JEPA loss, λ 从 1e-3 起步)
D_G = 128                 # 几何特征维
LAMBDA_G_DEFAULT = 1e-3   # SE3 项权重
LAMBDA_N_DEFAULT = 1e-3   # 球面项权重
MOMENTUM = 0.996          # 动量 target encoder 的 EMA 系数 (BYOL/JEPA 口径)


# ═══════════════════════ 1. SE(3) 测地线距离与损失 ═══════════════════════
def se3_distance(T1, T2, weight=None) -> float:
    """SE(3) 测地线距离 d(g₁,g₂) = ‖log(g₁⁻¹ g₂)‖。

    weight: 6 维权重 (ω 与 v 量纲不同, 工程上必须能分别调; 默认全 1)。
    """
    T1 = np.asarray(T1, float).reshape(4, 4)
    T2 = np.asarray(T2, float).reshape(4, 4)
    xi = se3_log(np.linalg.inv(T1) @ T2)                # ξ=(ω(3), v(3))
    xi = np.asarray(xi, float).ravel()[:6]
    if weight is not None:
        w = np.asarray(weight, float).ravel()[:6]
        xi = xi * w
    return float(np.linalg.norm(xi))


def se3_geodesic_loss(pred_T, target_T, weight=None) -> float:
    """L_g = ‖log(g⁻¹ g*)‖²  (方案里的定义, 逐字实现)。"""
    return se3_distance(pred_T, target_T, weight) ** 2


def se3_pose_from_twist(g0, xi):
    """g = g₀ · exp(ξ̂)。网络出 ξ, 这里还原成流形元素。"""
    g0 = np.asarray(g0, float).reshape(4, 4)
    xi = np.asarray(xi, float).ravel()[:6]
    return g0 @ np.asarray(se3_exp(xi), float).reshape(4, 4)


# ═══════════════════════ 2. 球面 (接触法线) 损失 ═══════════════════════
def sphere_distance(n1, n2, antipodal=False) -> float:
    """S² 测地线距离 (半径 1 的弧长)。复用 sphere.distance (含退化点精确处理)。"""
    return float(S2.distance(np.asarray(n1, float).ravel()[:3],
                             np.asarray(n2, float).ravel()[:3], antipodal=antipodal))


def sphere_geodesic_loss(pred_n, target_n, antipodal=False) -> float:
    """L_n = d_{S²}(n, n*)²。小角度下等价于 ‖n−n*‖², 大角度用弧长更稳。"""
    return sphere_distance(pred_n, target_n, antipodal) ** 2


def sphere_retract(n0, v, radius=1.0):
    """n = Retr_{n₀}(v)。方案里写的"球面回退(归一化)";
    严格做法是 exp_map 沿测地线走, 这里两者都提供, 默认走 exp_map。"""
    n0 = np.asarray(n0, float).ravel()[:3]
    v = np.asarray(v, float).ravel()[:3]
    # v 必须切于球面: 去掉径向分量 (数值上网络输出不一定严格切, 必须投影)
    v = S2.tangent_project(n0, v)
    return np.asarray(S2.exp_map(n0, v), float).ravel()[:3]


# ═══════════════════════ 3. 切空间高斯 NLL (不确定性) ═══════════════════════
def tangent_gaussian_nll(mu, target, log_diag_L, dim=None) -> float:
    """切空间对角高斯 NLL: ξ ~ N(μ, LLᵀ), L=diag(exp(log_diag_L))。

    NLL = 0.5·Σ[(y_i−μ_i)²/σ_i² + 2·log σ_i] + const
    只用对角可以保证 Σ 必然 SPD (方案要求 Σ∈SPD(6)), 且实现稳定。
    """
    mu = np.asarray(mu, float).ravel()
    target = np.asarray(target, float).ravel()
    ld = np.asarray(log_diag_L, float).ravel()
    d = min(len(mu), len(target), len(ld)) if dim is None else int(dim)
    mu, target, ld = mu[:d], target[:d], ld[:d]
    var = np.exp(2.0 * ld)
    return float(0.5 * np.sum((target - mu) ** 2 / np.maximum(var, EPS) + 2.0 * ld))


def sample_twist(mu, log_diag_L, rng=None):
    """ξ_sample = μ + L·ε。"""
    rng = np.random.default_rng() if rng is None else rng
    mu = np.asarray(mu, float).ravel()
    ld = np.asarray(log_diag_L, float).ravel()
    d = min(len(mu), len(ld))
    return mu[:d] + np.exp(ld[:d]) * rng.standard_normal(d)


# ═══════════════════════ 4. 神经网络分支 (torch 可选) ═══════════════════════
def _torch():
    import torch
    return torch


def _nn():
    import torch.nn as nn
    return nn


def build_geometric_branch(d_in: int = 256, d_g: int = D_G, twist_dim: int = 6,
                           n_layers: int = 2, with_uncertainty: bool = True):
    """几何分支: 共享特征 h → geo_enc → SE3Head(ξ) + SphereHead(v) (+ 方差头)。

    轻量: 参数量远小于主分支 (方案要求)。n_layers=2 时约 (256·128 + 128·128 + …) ≈ 6.6 万参数,
    主分支 z_enc 三层就有 ~100 万。
    """
    torch = _torch()
    nn = _nn()

    class _MLP(nn.Module):
        def __init__(self, din, dh, dout, nl=2):
            super().__init__()
            layers, prev = [], din
            for _ in range(max(1, nl - 1)):
                layers += [nn.Linear(prev, dh), nn.ReLU()]
                prev = dh
            layers += [nn.Linear(prev, dout)]
            self.net = nn.Sequential(*layers)

        def forward(self, x):
            return self.net(x)

    class GeometricBranch(nn.Module):
        """几何上下文编码器 + 两个流形头。

        forward(h) → dict(xi, v_n, log_sigma)  全部是切空间欧氏向量。
        """

        def __init__(self):
            super().__init__()
            self.geo_enc = _MLP(d_in, d_g, d_g, n_layers)
            self.se3_head = _MLP(d_g, d_g, twist_dim, 2)        # → ξ ∈ se(3)≅R⁶
            self.sph_head = _MLP(d_g, d_g, 3, 2)                # → v ∈ T S²
            self.use_unc = bool(with_uncertainty)
            if self.use_unc:
                # 对角 Σ: 6 维 twist + 3 维法线 的 log σ
                self.var_head = _MLP(d_g, d_g, twist_dim + 3, 2)
                nn.init.constant_(self.var_head.net[-1].bias, -2.0)   # 初始 σ≈0.135, 小扰动先验

        def forward(self, h):
            g = self.geo_enc(h)
            xi = self.se3_head(g)
            v = self.sph_head(g)
            out = {"xi": xi, "v_n": v, "h_g": g}
            if self.use_unc:
                ls = self.var_head(g)
                out["log_sigma"] = ls
            return out

        def trainable_params(self):
            return sum(p.numel() for p in self.parameters() if p.requires_grad)

    return GeometricBranch()


def make_momentum_target(branch):
    """制造动量 target 分支 (方案 §4): 同结构、参数 EMA、全部 requires_grad=False。

    JEPA 的核心思路 —— 目标是"动量的自己", 不是外部标签。这样弱监督场景也能训。
    """
    torch = _torch()
    import copy
    tgt = copy.deepcopy(branch)
    for p in tgt.parameters():
        p.requires_grad = False
    return tgt


def ema_update(target, online, momentum: float = MOMENTUM):
    """θ_target ← m·θ_target + (1−m)·θ_online (动量更新, 不传梯度)。"""
    torch = _torch()
    with torch.no_grad():
        for pt, po in zip(target.parameters(), online.parameters()):
            pt.data.mul_(momentum).add_(po.data, alpha=1.0 - momentum)


# ═══════════════════════ 5. 流形动力学 rollout ═══════════════════════
def build_dynamics(d_c: int = 512, d_g: int = D_G, d_a: int = 4,
                   d_out: int = 6, hidden: int = 256):
    """f_dyn(c_t, h_g_t, a_t) → ξ_{t+τ}  (方案 §三, 流形动力学 rollout)。

    g_{rel,t+τ} = g_{rel,t} · exp(ξ̂_{t+τ})
    """
    nn = _nn()

    class ManifoldDynamics(nn.Module):
        def __init__(self):
            super().__init__()
            self.net = nn.Sequential(
                nn.Linear(d_c + d_g + d_a, hidden), nn.ReLU(),
                nn.Linear(hidden, hidden), nn.ReLU(),
                nn.Linear(hidden, d_out))

        def forward(self, c, h_g, a):
            import torch as _t
            x = _t.cat([c, h_g, a], dim=-1)
            return self.net(x)

    return ManifoldDynamics()


def rollout_poses(g_rel_t, twists):
    """多步 rollout: 依次右乘 exp(ξ̂)。返回 [g_{t+1}, g_{t+2}, ...]。"""
    out, g = [], np.asarray(g_rel_t, float).reshape(4, 4)
    for xi in twists:
        g = se3_pose_from_twist(g, xi)
        out.append(g.copy())
    return out


# ═══════════════════════ 6. 自检 ═══════════════════════
def _selftest() -> int:
    rng = np.random.default_rng(0)
    fails = []

    def chk(name, cond, detail=""):
        print(("  [PASS] " if cond else "  [FAIL] ") + name + (("  " + detail) if detail else ""))
        if not cond:
            fails.append(name)

    print("① SE(3) 测地线距离 / 损失")
    I = np.eye(4)
    chk("d(g,g)=0 逐位", se3_distance(I, I) == 0.0, "%.3e" % se3_distance(I, I))
    # 纯平移 0.1m
    T2 = I.copy(); T2[0, 3] = 0.1
    d = se3_distance(I, T2)
    chk("纯平移 0.1m ⇒ d=0.1", abs(d - 0.1) < 1e-9, "%.10f" % d)
    # 纯旋转 30°
    th = math.radians(30.0)
    Rz = np.array([[math.cos(th), -math.sin(th), 0], [math.sin(th), math.cos(th), 0], [0, 0, 1]])
    T3 = I.copy(); T3[:3, :3] = Rz
    d3 = se3_distance(I, T3)
    chk("纯旋转 30° ⇒ d=0.5236", abs(d3 - th) < 1e-9, "%.10f (π/6=%.10f)" % (d3, th))
    # 对称性
    chk("距离对称 d(a,b)=d(b,a)",
        abs(se3_distance(I, T2) - se3_distance(T2, I)) < 1e-12)
    # 损失是距离的平方
    chk("L_g = d²", abs(se3_geodesic_loss(I, T2) - 0.01) < 1e-12,
        "%.12f" % se3_geodesic_loss(I, T2))

    print("② twist 还原 round-trip")
    xi = rng.normal(size=6) * 0.1
    g1 = se3_pose_from_twist(I, xi)
    xi_back = np.asarray(se3_log(g1), float).ravel()[:6]
    # SE3 的 ω 与 v 在两套约定下可能顺序不同, 用"还原位姿"而不是"还原向量"做判据更硬
    g_back = se3_pose_from_twist(I, xi_back)
    err = float(np.abs(g_back - g1).max())
    chk("g→log→exp→g 逐元素误差 <1e-12", err < 1e-12, "%.3e" % err)
    chk("rollout 一步与直接还原一致",
        np.abs(rollout_poses(I, [xi])[0] - g1).max() < 1e-12)

    print("③ 球面距离 / 损失 / 回退")
    n0 = np.array([0.0, 0.0, 1.0])
    chk("d(n,n)=0 逐位", sphere_distance(n0, n0) == 0.0, "%.3e" % sphere_distance(n0, n0))
    n1 = S2.normalize(np.array([1.0, 0.0, 0.0]))[0]    # normalize 返回 (array, meta) 元组
    dsn = sphere_distance(n0, n1)
    chk("正交法线 ⇒ d=π/2", abs(dsn - math.pi / 2) < 1e-9, "%.10f" % dsn)
    chk("L_n = d²", abs(sphere_geodesic_loss(n0, n1) - (math.pi / 2) ** 2) < 1e-9)
    # 回退必须落在球面上且只走小角度
    v = S2.tangent_project(n0, np.array([0.1, 0.05, 0.0]))
    n_new = sphere_retract(n0, v)
    chk("Retr 后仍在单位球面", abs(np.linalg.norm(n_new) - 1.0) < 1e-9,
        "|n|=%.12f" % np.linalg.norm(n_new))
    chk("Retr 走的是小角度", 0 < sphere_distance(n0, n_new) < 0.2,
        "d=%.6f" % sphere_distance(n0, n_new))
    # 径向分量必须被投影掉
    n_rad = sphere_retract(n0, np.array([0.0, 0.0, 5.0]))
    chk("纯径向输入 ⇒ 法线不动", sphere_distance(n0, n_rad) < 1e-9,
        "d=%.3e" % sphere_distance(n0, n_rad))
    # 双覆盖: n 与 −n 在 antipodal 下同点
    chk("antipodal 把 ±n 视为同点",
        abs(S2.distance(n0, -n0, antipodal=True)) < 1e-12)

    print("④ 切空间高斯 NLL / 采样")
    mu = np.zeros(6)
    y = np.array([0.1, 0.0, 0.0, 0.0, 0.0, 0.0])
    ls = np.full(6, math.log(0.1))       # σ=0.1
    nll = tangent_gaussian_nll(mu, y, ls)
    # 手算: 0.5·[(0.1/0.1)² + 2·6·log(0.1)]
    want = 0.5 * (1.0 + 12 * math.log(0.1))
    chk("NLL 与手算一致", abs(nll - want) < 1e-12, "%.10f vs %.10f" % (nll, want))
    samples = np.stack([sample_twist(mu, ls, rng=rng) for _ in range(4000)])
    chk("采样 std≈0.1", abs(samples.std() - 0.1) < 0.01, "%.4f" % samples.std())
    chk("采样均值≈0", abs(samples.mean()) < 0.01, "%.4f" % samples.mean())

    print("⑤ 神经网络分支 (torch 可选)")
    try:
        torch = _torch()
        br = build_geometric_branch()
        n_par = sum(p.numel() for p in br.parameters())
        h = torch.randn(4, 256)
        o = br(h)
        chk("xi 形状 (B,6)", tuple(o["xi"].shape) == (4, 6), str(tuple(o["xi"].shape)))
        chk("v_n 形状 (B,3)", tuple(o["v_n"].shape) == (4, 3), str(tuple(o["v_n"].shape)))
        chk("含不确定性头", "log_sigma" in o, str(tuple(o.get("log_sigma").shape)))
        chk("参数量远小于主分支", n_par < 200_000, "%s 参数" % format(n_par, ","))

        tgt = make_momentum_target(br)
        chk("动量 target 全部 requires_grad=False",
            all(not p.requires_grad for p in tgt.parameters()))
        before = [p.clone() for p in tgt.parameters()]
        opt = torch.optim.SGD(br.parameters(), lr=0.1)
        loss = br(torch.randn(4, 256))["xi"].pow(2).mean()
        opt.zero_grad(); loss.backward(); opt.step()
        ema_update(tgt, br, 0.9)
        moved = any(not torch.equal(b, p) for b, p in zip(before, tgt.parameters()))
        chk("EMA 真的改动了 target", moved)

        dyn = build_dynamics()
        out = dyn(torch.randn(2, 512), torch.randn(2, D_G), torch.randn(2, 4))
        chk("动力学输出 (B,6)", tuple(out.shape) == (2, 6), str(tuple(out.shape)))
    except Exception as e:                                            # noqa: BLE001
        chk("torch 分支可用", False, "%s: %s" % (type(e).__name__, str(e)[:120]))

    print()
    if fails:
        print("❌ %d 项失败: %s" % (len(fails), ", ".join(fails)))
        return 1
    print("✅ 全部通过 (H-JEPA-MR 几何分支)")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv or len(sys.argv) == 1:
        sys.exit(_selftest())
    print("用法: python3 -m lerobot.manifold.hjepa_manifold --selftest")
