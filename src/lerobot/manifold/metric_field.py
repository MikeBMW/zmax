# -*- coding: utf-8 -*-
"""流形引擎**主参数 M = 度量张量 g_ij(x)** (老倪 2026-10-12 设计口径) —— 唯一真源实现。

老倪的设计 (摘要):
> 流形引擎的主参数**是一个张量** —— 随状态变化的**度量张量** g_ij(x)。它决定流形上
> 「距离怎么算 / 梯度怎么走 / 测地线怎么弯」。联络 Γ、曲率 R、梯度 ∇Φ、测地线都是从它导出的。
> 大小 n×n, 独立分量 n(n+1)/2。

## 本模块的数学口径 (把"标量 M"严格嵌进"度量张量")

度量分解 (尺度 × 形状, 二者可分辨):

    g_ij(x) = M · G_ij(x),      det G(x) = 1,  M > 0

  · **M (标量, 现场标定, 范围 [M_min, M_max])** = 度量的**整体尺度** —— 物理上就是"等效惯量尺度":
    运动方程里 a^k = −Γ^k_ij v^i v^j + g^{kl} F_l, 而各向同性时 Γ = 0 且 g^{kl} = δ^{kl}/M
    ⇒ **a = F/M**, 与旧的标量 M 语义**逐字一致** (零回归)。
  · **G_ij(x) (det = 1)** = 度量的**形状** —— 各向异性方向 + 随状态变化 (这就是原来缺的那一半)。
    Γ^k_ij = ½ g^{kl}(∂_i g_jl + ∂_j g_il − ∂_l g_ij) 对尺度不变 ⇒ **弯曲只由形状决定, 尺度不产生曲率** ——
    这条性质是"能分开标定"的数学依据 (现场先标 M, 再标形状; 形状的效应不被 M 污染)。

## 三种形状参数化 (现场可用 → 复杂)

| mode | G(x) | 独立参数 | 用途 |
|---|---|---|---|
| `isotropic` | I | 0 | 旧行为 (欧氏/直线/Γ=0) —— **默认, 零回归** |
| `diag` | diag(w)/det(w)^{1/n} | n | 每轴不同刚度 (位置 3 轴 / 位姿 6 轴) |
| `full` | L Lᵀ / det(L Lᵀ)^{2/n}, L 下三角 | n(n+1)/2 | 一般度量的**独立分量数** (3→6 · 6→21 · 16→136 · 43→946) |

状态相关 (可选): `G(x) = G_0 + Σ_k x_k · G_k` (每轴灵敏度矩阵 G_k, 由 data/物理导出; 缺省 G_k = 0 ⇒ 常度量)。

## 导出量 (全部数值实现, 无解析近似)
  · 梯度      ∇Φ = g^{-1} ∂Φ        (Cholesky 解, 不显式求逆)
  · 联络      Γ^k_ij = ½ g^{kl}(∂_i g_jl + ∂_j g_il − ∂_l g_ij)   (中心差分)
  · 曲率      R^i_jkl = ∂_k Γ^i_jl − ∂_l Γ^i_jk + Γ^i_km Γ^m_jl − Γ^i_lm Γ^m_jk
              Ric_jl = R^i_jil · 标量曲率 = g^{jl} Ric_jl
  · 测地线    ẍ^k = −Γ^k_ij ẋ^i ẋ^j      (无力 ⇒ 测地线; 有力 ⇒ 加 g^{kl}F_l)
"""
from __future__ import annotations

import os
from typing import Callable

import numpy as np

MODE_ISOTROPIC, MODE_DIAG, MODE_FULL = "isotropic", "diag", "full"
MODES = (MODE_ISOTROPIC, MODE_DIAG, MODE_FULL)


def independent_components(n: int) -> int:
    """对称 n×n 的**独立分量数** = n(n+1)/2 (3→6 · 6→21 · 16→136 · 43→946)。"""
    n = int(n)
    return n * (n + 1) // 2


def _chol_ok(G: np.ndarray) -> bool:
    try:
        np.linalg.cholesky(G)
        return True
    except np.linalg.LinAlgError:
        return False


def _normalize_det(G: np.ndarray) -> np.ndarray:
    """把形状矩阵归一到 det = 1 (尺度全部交给标量 M ⇒ 尺度/形状可分辨)。"""
    G = (G + G.T) / 2.0
    n = G.shape[0]
    d = float(np.linalg.det(G))
    if d <= 1e-300:                        # 非正定 ⇒ 用特征值夹正 (如实可用, 但会被 is_positive_definite 标出)
        w, V = np.linalg.eigh(G)
        w = np.clip(w, 1e-9, None)
        G = V @ np.diag(w) @ V.T
        d = float(np.linalg.det(G))
    return G / (abs(d) ** (1.0 / n))


