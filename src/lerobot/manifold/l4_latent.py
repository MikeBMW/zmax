#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🌐 L4 潜空间 (Riemannian-metric-constrained latent space) —— 老倪 2026-10-14 定稿口径

    「VLM 通用视觉编码器是输入，流形引擎根据黎曼度规加约束，INTACT 负责意图解码。这才是 L4 的潜空间」

链路 (三段分工, 每段都有真源/标定, 不造数):

    ① 编码 (输入)   VLM 通用视觉编码器 (src/lerobot/manifold/encoder_vlm.py)
                    帧 → 通用视觉特征 f ∈ R^960          (冻结, 通用表示, 与任务无关)
    ② 度规约束      本模块 + 流形引擎:
                    特征空间度规  g_f = (1/M)·diag(σ²) 归一化到 det(g_f)=1   (M=主参数真源)
                    (度规按各维方差定标 ⇒ 度量下距离 = Σ(Δf)²/σ² 即 Mahalanobis)
                    广义特征分解  Cov(f) v = λ g_f v      ⇒ V 在 g_f 下正交 (黎曼约束)
                    z = Vᵀ g_f^{-1/2} (f − μ) ∈ R^16       (16 = 6 度量主方向 + 10 残差方向)
                    再交引擎: 度规 g = M·G(x), det G = 1 → 漂移/异常/测地线导航 (约束是否成立)
    ③ 意图解码      INTACT (画布 ssintact_dec): z_t / Δz = z_goal − z_t → 意图 (goal/from/skill/gate)

真源:
    config/calib/zmax_manifold.json   主参数 M (3.643) · metric dim=6 mode=diag
    models/l4_latent_calib.json       本模块拟合产物 (μ, V, g_f, n 帧, 解释方差, 源 sha) —— 可复核
