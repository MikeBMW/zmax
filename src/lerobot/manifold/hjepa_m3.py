#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🔀 hjepa_m3.py — 方案3: 统一多模态 JEPA (双向跨模态, 老倪 2026-10-25)

老倪: 「方案3 你考虑进自主进化」

## 方案1 vs 方案3 的本质区别
方案1 (`hjepa_manifold.GeometricBranch`): **单向** —
    z_vis ──条件──▶ 几何头 ──▶ ξ
    几何只能"读"视觉线索, 反过来不能强引导视觉表征。

方案3 (本模块): **双向, 两个模态平等** —
    z_vis ──▶ e_vis ──▶ ξ_pred          (图像预测几何)
    ξ     ──▶ e_geo ──▶ z_vis_pred      (几何预测图像)
    再让 e_vis 与 e_geo 在**联合嵌入空间**对齐。
    好处: 视觉表征会被刚体运动学约束反向塑形 —— 世界模型推演未来时不会出现不物理的扭曲。

## 🔴 最大的风险不是训得慢, 是**塌缩**
双向对比最经典的失败: 两个 encoder 都输出常数向量, 对比 loss 变得极低,
但嵌入里没有任何信息 (跟"平凡基线"是一类骗局)。所以本模块强制三件事:
  ① L2 归一化 + 温度缩放   —— 保证相似度有界, 不让幅值作弊
  ② **方差正则** (VICReg 式) —— 每个维度标准差必须 ≥ γ, 否则重罚
  ③ **协方差解耦**          —— 维度之间不许冗余, 否则 32 维退化成 1 维复读

被动性一样的纪律: 塌缩是硬闸, 不是加权项。`collapse_score()` 一旦超阈就判这一代作废。

## 和方案1 的关系: 并存, 不替换
    HJEPA_M3_W=0 ⇒ 只用方案1, **零回归** (原几何通道逐位不变)