def shape_from_components(n: int, comps: list | np.ndarray | None) -> np.ndarray:
    """独立分量 (n(n+1)/2 个, 行优先上三角) → 形状矩阵 G (det 归一化, 正定)。"""
    n = int(n)
    k = independent_components(n)
    v = np.asarray(list(comps) if comps is not None else [], dtype=float).ravel()
    if v.size < k:
        v = np.concatenate([v, np.ones(k - v.size)])
    v = v[:k]
    L = np.zeros((n, n), dtype=float)
    it = iter(v)
    for i in range(n):
        for j in range(i + 1):
            L[i, j] = next(it)
    G = L @ L.T                            # 必正定 (Cholesky 反用)
    return _normalize_det(G)


def shape_from_diag(n: int, w: list | np.ndarray | None) -> np.ndarray:
    n = int(n)
    w = np.asarray(list(w) if w is not None else [], dtype=float).ravel()
    if w.size < n:
        w = np.concatenate([w, np.ones(n - w.size)])
    w = np.clip(w[:n], 1e-9, None)
    return _normalize_det(np.diag(w))


def raw_shape_positive_definite(dim: int, mode: str = MODE_ISOTROPIC, diag=None, comps=None) -> tuple[bool, float]:
    """**归一化前**的原始形状是否严格正定 (det > 0 且 min eig > 0) —— 写盘闸门。

    为什么查原始形状: `_normalize_det` 会把奇异/半正定矩阵夹正 (为了引擎可用), 于是"归一化后"永远正定,
    闸门就失效了 ⇒ 拒写判据必须落在原始参数上 (例: diag 里有负数、或独立分量给出的 L 奇异 ⇒ det=0)。
    """
    n = int(dim)
    if mode == MODE_DIAG:
        w = np.asarray(list(diag) if diag is not None else [], dtype=float).ravel()
        G = np.diag(np.concatenate([w, np.ones(max(0, n - w.size))])[:n]) if w.size else np.eye(n)
    elif mode == MODE_FULL:
        k = independent_components(n)
        v = np.asarray(list(comps) if comps is not None else [], dtype=float).ravel()
        v = np.concatenate([v, np.ones(max(0, k - v.size))])[:k]
        L = np.zeros((n, n))
        it = iter(v)
        for i in range(n):
            for j in range(i + 1):
                L[i, j] = next(it)
        G = L @ L.T
    else:
        G = np.eye(n)
    w = np.linalg.eigvalsh((G + G.T) / 2.0)
    d = float(np.linalg.det(G))
    return bool(w.min() > 0.0 and d > 1e-12), float(w.min())


