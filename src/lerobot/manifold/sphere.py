#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sphere.py — 归一化球面 S^n 的完整实现 (投影 / 度量 / 梯度 / 测地线 / 平行移动 / 可微层 + 训练三件套)。

对着的方案 (老倪 2026-10-15「归一化球面实现方案」) 逐条落到代码:

  二、实现方法      方法一 直接归一化 → `normalize()`      (一行, 含 eps 防除零)
                    方法二 指数映射   → `exp_map()` / `log_map()`
                    方法三 四元数参数化 → 由 `manifold_engine` 的 su2 档提供 (SU(2)≅S³), 本文件给球面双覆盖口径
                    方法四 投影层     → `SphereProjection` (torch, 可插任何网络末端, 可选温度/可学增益)
  三、推荐方案      投影层 + 正则化 → `SphereProjection` + `unit_norm_regularizer`
                    训练: 归一化**可微** (torch.autograd 直接过) / 推理: 直接归一化
  四、训练注意      零点不可导     → `EPS` + `clamp_min` (零向量给固定基向量, 不出 NaN)
                    长度约束       → `unit_norm_regularizer` 用 (‖x‖²−1)² (零点**可导**且为极小)
                    球面距离       → `sphere_distance_loss(mode="cos"|"arccos"|"fs")`
                    温度参数       → `SphereProjection(temperature=τ)` (τ↓ 集中, τ↑ 铺开)
  五、引擎里的位置  编码器→投影层→球面点→球面度量/梯度/测地线/更新  —— 对应本文件 + manifold_engine.sphere 档
  六、球面上的计算  距离/梯度/测地线/平行移动/指数映射/对数映射 —— 全部给出真公式 (见下)

数学约定 (S^n ⊂ R^{n+1}, 单位球):
  · 点 p: ‖p‖ = 1
  · 切空间 T_p = {v : ⟨v, p⟩ = 0}          `tangent_project()`
  · 内蕴距离 d(p,q) = arccos⟨p,q⟩ (弧长, 半径 1)   `distance()`
  · 指数映射 exp_p(v) = p·cos‖v‖ + (v/‖v‖)·sin‖v‖   `exp_map()`
  · 对数映射 log_p(q) = θ·(q − ⟨p,q⟩p)/‖q − ⟨p,q⟩p‖, θ = arccos⟨p,q⟩   `log_map()`
  · 大圆测地线 γ(t) = slerp(p0,p1,t)          `geodesic_slerp()` / `great_circle_path()`
  · 平行移动 (沿大圆): v' = v + ⟨v,e⟩·((c−1)e − s·p0),  c=⟨p0,p1⟩, s=√(1−c²), e=(p1−c·p0)/s
      —— 保持 ⟨v',p1⟩=0 且 ‖v'‖=‖v‖ 且内积不变 (判据里逐项核)   `parallel_transport()`
  · 黎曼梯度 grad_S φ(p) = 切空间投影(∇φ(p)) = ∇φ − p⟨∇φ,p⟩   `riemannian_gradient()`

torch 侧 (训练用, 可微): `SphereProjection` / `sphere_distance_loss` / `unit_norm_regularizer`
  + `torch_exp_map` / `torch_log_map` / `torch_tangent_project` / `torch_parallel_transport`
  torch 是**惰性导入**的 (引擎走 numpy 时不付代价)。