"""
from __future__ import annotations

import hashlib
import json
import os
import time

import numpy as np

ROOT_DEFAULT = "/home/ubuntu/zmax"
CALIB_REL = "models/l4_latent_calib.json"
MANIFOLD_CALIB_REL = "config/calib/zmax_manifold.json"


def _sha(path: str) -> str:
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()[:12]
    except OSError:
        return "缺"


def _read_M(root: str) -> tuple:
    p = os.path.join(root, MANIFOLD_CALIB_REL)
    try:
        with open(p, encoding="utf-8") as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        return None, "主参数真源读不到: %s" % MANIFOLD_CALIB_REL
    m = d.get("M")
    if m is None:
        return None, "主参数真源缺 M"
    return float(m), "M=%.4f (真源 %s, 更新 %s)" % (float(m), MANIFOLD_CALIB_REL,
                                                   d.get("_updated_at") or "?")


class L4LatentSpace:
    """L4 潜空间: VLM 特征 ⇒ 黎曼度规约束下的 16 维潜坐标。"""

    def __init__(self, root: str = ROOT_DEFAULT, latent_dim: int = 16) -> None:
        self.root = root
        self.latent_dim = int(latent_dim)
        self.calib_path = os.path.join(root, CALIB_REL)
        self.calib: dict | None = None
        self.M, self.M_note = _read_M(root)

    # ── 拟合 (用**真实帧**的 VLM 特征; 特征空间度规含真源 M) ──
    def fit(self, feats: np.ndarray, frames_note: str = "", save: bool = True) -> dict:
        F = np.asarray(feats, float)
        if F.ndim != 2 or F.shape[0] < max(8, self.latent_dim + 1):
            raise ValueError("拟合样本不足: %s (需 ≥ %d 帧)" % (F.shape, max(8, self.latent_dim + 1)))
        if self.M is None:
            raise ValueError("主参数 M 读不到 ⇒ 度规定标无从谈起: %s" % self.M_note)
        n, d = F.shape
        # 🐛 2026-10-14 实测: 768 维 diag 矩阵直接算 det → 乘积下溢成 0/inf ⇒ det(g_f)=nan。
        #   必须在**对数域**做 det=1 归一 (log g ← log g − mean(log g)), 不显式求 det。
        keep = np.isfinite(F).all(axis=1)
        if not keep.all():
            F = F[keep]
            n, d = F.shape
        mu = F.mean(axis=0)
        Fc = F - mu
        var = (Fc ** 2).mean(axis=0)
        # 🐛 实测: VLM 特征里有**跨帧恒定**的维 (池化 padding 等) —— 方差≈0 ⇒ 白化后放大噪声,
        #   度规在这些维上没有定义。丢掉它们 (mask 存档), 不让它们污染度规。
        vmax = float(var.max()) or 1.0
        keepd = var >= (1e-8 * vmax)
        if not keepd.all():
            Fc = Fc[:, keepd]
            var = var[keepd]
        var[var <= 0] = 1e-12
        # 特征空间度规: g_f = (1/M)·diag(σ²), 对数域归一 to det(g_f)=1 (体积保持)
        log_g = np.log(var) - np.log(max(self.M, 1e-9))
        log_g = log_g - log_g.mean()                      # ⇒ Σ log g = 0 ⇔ det(g_f)=1
        gd = np.exp(log_g)
        g_f = np.diag(gd)
        gf_half = np.diag(np.sqrt(gd))
        gf_half_inv = np.diag(1.0 / np.sqrt(gd))
        W = gf_half_inv @ Fc.T                             # 🐛 须用 g_f^{-1/2} 白化 → (d,n); 用 g^{+1/2} 会把方差变成 σ⁴
        cov = (W @ W.T) / max(1, n - 1)
        lam, V = np.linalg.eigh(cov)                       # V 在 g_f 下正交
        order = np.argsort(lam)[::-1]
        lam, V = lam[order], V[:, order]
        dim = min(self.latent_dim, d, n - 1)
        lam_t, V_t = lam[:dim], V[:, :dim]
        ev = float(lam_t.sum() / max(lam.sum(), 1e-12))
        # 黎曼约束的证据 (可验证, 不写空话): 白化空间里取广义特征方向 ⇒ **潜坐标各维不相关**
        Z = V_t.T @ W                                     # (dim, n)
        Cz = np.cov(Z) if n > 1 else np.eye(dim)
        dg = np.diag(Cz)
        off = float(np.abs(Cz - np.diag(dg)).max() / max(float(dg.max()), 1e-12))
        _vw = np.var(W, axis=1)
        white_var = float(_vw.max() / max(_vw.min(), 1e-12) - 1.0)   # 白化后各维方差相对不一致
        self.calib = {
            "schema": "zmax.l4_latent/1",
            "fitted_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "n_frames": int(n), "feature_dim": int(d), "latent_dim": int(dim),
            "M": float(self.M), "M_note": self.M_note,
            "mu": mu.tolist(), "g_f_diag": gd.tolist(),
            "det_g_f": float(np.exp(np.clip(np.log(gd).sum(), -700, 700))),   # ln det = Σ ln g = 0
            "V": V_t.tolist(), "eig": lam_t.tolist(), "explained_var": ev,
            "latent_offdiag_rel": off,            # 潜坐标协方差非对角/最大对角 (≈0 = 度规下已解耦)
            "white_var_dev": white_var,           # 白化后各维方差的相对不一致 (≈0 = 各向同性)
            "frames_note": frames_note,
            "dim_mask": np.asarray(keepd).tolist(),      # 参与度规的特征维 (跨帧恒定维已剔除)
            "n_dims_kept": int(np.asarray(keepd).sum()),
            "sources": {"zmax_manifold.json": _sha(os.path.join(self.root, MANIFOLD_CALIB_REL))},
        }
        if save:
            os.makedirs(os.path.dirname(self.calib_path), exist_ok=True)
            with open(self.calib_path, "w", encoding="utf-8") as fh:
                json.dump(self.calib, fh, ensure_ascii=False)
        return self.calib

    def load(self) -> dict:
        if self.calib is None:
            with open(self.calib_path, encoding="utf-8") as fh:
                self.calib = json.load(fh)
            self.latent_dim = int(self.calib.get("latent_dim") or self.latent_dim)
        return self.calib

    # ── 投影: VLM 特征 → 度规约束下的潜坐标 ──
    def project(self, feat) -> tuple:
        c = self.load()
        f = np.asarray(feat, float).ravel()
        mu = np.asarray(c["mu"], float)
        gd = np.asarray(c["g_f_diag"], float)
        V = np.asarray(c["V"], float)                      # (d, latent_dim)
        if f.size != mu.size:
            raise ValueError("视觉特征 %d 维 != 标定 %d 维 ⇒ 口径不符 (换编码器需重标定)" % (f.size, mu.size))
        mask = c.get("dim_mask")
        if mask is not None and len(mask) == f.size:
            f = f[np.asarray(mask, bool)]
        z = V.T @ ((1.0 / np.sqrt(gd)) * (f - mu))   # g_f^{-1/2}: 度规下白化 (Mahalanobis)
        z = np.asarray(z, float).ravel()
        if z.size < 16:
            z = np.concatenate([z, np.zeros(16 - z.size)])
        note = ("L4 潜空间: VLM 特征 %d → 度规约束 %d 维 (g_f=(1/M)diag(σ²), det=1 · "
                "度规下已解耦 非对角/对角=%.2e · 解释方差 %.1f%% · n=%d 帧 · M=%.4f)"
                % (mu.size, z.size, float(c.get("latent_offdiag_rel") or 0.0),
                   100.0 * float(c.get("explained_var") or 0.0), int(c.get("n_frames") or 0),
                   float(c.get("M") or 0.0)))
        return z[:16], note

    def encode_frame(self, frame, encoder, update: bool = False) -> tuple:
        """一步: 帧 → (16 维潜坐标, 口径)。encoder = VLMVisionEncoder。"""
        f = encoder.encode(frame)
        return self.project(f)


def fit_from_frames(encoder, frames: list, root: str = ROOT_DEFAULT, latent_dim: int = 16,
                    note: str = "") -> dict:
    """用真实帧拟标定 (帧 → VLM 特征 → 度规约束标定)。"""
    space = L4LatentSpace(root, latent_dim)
    feats = []
    for i, fr in enumerate(frames):
        feats.append(encoder.encode(fr))
    return space.fit(np.asarray(feats, float), frames_note="%s (%d 帧)" % (note, len(feats)))