class MetricField:
    """随状态变化的度量场 g_ij(x) = M · G_ij(x) — 流形引擎的主参数。"""

    def __init__(self, dim: int = 3, scale: float = 1.0, mode: str = MODE_ISOTROPIC,
                 diag: list | np.ndarray | None = None, comps: list | np.ndarray | None = None,
                 gain: list | np.ndarray | None = None, h: float = 1e-5):
        self.dim = int(dim)
        self.mode = mode if mode in MODES else MODE_ISOTROPIC
        self.scale = float(scale) if float(scale) > 0 else 1.0
        self.h = float(h)
        n = self.dim
        if self.mode == MODE_DIAG:
            self._G0 = shape_from_diag(n, diag)
        elif self.mode == MODE_FULL:
            self._G0 = shape_from_components(n, comps)
        else:
            self._G0 = np.eye(n)
        # 状态灵敏度 G_k (可选, shape (n, n, n) — 每轴一张对称矩阵); 缺省 = 常度量
        self._gain = None
        if gain is not None:
            g = np.asarray(gain, dtype=float)
            if g.shape == (n, n, n):
                self._gain = np.stack([(g[:, :, k] + g[:, :, k].T) / 2.0 for k in range(n)], axis=2)

    # ── 度量与逆 ────────────────────────────────────────────────────────────
    def shape(self, x) -> np.ndarray:
        G = self._G0
        if self._gain is not None:
            x = np.asarray(x, dtype=float).ravel()[: self.dim]
            G = G + np.tensordot(x, self._gain, axes=(0, 2))     # Σ_k x_k G_k
        return G

    def g(self, x) -> np.ndarray:
        """度量张量 g_ij(x) = M · G(x) (对称正定)。"""
        return self.scale * self.shape(x)

    def ginv_mul(self, x, b) -> np.ndarray:
        """g^{-1} b (Cholesky 求解, 不显式求逆)。"""
        g = self.g(x)
        try:
            L = np.linalg.cholesky(g)
            y = np.linalg.solve(L, np.asarray(b, dtype=float))
            return np.linalg.solve(L.T, y)
        except np.linalg.LinAlgError:                       # 非正定: 伪逆兜底 (会被 is_positive_definite 标出)
            return np.linalg.pinv(g) @ np.asarray(b, dtype=float)

    # ── 正定性/尺度 自检 ───────────────────────────────────────────────────
    def is_positive_definite(self, x=None) -> tuple[bool, float, float]:
        g = self.g(np.zeros(self.dim) if x is None else x)
        w = np.linalg.eigvalsh(g)
        return bool(w.min() > 1e-12), float(w.min()), float(np.prod(w))

    def spec(self) -> dict:
        return {"主参数": "度量张量 g_ij(x) = M · G_ij(x)", "dim": self.dim,
                "mode": self.mode, "独立分量数": independent_components(self.dim),
                "尺度 M": self.scale, "形状 det(G)": 1.0, "状态相关": self._gain is not None,
                "测地线": "ẍ = −Γ ẋẋ (无力) / + g⁻¹F (有力)", "单位": "M=等效惯量尺度; G=无量纲形状"}

    # ── 梯度 ───────────────────────────────────────────────────────────────
    def grad(self, x, dphi) -> np.ndarray:
        """∇Φ = g^{-1} ∂Φ —— 同一个场, 度量决定梯度怎么走。"""
        return self.ginv_mul(x, dphi)

    # ── 联络 Γ ─────────────────────────────────────────────────────────────
    def _dg(self, x) -> np.ndarray:
        """∂_m g_ij (中心差分) → 形状 (n, n, n) [i, j, m]。"""
        n, h = self.dim, self.h
        x = np.asarray(x, dtype=float)
        d = np.zeros((n, n, n))
        for m in range(n):
            xp, xm = x.copy(), x.copy()
            xp[m] += h
            xm[m] -= h
            d[:, :, m] = (self.g(xp) - self.g(xm)) / (2 * h)
        return d

    def christoffel(self, x) -> np.ndarray:
        """Γ^k_ij = ½ g^{kl}(∂_i g_jl + ∂_j g_il − ∂_l g_ij) → 形状 (n, n, n) [k, i, j]。"""
        n = self.dim
        dg = self._dg(x)                                                   # [i, j, m]
        G = np.array([self.ginv_mul(x, np.eye(n)[k]) for k in range(n)]).T   # g^{-1}: 列 k = g^{-1} e_k
        Gam = np.zeros((n, n, n))
        for k in range(n):
            for i in range(n):
                for j in range(n):
                    s = 0.0
                    for l in range(n):
                        s += G[k, l] * (dg[j, l, i] + dg[i, l, j] - dg[i, j, l])
                    Gam[k, i, j] = 0.5 * s
        return Gam

    # ── 曲率 ───────────────────────────────────────────────────────────────
    def riemann(self, x) -> np.ndarray:
        """R^i_jkl (数值, O(n^5) 差分) → 形状 (n, n, n, n) [i, j, k, l]。"""
        n, h = self.dim, max(self.h, 1e-4)
        x = np.asarray(x, dtype=float)
        dGam = np.zeros((n, n, n, n))                       # [m, k, i, j] = ∂_m Γ^k_ij
        for m in range(n):
            xp, xm = x.copy(), x.copy()
            xp[m] += h
            xm[m] -= h
            dGam[m] = (self.christoffel(xp) - self.christoffel(xm)) / (2 * h)
        G = self.christoffel(x)
        R = np.zeros((n, n, n, n))
        for i in range(n):
            for j in range(n):
                for k in range(n):
                    for l in range(n):
                        s = dGam[k, i, j, l] - dGam[l, i, j, k]          # ∂_k Γ^i_jl − ∂_l Γ^i_jk
                        for m in range(n):
                            s += G[i, k, m] * G[m, j, l] - G[i, l, m] * G[m, j, k]
                        R[i, j, k, l] = float(s)
        return R

    def curvature_report(self, x=None, max_dim: int = 8) -> dict:
        """曲率报告 (大维度如实降级: 抽样 3 维子空间, 不假装算全张量)。"""
        n = self.dim
        x = np.zeros(n) if x is None else np.asarray(x, dtype=float)
        if n > max_dim:
            idx = list(range(min(3, n)))
            sub = MetricField(3, self.scale, MODE_FULL,
                              comps=[self.shape(x)[i, j] for i in idx for j in idx if i <= j])
            R = sub.riemann(np.zeros(3))
            return {"full_tensor": False, "why": "n=%d > %d: 只报 3 维子空间抽样 (O(n^5) 差分不假装全量)" % (n, max_dim),
                    "subspace": idx, "‖R‖_F": float(np.linalg.norm(R))}
        Gam = self.christoffel(x)
        R = self.riemann(x)
        # Ric_jl = R^i_jil, 标量曲率 = g^{jl} Ric_jl
        Ric = np.zeros((n, n))                                    # Ric_jl = R^i_jil
        for j in range(n):
            for l in range(n):
                Ric[j, l] = sum(R[i, j, i, l] for i in range(n))
        sc = float(np.trace(self.ginv_mul(x, Ric)))
        return {"full_tensor": True, "‖Γ‖_F": float(np.linalg.norm(Gam)), "‖R‖_F": float(np.linalg.norm(R)),
                "Ric_scalar": sc, "Γ=0 ⇒ 平直": bool(np.linalg.norm(Gam) < 1e-9)}

    # ── 测地线 / 运动 ──────────────────────────────────────────────────────
    def accel(self, x, v, force=None) -> np.ndarray:
        """a^k = −Γ^k_ij v^i v^j + g^{kl} F_l  (无力 ⇒ 纯测地线; 各向同性 ⇒ a = F/M)。"""
        v = np.asarray(v, dtype=float)
        Gam = self.christoffel(x)
        a = -np.einsum("kij,i,j->k", Gam, v, v)
        if force is not None:
            a = a + self.ginv_mul(x, np.asarray(force, dtype=float))
        return a

    def geodesic_step(self, x, v, dt: float, force=None) -> tuple[np.ndarray, np.ndarray]:
        """半步辛积分 (先半推位置, 再更新速度, 再半推位置) —— 二阶精度, 保测地线动能。"""
        x = np.asarray(x, dtype=float)
        v = np.asarray(v, dtype=float)
        a = self.accel(x, v, force)
        x2 = x + v * (dt / 2)
        v2 = v + a * dt
        x2 = x2 + v2 * (dt / 2)
        return x2, v2

    def geodesic_curve(self, x0, v0, steps: int = 20, dt: float = 0.05, force=None) -> np.ndarray:
        x, v = np.asarray(x0, dtype=float), np.asarray(v0, dtype=float)
        out = [x.copy()]
        for _ in range(int(steps)):
            x, v = self.geodesic_step(x, v, dt, force)
            out.append(x.copy())
        return np.array(out)

    def geodesic_residual(self, x, v, a) -> float:
        """测地线方程残差 ‖a + Γ v v − g⁻¹F‖ (判据用; ≈0 ⇒ 积分确实在测地线上)。"""
        Gam = self.christoffel(x)
        lhs = np.asarray(a, dtype=float) + np.einsum("kij,i,j->k", Gam, np.asarray(v, dtype=float), np.asarray(v, dtype=float))
        return float(np.linalg.norm(lhs))

    # ── 配置 (真源 config/calib/zmax_manifold.json 的 metric 段) ─────────────
    @classmethod
    def from_config(cls, cfg: dict | None = None, path: str | None = None) -> "MetricField":
        cfg = cfg if isinstance(cfg, dict) else _load_manifold_cfg(path)
        m = cfg.get("metric") or {}
        return cls(dim=int(m.get("dim", 3)), scale=float(cfg.get("M", 1.0)),
                   mode=str(m.get("mode", MODE_ISOTROPIC)), diag=m.get("diag"), comps=m.get("components"),
                   gain=m.get("gain"))


def _load_manifold_cfg(path: str | None = None) -> dict:
    import json
    p = path or os.path.join(os.path.expanduser("~"), "zmax", "config", "calib", "zmax_manifold.json")
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                           # noqa: BLE001
        return {}


def analytic_check_g22(fun_h: Callable[[float], float], x1: float) -> dict:
    """解析对照 (判据用): 2D 度量 g = diag(1, h(x¹))。

    Γ^2_12 = Γ^2_21 = h'(x¹) / (2 h(x¹)), 其余 Γ = 0  (g_11 = 1 常数 ⇒ 关于 x¹ 的导数只剩这一项)
    """
    h = float(fun_h(x1))
    d = (float(fun_h(x1 + 1e-6)) - float(fun_h(x1 - 1e-6))) / 2e-6
    return {"Gamma^2_12": d / (2 * h), "h": h, "h'": d}