"""
from __future__ import annotations

import math

import numpy as np

EPS = 1e-12          # 防除零 (方案四「加一个极小量防止除零」)
STD_EPS = 1e-6       # 数值标准差下限


# ═══════════════════════════ 基础: 归一化 / 投影 (方法一 · 方法四) ═══════════════════════════
def normalize(x, eps: float = EPS, temperature: float = 1.0, radius: float = 1.0):
    """方法一: 除以自身长度 ⇒ 单位向量。temperature>0: 先 x/τ 再归一 (τ↓集中, τ↑铺开)。

    零向量: 不返回 NaN —— 给固定基向量 (e_0)·radius, 并在 meta 里标明, 由调用方决定是否报警。
    返回 (p, meta): meta 带 r_in (归一化前长度), drift (改动量 ‖p−x‖), zero (是否零向量)。
    """
    x = np.asarray(x, float).ravel()
    t = float(temperature)
    if t <= 0:
        raise ValueError("temperature 必须 > 0 (收到 %r)" % temperature)
    x = x / t
    n = float(np.linalg.norm(x))
    if n < eps:
        p = np.zeros_like(x)
        p[0] = float(radius)
        return p, {"r_in": n, "drift": round(float(np.linalg.norm(p)), 6), "zero": True, "temperature": t}
    p = x / n * float(radius)
    return p, {"r_in": round(n, 6), "drift": round(float(np.linalg.norm(p - x)), 6), "zero": False,
               "temperature": t}


def project(x, radius: float = 1.0, temperature: float = 1.0):
    """方法四 (投影层) 的 numpy 版: 把任意向量投到半径 radius 的球面; 返回 (p, residual, meta)。

    residual = |‖p‖ − radius| —— 投影后应该 ≈0 (引擎 ManifoldProjector 同口径)。
    """
    p, meta = normalize(x, temperature=temperature, radius=radius)
    return p, abs(float(np.linalg.norm(p)) - float(radius)), meta


# ═══════════════════════════ 球面上的计算 (方案六) ═══════════════════════════
def _angle(c: float) -> float:
    """由内积 c 取夹角 θ (稳定式): θ = 2·arcsin(√((1−c)/2))。

    比 arccos(c) 好在退化点**精确**: c=1 ⇒ θ=0 (逐位 0), c=−1 ⇒ θ=π;
    arccos 在 c=1 附近受浮点影响会给出 ~1.5e-8 的假角。定义域外先夹到 [−1,1]。
    """
    if c >= 1.0:
        return 0.0
    if c <= -1.0:
        return math.pi
    return 2.0 * math.asin(math.sqrt(0.5 * (1.0 - c)))


def dot(p, q) -> float:
    return float(np.dot(np.asarray(p, float).ravel(), np.asarray(q, float).ravel()))


def distance(p, q, antipodal: bool = False) -> float:
    """球面距离 = 夹角 (半径 1 时=弧长)。

    antipodal=True ⇒ 把 ±p 视为同一点 (双覆盖消歧) ⇒ arccos|⟨p,q⟩|, 上界 π/2
    —— 这是 SO(3) 的物理口径 (180° 旋转 = π); 默认 False 是纯球面口径 (上界 π)。
    """
    p = np.asarray(p, float).ravel()
    q = np.asarray(q, float).ravel()
    c = dot(p, q) / max(np.linalg.norm(p) * np.linalg.norm(q), EPS)
    if antipodal:
        c = abs(c)
    return _angle(c)


def tangent_project(p, v):
    """切空间投影: 去掉法向分量 ⇒ ⟨结果, p⟩ = 0 (方案六「梯度: 减去径向分量」)。"""
    p = np.asarray(p, float).ravel()
    v = np.asarray(v, float).ravel()
    return v - p * (dot(v, p) / max(float(np.dot(p, p)), EPS))


def riemannian_gradient(p, grad_euclid):
    """球面上的黎曼梯度 = 欧氏梯度的切空间投影 (引擎 `MetricCalculator.tangent_gradient` 同口径)。"""
    return tangent_project(p, grad_euclid)


def exp_map(p, v):
    """指数映射 exp_p(v): 切向量 → 球面点。v=0 ⇒ 原样返回 p (不动点)。"""
    p = np.asarray(p, float).ravel()
    v = np.asarray(v, float).ravel()
    n = float(np.linalg.norm(v))
    if n < EPS:
        return p.copy()
    return p * math.cos(n) + (v / n) * math.sin(n)


def log_map(p, q):
    """对数映射 log_p(q): 球面点 → 切向量 (与 exp_map 精确互逆)。

    ⚠ 互逆域 = **单射半径 π**: exp_p(v) 只在 ‖v‖ ≤ π 上单射, 超过 π 会把 v 绕回,
    因此 log_p(exp_p(v)) = v 只对 ‖v‖ ≤ π 成立 (‖log‖ 必然 ≤π) —— 球面固有性质, 非实现缺陷。
    """
    p = np.asarray(p, float).ravel()
    q = np.asarray(q, float).ravel()
    c = dot(p, q) / max(np.linalg.norm(p) * np.linalg.norm(q), EPS)
    c = max(-1.0, min(1.0, c))
    w = q - c * p                                  # 平面分量
    nw = float(np.linalg.norm(w))
    if nw < EPS:
        return np.zeros_like(p)
    return (_angle(c) / nw) * w


def geodesic_slerp(p0, p1, t: float):
    """大圆弧上的点 (球面插值)。p0≈p1 ⇒ 退化为线性插值后再归一 (避免 0/0)。"""
    p0 = np.asarray(p0, float).ravel()
    p1 = np.asarray(p1, float).ravel()
    c = max(-1.0, min(1.0, dot(p0, p1) / max(np.linalg.norm(p0) * np.linalg.norm(p1), EPS)))
    th = math.acos(c)
    if th < 1e-8:
        return p0.copy()
    s = math.sin(th)
    return (math.sin((1.0 - t) * th) / s) * p0 + (math.sin(t * th) / s) * p1


def great_circle_path(p0, p1, n: int = 16):
    """大圆路径 (n 个点, 含端点) + 真弧长 (逐段求和, 与解析 θ 对得上)。"""
    n = max(2, int(n))
    ts = np.linspace(0.0, 1.0, n)
    path = np.asarray([geodesic_slerp(p0, p1, float(t)) for t in ts], float)
    L = float(sum(distance(path[i], path[i + 1]) for i in range(len(path) - 1)))
    return {"path": path, "n": n, "length": round(L, 12), "theta": round(distance(p0, p1), 12)}


def parallel_transport(p0, p1, v):
    """沿大圆把 v∈T_{p0} 平行移动到 T_{p1} (方案六「保持与路径的夹角不变」)。

    真公式: c=⟨p0,p1⟩, s=√(1−c²); 若 s≈0 (同点/对径) ⇒ 原样返回。
            e = (p1 − c·p0)/s   (沿测地线的切向单位向量, ⊥ p0)
            v' = v + ⟨v,e⟩·((c−1)·e − s·p0)
    性质 (判据逐条核): ⟨v',p1⟩=0 · ‖v'‖=‖v‖ · 内积不变 ⟨v',w'⟩=⟨v,w⟩。
    """
    p0 = np.asarray(p0, float).ravel()
    p1 = np.asarray(p1, float).ravel()
    v = np.asarray(v, float).ravel()
    c = max(-1.0, min(1.0, dot(p0, p1) / max(np.linalg.norm(p0) * np.linalg.norm(p1), EPS)))
    s = math.sqrt(max(0.0, 1.0 - c * c))
    if s < 1e-9:
        return v.copy()
    e = (p1 - c * p0) / s
    return v + dot(v, e) * ((c - 1.0) * e - s * p0)


# ═══════════════════════════ torch 侧: 可微投影层 + 训练三件套 (方案三/四/七) ═══════════════════════════
def _torch():
    import torch                                                                # noqa: PLC0415
    return torch


class SphereProjection:
    """方法四: 可插在网络末端的投影层 (torch)。**可微** —— 梯度穿过归一化回传。

    · temperature τ —— ⚠ **说清它管什么**: 单纯投影的方向对 τ **不敏感** (x/τ ∥ x ⇒ 归一化后同一点,
      逐位相同, 判据 ④(a) 实测)。τ 真正起作用的是两处:
        (i) **输出量级的目标**: 归一化前除以 τ ⇒ 想让 ‖p‖=1 就必须输出 ‖x‖≈τ,
            即 τ 设定"网络输出该有多大"(与 `unit_norm_regularizer` 联用时才有意义);
        (ii) **分布集中度**: 用 `sphere_logits(⟨p,q⟩/τ)` / vMF κ=1/τ² ⇒ τ↓ 集中, τ↑ 铺开 (判据 ④(b))。
    · learn_gain: 是否带**可学参数** (方案四「缺点: 需要额外参数」—— 这里作为可选项, 默认无参)
    · forward(x) → 单位向量; 零向量给固定基向量 (不出 NaN)
    用法: proj = SphereProjection(temperature=0.1); p = proj(z); logits = sphere_logits(q, p, 0.1)
    """

    def __init__(self, temperature: float = 1.0, learn_gain: bool = False, radius: float = 1.0, eps: float = 1e-6):
        torch = _torch()
        if float(temperature) <= 0:
            raise ValueError("temperature 必须 > 0")
        self.temperature = float(temperature)
        self.radius = float(radius)
        self.eps = float(eps)
        self.learn_gain = bool(learn_gain)
        self._mod = None
        if learn_gain:                      # 方案四「额外参数」: 一个标量增益 (初始化 1.0 ⇒ 零回归)
            nn = torch.nn
            self._mod = nn.Parameter(torch.ones(1))

    def parameters(self):
        return [self._mod] if self._mod is not None else []

    def __call__(self, x):
        torch = _torch()
        if self._mod is not None:
            x = x * self._mod
        x = x / self.temperature
        n = torch.linalg.norm(x, dim=-1, keepdim=True).clamp_min(self.eps)
        p = x / n * self.radius
        # 零向量: ‖x‖ < eps ⇒ 该行给固定基向量 (与 numpy 版同口径, 不产生 NaN)
        zero = (torch.linalg.norm(x, dim=-1, keepdim=True) < self.eps)
        if bool(zero.any()):
            basis = torch.zeros_like(p)
            basis[..., 0] = self.radius
            p = torch.where(zero, basis, p)
        return p


def sphere_distance_loss(p, q, mode: str = "cos", reduction: str = "mean"):
    """方案三/四「用球面距离而非欧氏距离做损失」。

    mode="cos"    : 1 − cos∠p,q (有界 [0,2], 数值最稳, **推荐训练用**)
    mode="arccos" : 真实测地角 arccos⟨p,q⟩ (可解释; 退化点精确=0, 但梯度在 p=q 处奇异 ⇒ 仅报告/评测)
    mode="fs"     : Fubini–Study 口径 arccos|⟨p,q⟩| (双覆盖: ±p 同一点, 比旋转时用)
    """
    torch = _torch()
    p = p / torch.linalg.norm(p, dim=-1, keepdim=True).clamp_min(1e-12)
    q = q / torch.linalg.norm(q, dim=-1, keepdim=True).clamp_min(1e-12)
    c = (p * q).sum(-1)
    if mode == "cos":
        loss = 1.0 - c
    elif mode == "arccos":
        loss = _t_angle(c.clamp(-1.0, 1.0))
    elif mode == "fs":
        loss = _t_angle(c.abs().clamp_max(1.0))
    else:
        raise ValueError("mode 只支持 cos / arccos / fs, 收到 %r" % mode)
    if reduction == "mean":
        return loss.mean()
    if reduction == "none":
        return loss
    return loss.sum()


def _t_angle(c):
    """可微夹角 (稳定式): θ = 2·arcsin(√((1−c)/2)) —— c=1 ⇒ 逐位 0, 不受浮点假角污染。"""
    torch = _torch()
    return 2.0 * torch.arcsin(torch.sqrt((0.5 * (1.0 - c)).clamp_min(0.0)))


def sphere_logits(p, q, temperature: float = 1.0):
    """球面相似度 logits = ⟨p,q⟩/τ —— 方案四「温度参数」**真正起作用**的地方。

    q 可以是 (k,n) 一组候选 ⇒ 返回 (k,) logits。τ↓ softmax 集中 (vMF κ=1/τ²), τ↑ 铺开。
    """
    p = np.asarray(p, float).ravel()
    Q = np.atleast_2d(np.asarray(q, float))
    p = p / max(float(np.linalg.norm(p)), EPS)
    Q = Q / np.maximum(np.linalg.norm(Q, axis=1, keepdims=True), EPS)
    return (Q @ p) / float(temperature)


def von_mises_kappa(temperature: float) -> float:
    """温度 ↔ von Mises–Fisher 集中度 κ = 1/τ² (方案四「温度控制分布集中程度」的几何口径)。"""
    t = float(temperature)
    if t <= 0:
        raise ValueError("temperature 必须 > 0")
    return 1.0 / (t * t)


def torch_sphere_logits(p, q, temperature: float = 1.0):
    """可微版球面 logits ⟨p,q⟩/τ。"""
    torch = _torch()
    p = p / torch.linalg.norm(p, dim=-1, keepdim=True).clamp_min(1e-12)
    q = q / torch.linalg.norm(q, dim=-1, keepdim=True).clamp_min(1e-12)
    return (p * q).sum(-1) / float(temperature)


def unit_norm_regularizer(x, weight: float = 1.0, form: str = "sq"):
    """方案三/四「惩罚向量长度偏离 1 的程度」—— 让网络自然输出接近单位长度, 归一化改动小, 梯度稳。

    form="sq"   : mean((‖x‖² − 1)²) —— 零点**可导**且为极小 (方案四「零点附近不可导」的正解)
    form="abs"  : mean(|‖x‖ − 1|)     —— 线性惩罚, 零点不可导 (留着做对照, 不推荐)
    """
    torch = _torch()
    n2 = (x * x).sum(-1)
    if form == "sq":
        r = (n2 - 1.0) ** 2
    elif form == "abs":
        r = (n2.clamp_min(0.0).sqrt() - 1.0).abs()
    else:
        raise ValueError("form 只支持 sq / abs")
    return weight * r.mean()


def torch_tangent_project(p, v):
    """可微切空间投影: ⟨结果, p⟩ = 0。"""
    torch = _torch()
    p = p / torch.linalg.norm(p, dim=-1, keepdim=True).clamp_min(1e-12)
    return v - p * (p * v).sum(-1, keepdim=True)


def torch_exp_map(p, v):
    """可微指数映射 (v=0 ⇒ p)。"""
    torch = _torch()
    n = torch.linalg.norm(v, dim=-1, keepdim=True)
    safe = n.clamp_min(1e-12)
    return p * torch.cos(n) + (v / safe) * torch.sin(n)


def torch_log_map(p, q):
    """可微对数映射 (与 torch_exp_map 互逆)。"""
    torch = _torch()
    p = p / torch.linalg.norm(p, dim=-1, keepdim=True).clamp_min(1e-12)
    q = q / torch.linalg.norm(q, dim=-1, keepdim=True).clamp_min(1e-12)
    c = (p * q).sum(-1, keepdim=True).clamp(-1.0 + 1e-7, 1.0 - 1e-7)
    w = q - c * p
    nw = torch.linalg.norm(w, dim=-1, keepdim=True).clamp_min(1e-12)
    return (torch.arccos(c) / nw) * w


def torch_parallel_transport(p0, p1, v):
    """可微平行移动 (同 numpy 版公式)。"""
    torch = _torch()
    p0 = p0 / torch.linalg.norm(p0, dim=-1, keepdim=True).clamp_min(1e-12)
    p1 = p1 / torch.linalg.norm(p1, dim=-1, keepdim=True).clamp_min(1e-12)
    c = (p0 * p1).sum(-1, keepdim=True).clamp(-1.0, 1.0)
    s = (1.0 - c * c).clamp_min(0.0).sqrt()
    e = (p1 - c * p0) / s.clamp_min(1e-9)
    return v + (v * e).sum(-1, keepdim=True) * ((c - 1.0) * e - s * p0)


def grad_check(fn, x, eps: float = 1e-5):
    """判据用: 自动微分 vs 中心差分 (返回最大相对误差)。"""
    torch = _torch()
    xr = np.asarray(x, float)
    x = torch.tensor(xr, dtype=torch.float64, requires_grad=True)
    y = fn(x).sum()
    y.backward()
    auto = x.grad.detach().numpy().ravel()
    x0 = xr.ravel()
    num = np.zeros_like(x0)
    for i in range(x0.size):
        e = np.zeros_like(x0)
        e[i] = eps
        with torch.no_grad():
            fp = float(fn(torch.tensor((x0 + e).reshape(xr.shape), dtype=torch.float64)).sum())
            fm = float(fn(torch.tensor((x0 - e).reshape(xr.shape), dtype=torch.float64)).sum())
        num[i] = (fp - fm) / (2 * eps)
    denom = np.maximum(np.abs(auto) + np.abs(num), 1e-12)
    return {"max_rel_err": float(np.max(np.abs(auto - num) / denom)), "auto": auto, "num": num}


def demo(seed: int = 0, n: int = 8, dim: int = 16) -> dict:
    """自检 (无参): 单位性 / 往返 / 平行移动不变量 —— 供 __main__ 与判据脚本复用。"""
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(n, dim))
    P = np.asarray([project(x)[0] for x in X], float)
    unit_err = float(np.abs(np.linalg.norm(P, axis=1) - 1.0).max())
    p0, p1 = P[0], P[1]
    rt = float(np.linalg.norm(exp_map(p0, log_map(p0, p1)) - p1))
    v = tangent_project(p0, rng.normal(size=dim))
    w = tangent_project(p0, rng.normal(size=dim))
    v2, w2 = parallel_transport(p0, p1, v), parallel_transport(p0, p1, w)
    return {"单位性最大偏差": unit_err,
            "exp∘log 往返误差": rt,
            "PT 保内积误差": abs(dot(v2, w2) - dot(v, w)),
            "PT 保长度误差": abs(float(np.linalg.norm(v2)) - float(np.linalg.norm(v))),
            "PT 后切于 p1 (⟨v',p1⟩)": dot(v2, p1),
            "弧长": distance(p0, p1)}


if __name__ == "__main__":
    d = demo()
    print("🧪 sphere.py 自检 — 归一化球面 S^n")
    for k, v in d.items():
        print("   %-22s %.3e" % (k, v))