自检: python3 -m lerobot.manifold.hjepa_m3 --selftest
"""
from __future__ import annotations

import os
import sys

import numpy as np

try:
    from .hjepa_manifold import (MOMENTUM, se3_distance, se3_geodesic_loss,
                                 sphere_geodesic_loss)
except Exception:                                                      # noqa: BLE001
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from hjepa_manifold import (MOMENTUM, se3_distance,                # type: ignore
                                se3_geodesic_loss, sphere_geodesic_loss)

D_E_DEFAULT = 64      # 联合嵌入维度
TAU_DEFAULT = 0.07    # 对比温度
VAR_GAMMA = 0.5       # 每个嵌入维度的最小标准差 (VICReg 式)
COV_LAMBDA = 0.02     # 协方差解耦权重


def _torch():
    import torch
    return torch


def _nn():
    import torch.nn as nn
    return nn


# ═══════════════ 防塌缩三件套 ═══════════════
def variance_regularizer(e, gamma=VAR_GAMMA):
    """VICReg 方差项: 每个维度标准差低于 γ 就罚。

    为什么必须有: 双向对比最省力的作弊解就是把两个 encoder 都训成常数输出,
    对比相似度立刻=1.0, loss 漂亮, 但嵌入里零信息。这一项直接判它负分。
    """
    torch = _torch()
    if e.shape[0] < 2:
        return torch.zeros((), device=e.device)
    std = torch.sqrt(e.var(dim=0) + 1e-8)
    return torch.clamp(gamma - std, min=0.0).mean()


def covariance_regularizer(e, lam=COV_LAMBDA):
    """协方差解耦: 非对角元素压到 0, 防止维度冗余 (32 维退化成 1 维复读)。"""
    torch = _torch()
    n, d = e.shape
    if n < 2 or d < 2:
        return torch.zeros((), device=e.device)
    ec = e - e.mean(dim=0, keepdim=True)
    cov = (ec.T @ ec) / max(n - 1, 1)
    off = cov - torch.diag(torch.diagonal(cov))
    return lam * (off ** 2).sum() / d


def effective_rank(e):
    """有效秩 = exp(奇异值归一化后的熵)。塌缩 ⇒ 1, 满秩 ⇒ d。

    为什么不用"每维标准差 ≥ γ"当主判据:
      VICReg 的 γ=1.0 是给 **2096 维**嵌入定的。这里 d_e 只有 16~64,
      信息天然集中在少数维度, 单维 std 稳态就在 0.22 左右 (实测 120 步和 350 步
      几乎一样, 0.2166 → 0.2263), 拿 0.25 去卡它只会误判。
      有效秩对维度数不敏感 —— 塌缩时秩→1, 有信息时秩→d。
    """
    a = np.asarray(e, float)
    if a.ndim != 2 or a.shape[0] < 2:
        return 0.0
    a = a - a.mean(axis=0, keepdims=True)
    try:
        s = np.linalg.svd(a, compute_uv=False)
    except np.linalg.LinAlgError:
        return 0.0
    s = s[s > 1e-12]
    if s.size == 0:
        return 0.0
    p = s / s.sum()
    ent = float(-(p * np.log(p)).sum())
    return float(np.exp(ent))


def collapse_score(e_vis, e_geo, gamma=VAR_GAMMA):
    """塌缩体检 → dict(std_min, eff_rank, cov_off, collapsed, why)。

    三重判据 (任何一条命中就算塌):
      ① std_min  < 0.10     —— 绝对底线, 防完全常数输出
      ② 有效秩   < max(2, d*0.15) —— 信息维度不能退化成 1~2 维复读
      ③ 协方差非对角 > 0.6  —— 维度之间不许冗余复制
    """
    ev = np.asarray(e_vis, float)
    eg = np.asarray(e_geo, float)
    out = {"std_min_vis": None, "std_min_geo": None,
           "eff_rank_vis": None, "eff_rank_geo": None,
           "cov_off_vis": None, "cov_off_geo": None,
           "collapsed": False, "why": ""}
    if ev.ndim != 2 or eg.ndim != 2 or ev.shape[0] < 3:
        out["why"] = "样本太少无法判塌缩"
        return out
    sv = float(ev.std(axis=0).min())
    sg = float(eg.std(axis=0).min())
    rv = effective_rank(ev)
    rg = effective_rank(eg)
    out["std_min_vis"] = round(sv, 6)
    out["std_min_geo"] = round(sg, 6)
    out["eff_rank_vis"] = round(rv, 3)
    out["eff_rank_geo"] = round(rg, 3)

    def _off(a):
        ac = a - a.mean(axis=0, keepdims=True)
        c = (ac.T @ ac) / max(len(a) - 1, 1)
        d = np.sqrt(np.clip(np.diag(c), 1e-12, None))
        n = c / np.outer(d, d)
        return float(np.abs(n - np.eye(len(n))).sum() / max(len(n) ** 2 - len(n), 1))

    out["cov_off_vis"] = round(_off(ev), 6)
    out["cov_off_geo"] = round(_off(eg), 6)

    d_vis, d_geo = ev.shape[1], eg.shape[1]
    rank_thr_v = max(2.0, d_vis * 0.15)
    rank_thr_g = max(2.0, d_geo * 0.15)
    if sv < 0.10 or sg < 0.10:
        out["collapsed"] = True
        out["why"] = ("嵌入贴常数: std_vis=%.4f std_geo=%.4f 底线 0.10" % (sv, sg))
    elif rv < rank_thr_v or rg < rank_thr_g:
        out["collapsed"] = True
        out["why"] = ("有效秩退化: rank_vis=%.2f(需≥%.1f) rank_geo=%.2f(需≥%.1f)"
                      % (rv, rank_thr_v, rg, rank_thr_g))
    elif max(out["cov_off_vis"], out["cov_off_geo"]) > 0.6:
        out["collapsed"] = True
        out["why"] = ("维度冗余: 协方差非对角 %.3f/%.3f 过高"
                      % (out["cov_off_vis"], out["cov_off_geo"]))
    else:
        out["why"] = "未塌缩 (rank %.1f/%.1f, std %.3f/%.3f)" % (rv, rg, sv, sg)
    return out


# ═══════════════ 双向跨模态 JEPA ═══════════════
def build_m3_jepa(d_vis=256, d_geo=6, d_e=D_E_DEFAULT, n_layers=3,
                  with_uncertainty=False):
    """方案3: 两个平等模态 + 双向预测 + 联合对齐。

    Args:
        d_vis : 视觉潜维度 (原生 H-JEPA 的 z_vis 维数)
        d_geo : 几何切空间维度 (6 = se(3))
        d_e   : 联合嵌入维度
    Returns:
        nn.Module, forward(batch) →
            {
              "e_vis", "e_geo",            # 联合嵌入 (已 L2 归一化)
              "xi_pred",                   # 图像→几何: 切空间 twist
              "z_vis_pred",                # 几何→图像: 重构视觉潜
              "scalars": {…}               # 各损失标量
            }
    """
    torch = _torch()
    nn = _nn()

    class _MLP(nn.Module):
        def __init__(self, din, dhid, dout, nl=2):
            super().__init__()
            layers, d = [], din
            for _ in range(nl):
                layers += [nn.Linear(d, dhid), nn.LayerNorm(dhid), nn.GELU()]
                d = dhid
            self.net = nn.Sequential(*layers, nn.Linear(d, dout))

        def forward(self, x):
            return self.net(x)

    class M3JEPA(nn.Module):
        """视觉 ↔ SE(3) 双向跨模态联合嵌入。

        两个模态**平等**: 各有一个 encoder 投到 d_e 维联合空间,
        然后互相预测对方的原始表征。不是"视觉当条件、几何当附属头"。
        """

        def __init__(self):
            super().__init__()
            # ── 两个平等模态的编码器 ──
            self.vis_enc = _MLP(d_vis, 256, d_e, n_layers)
            self.geo_enc = _MLP(d_geo, 128, d_e, n_layers)
            # ── 双向预测头 ──
            #   图像→几何: 想从视觉推出刚体运动 (这是方案1 也有的方向)
            self.img2geo = _MLP(d_e, 128, d_geo, 2)
            #   几何→图像: **方案3 才有** —— 让视觉表征被运动学反向塑形
            self.geo2img = _MLP(d_e, 256, d_vis, 2)
            # ── 可选不确定性 ──
            self.use_unc = bool(with_uncertainty)
            if self.use_unc:
                self.var_head = _MLP(d_e, 128, d_geo, 2)
                nn.init.constant_(self.var_head.net[-1].bias, -2.0)

        @staticmethod
        def _norm(e):
            return e / e.norm(dim=-1, keepdim=True).clamp_min(1e-8)

        def forward(self, z_vis, xi, tau=TAU_DEFAULT,
                    lam_img2geo=1.0, lam_geo2img=1.0, lam_align=0.25):
            """
            z_vis : (B, d_vis) 视觉潜 —— 来自原生 H-JEPA ViT, **本模块不反传给它**
            xi    : (B, d_geo) 真值切空间 twist (FK/仿真给的 SE(3) 对数)
            """
            e_vis = self._norm(self.vis_enc(z_vis))
            e_geo = self._norm(self.geo_enc(xi))

            xi_pred = self.img2geo(e_vis)
            z_vis_pred = self.geo2img(e_geo)

            # ① 图像→几何: 切空间 L2 (真值已在切空间, 不必 exp 回流形再算测地线)
            l_i2g = (xi_pred - xi).pow(2).mean()
            # ② 几何→图像: 视觉潜回归
            l_g2i = (z_vis_pred - z_vis).pow(2).mean()
            # ③ 联合对齐: **双向 InfoNCE**, 不是 1−cos
            #    🔴 踩过: 初版用 (1−cos).mean() 对齐, 训练后 loss 2.70→0.62 看着很好,
            #    但 std_vis=0.069/std_geo=0.088 (要求≥0.25), cos=0.98 —— **塌了**。
            #    原因: 把所有样本挤到球面同一点, 余弦立刻=1, 是最省力的解。
            #    InfoNCE 里 batch 内其他样本是负样本: 塌缩时对角线不再突出, CE 反而变大
            #    (=log B), 所以天然反塌缩。CLIP 就是这个结构。
            scale = 1.0 / max(float(tau), 1e-6)
            logits_v2g = (e_vis @ e_geo.T) * scale      # (B,B) 图像为锚, 几何为正样本
            logits_g2v = logits_v2g.T
            labels = torch.arange(e_vis.shape[0], device=e_vis.device)
            l_align = 0.5 * (torch.nn.functional.cross_entropy(logits_v2g, labels)
                             + torch.nn.functional.cross_entropy(logits_g2v, labels))
            cos = (e_vis * e_geo).sum(dim=-1)
            # ④ 防塌缩: 方差 + 协方差 (作用在**归一化前**的原始嵌入上才有意义)
            raw_vis = self.vis_enc(z_vis)
            raw_geo = self.geo_enc(xi)
            l_var = variance_regularizer(raw_vis) + variance_regularizer(raw_geo)
            l_cov = covariance_regularizer(raw_vis) + covariance_regularizer(raw_geo)

            # 方差/协方差给 3.0 权重: CE 的量级是 log(B)≈3.4, 权重 1.0 时被压过,
            # 实测照样塌缩。防塌缩项必须和对比项同量级才顶得住。
            total = (lam_img2geo * l_i2g + lam_geo2img * l_g2i
                     + lam_align * l_align + 3.0 * (l_var + l_cov))
            out = {
                "e_vis": e_vis, "e_geo": e_geo,
                "xi_pred": xi_pred, "z_vis_pred": z_vis_pred,
                "loss": total,
                "scalars": {
                    "img2geo": float(l_i2g), "geo2img": float(l_g2i),
                    "align": float(l_align), "var": float(l_var), "cov": float(l_cov),
                    "cos_mean": float(cos.mean()), "tau": float(tau),
                },
            }
            if self.use_unc:
                out["log_sigma"] = self.var_head(e_vis)
            return out

        @torch.no_grad()
        def predict_geometry(self, z_vis):
            """推理: 只走图像→几何 (给下游 g_d 用)。"""
            e_vis = self._norm(self.vis_enc(z_vis))
            return self.img2geo(e_vis)

        @torch.no_grad()
        def embed(self, z_vis=None, xi=None):
            """取联合嵌入 (给塌缩体检/进化适应度用)。"""
            o = {}
            if z_vis is not None:
                o["e_vis"] = self.vis_enc(z_vis).cpu().numpy()
            if xi is not None:
                o["e_geo"] = self.geo_enc(xi).cpu().numpy()
            return o

    return M3JEPA()


# ═══════════════ 自检 ═══════════════
def _selftest() -> int:
    fails = []

    def chk(name, cond, detail=""):
        print(("  [PASS] " if cond else "  [FAIL] ") + name + (("  " + detail) if detail else ""))
        if not cond:
            fails.append(name)

    torch = _torch()
    torch.manual_seed(0)

    print("① 结构与双向输出")
    m3 = build_m3_jepa(d_vis=32, d_geo=6, d_e=16, n_layers=2)
    B = 24
    z_vis = torch.randn(B, 32)
    xi = torch.randn(B, 6) * 0.02
    out = m3(z_vis, xi)
    chk("e_vis 形状", tuple(out["e_vis"].shape) == (B, 16), str(tuple(out["e_vis"].shape)))
    chk("e_geo 形状", tuple(out["e_geo"].shape) == (B, 16))
    chk("xi_pred 6 维 (图像→几何)", tuple(out["xi_pred"].shape) == (B, 6))
    chk("z_vis_pred 32 维 (几何→图像)", tuple(out["z_vis_pred"].shape) == (B, 32))
    chk("嵌入已 L2 归一化",
        bool(torch.allclose(out["e_vis"].norm(dim=-1), torch.ones(B), atol=1e-5)),
        "|e_vis|=%.6f" % float(out["e_vis"].norm(dim=-1).mean()))
    n_par = sum(p.numel() for p in m3.parameters())
    print("     参数量 %d" % n_par)

    print("② 双向 loss 都连通 (梯度能回到两个 encoder)")
    m3.zero_grad()
    o = m3(z_vis, xi)
    o["loss"].backward()
    gv = sum(p.grad.abs().sum().item() for p in m3.vis_enc.parameters() if p.grad is not None)
    gg = sum(p.grad.abs().sum().item() for p in m3.geo_enc.parameters() if p.grad is not None)
    chk("vis_enc 有梯度", gv > 0, "|∇|_sum=%.4f" % gv)
    chk("geo_enc 有梯度", gg > 0, "|∇|_sum=%.4f" % gg)
    gi = sum(p.grad.abs().sum().item() for p in m3.img2geo.parameters() if p.grad is not None)
    gj = sum(p.grad.abs().sum().item() for p in m3.geo2img.parameters() if p.grad is not None)
    chk("img2geo 头有梯度", gi > 0, "%.4f" % gi)
    chk("geo2img 头有梯度", gj > 0, "%.4f" % gj)
    chk("**双向都真反传** (方案3 的核心)", gi > 0 and gj > 0 and gv > 0 and gg > 0)

    print("③ 防塌缩: 方差/协方差正则真的起作用")
    # 人为造塌缩: 常数嵌入
    const = torch.ones(24, 16)
    v = variance_regularizer(const)
    chk("常数嵌入 ⇒ 方差正则很大", float(v) > 0.4, "var_reg=%.4f" % float(v))
    rnd = torch.randn(24, 16)
    v2 = variance_regularizer(rnd)
    chk("随机嵌入 ⇒ 方差正则近 0", float(v2) < 1e-3, "var_reg=%.6f" % float(v2))

    # 冗余嵌入: 16 维全是同一列复制
    red = torch.randn(24, 1).repeat(1, 16)
    c = covariance_regularizer(red)
    chk("完全冗余 ⇒ 协方差正则大", float(c) > 0.01, "cov_reg=%.4f" % float(c))
    c2 = covariance_regularizer(rnd)
    chk("独立维度 ⇒ 协方差正则小", float(c2) < float(c), "%.6f vs %.6f" % (float(c2), float(c)))

    print("④ 塌缩体检")
    ev = np.random.randn(40, 16)
    eg = np.random.randn(40, 16)
    r = collapse_score(ev, eg)
    chk("随机嵌入未判塌缩", r["collapsed"] is False, r["why"])
    r2 = collapse_score(np.ones((40, 16)) * 0.01, np.ones((40, 16)) * 0.01)
    chk("常数嵌入判为塌缩", r2["collapsed"] is True, r2["why"])
    red2 = np.random.randn(40, 1).repeat(16, axis=1)
    r3 = collapse_score(red2, red2)
    chk("冗余嵌入判为塌缩", r3["collapsed"] is True, r3["why"])

    print("⑤ 训练能真降 loss 且不塌缩 (小步验证)")
    torch.manual_seed(1)
    m = build_m3_jepa(d_vis=32, d_geo=6, d_e=16, n_layers=2)
    opt = torch.optim.AdamW(m.parameters(), lr=3e-3)
    # 造一对真有相关性的模态 (xi 是 z_vis 的线性投影 + 噪声) —— 有可学结构
    W = torch.randn(32, 6) * 0.1
    Z = torch.randn(128, 32)
    X = Z @ W + torch.randn(128, 6) * 0.005
    losses = []
    for step in range(350):
        idx = torch.randint(0, 128, (64,))
        o = m(Z[idx], X[idx])
        opt.zero_grad(); o["loss"].backward(); opt.step()
        if step % 70 == 0 or step == 349:
            losses.append(float(o["loss"]))
    print("     loss: %s" % " → ".join("%.4f" % v for v in losses))
    chk("loss 下降", losses[-1] < losses[0], "%.4f → %.4f" % (losses[0], losses[-1]))
    with torch.no_grad():
        o = m(Z, X)
        ev = o["e_vis"].cpu().numpy()
        eg = o["e_geo"].cpu().numpy()
        cos_mean = float(o["scalars"]["cos_mean"])
    cs = collapse_score(ev, eg)
    chk("训练后未塌缩", cs["collapsed"] is False, cs["why"])
    # InfoNCE 下判据要换: 不能看 cos 均值 (塌缩时 cos 也能到 1),
    # 要看**对角优势** pos−neg —— 正样本对相似度比负样本对高出多少。
    with torch.no_grad():
        ev_t = m.vis_enc(Z); eg_t = m.geo_enc(X)
        ev_n = ev_t / ev_t.norm(dim=-1, keepdim=True).clamp_min(1e-8)
        eg_n = eg_t / eg_t.norm(dim=-1, keepdim=True).clamp_min(1e-8)
        S = ev_n @ eg_n.T
        pos = S.diagonal().mean().item()
        offmask = ~torch.eye(S.shape[0], dtype=torch.bool)
        neg = S[offmask].mean().item()
    chk("对角优势 pos−neg > 0.2", (pos - neg) > 0.2,
        "pos=%.4f neg=%.4f 差=%.4f" % (pos, neg, pos - neg))
    print("     std_vis=%.4f std_geo=%.4f pos=%.4f neg=%.4f cos=%.4f"
          % (cs["std_min_vis"], cs["std_min_geo"], pos, neg, cos_mean))

    print("⑥ 推理接口")
    p = m3.predict_geometry(z_vis)
    chk("predict_geometry 出 6 维", tuple(p.shape) == (B, 6))
    e = m3.embed(z_vis=z_vis, xi=xi)
    chk("embed 出两侧", "e_vis" in e and "e_geo" in e,
        "%s / %s" % (e["e_vis"].shape, e["e_geo"].shape))

    print()
    if fails:
        print("❌ %d 项失败: %s" % (len(fails), ", ".join(fails)))
        return 1
    print("✅ 全部通过 (方案3 双向跨模态 JEPA: 双向真反传 + 防塌缩三件套)")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv or len(sys.argv) == 1:
        sys.exit(_selftest())
    print("用法: python3 -m lerobot.manifold.hjepa_m3 --selftest")
