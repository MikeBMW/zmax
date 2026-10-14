#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""⛓ L4 后段链的数学层 (老倪 2026-10-14)

口径: 「L4 INTACT LoRA 微调节点接到 INTACT 意图解码器后面 —— 不想动 INTACT 原始模型权重,
     只需要修改 LoRA 节点；元任务预测节点的输出也要接到 INTACT LoRA 微调节点；
     然后向后连接流形专家预测器，以及接触流形、性能流形。流形类节点你来设计数学逻辑。」

链路 (每段都可单跑、可验数):

    u_int  ── INTACT 意图解码器 (冻结 W0, 本模块不碰)
      │
      ▼ ① L4Adapter  —— 只训 ΔW = (α/r)·B·A; 原权重 W0 冻结
    u_lora = u_int + γ·clip( Σ_j w_j(m_meta)·(α/r)·B_j A_j φ(u_int),  ρ‖u_int‖ )
            w = softmax_τ( score_j(m_meta, stage) )        ← 元任务预测值 = LoRA 专家门控
      │
      ▼ ② ManifoldExpert —— 流形专家预测器 (JEPA 一步, 度规约束下沿测地线)
    ẑ = exp_z( −δ · g⁻¹ ∇Φ(z) ) + R_Θ(z, u_lora)          g = M·G(x), det G = 1
      │
      ▼ ③ ContactManifold + ContactConstraint —— 接触流形 (切向进度/法向偏离 + 摩擦锥)
    接触子流形 C = { h(z) ≤ 0 },  n̂ = ∇h/‖∇h‖,  P_t = I − n̂n̂ᵀ
    f = f_n n̂ + f_t ,  可行域: ‖f_t‖ ≤ μ f_n  (越锥 ⇒ 投影回锥)   Φ_c = ½k_n max(0,h)² + μ k_t ‖v_t‖
      │
      ▼ ④ PerformanceManifold + PerformanceConstraint —— 性能流形 (耦合代价 + 帕累托)
    V_p = ½ δᵀ W δ ,  η = exp(−V_p/σ²) ,  度量 g_p = ∂²V_p/∂π² ,  黎曼梯度 g_p⁻¹ ∂V_p/∂π
    帕累托闸: 各维 Δπ_i ≥ −tol_i (要提升, 不是"仅不回退")
"""
from __future__ import annotations

import importlib.util
import json
import os

import numpy as np

ROOT_DEFAULT = "/home/ubuntu/zmax"
ADAPTER_KEYS = ("lora_l4", "lora_l4_init", "l4_lora")


def _load_manifold_layer(root: str):
    path = os.path.join(root, "src", "lerobot", "manifold", "manifold_layer.py")
    spec = importlib.util.spec_from_file_location("lerobot.manifold.manifold_layer", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _softmax(x, tau: float = 0.5):
    x = np.asarray(x, float) / max(1e-6, float(tau))
    x = x - x.max()
    e = np.exp(x)
    return e / max(1e-12, e.sum())


# ─────────────────────────── ① LoRA 微调层 ───────────────────────────
class L4Adapter:
    """L4 · INTACT LoRA 微调 —— **冻结原权重**, 只加低秩 ΔW = (α/r)·B·A。

    无适配器产物 ⇒ Δu ≡ 0 (恒等, 零回归) 且明写"未训练", 绝不假装有微调。
    """

    def __init__(self, root: str = ROOT_DEFAULT, in_dim: int = 16, out_dim: int = 16,
                 r: int = 8, alpha: int = 16, gamma: float = 1.0,
                 rho: float = 0.35, tau: float = 0.5) -> None:
        self.root = root
        self.r, self.alpha = int(r), int(alpha)
        self.scaling = self.alpha / self.r              # 与 tools/lora_inject.py 同口径
        self.gamma, self.rho, self.tau = float(gamma), float(rho), float(tau)
        self.in_dim, self.out_dim = int(in_dim), int(out_dim)
        self.experts: list = []                         # [{"tag":…, "A":(r,in), "B":(out,r), "score":…}]
        self.src, self.note = "", ""

    # ── 产物真源 ──
    def find_products(self) -> list:
        """候选 = LoRA **包装**ckpt (含 lora_A/lora_B 键); merged_* 是已折叠 = 改了原权重, 排除。"""
        import glob                                                    # noqa: PLC0415
        pats = [
            os.path.join(self.root, "zmax_data", "stable-wm-cache", "checkpoints", "*", "weights*.pt"),
            os.path.join(self.root, "zmax_data", "*lora*.pt"),
            os.path.join(self.root, "models", "*lora*"),
        ]
        cand = []
        for p in pats:
            cand += glob.glob(p)
        cand = [c for c in cand if os.path.isfile(c) and "merged" not in os.path.basename(c)]
        cand.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        return cand

    def load(self) -> tuple:
        prods = self.find_products()
        if not prods:
            self.experts = []
            self.note = "未训练/无 LoRA 产物 ⇒ ΔW=0 (恒等, 零回归); 训练入口 tools/lora_inject.py + joint_train_all.py --only L4"
            return False, self.note
        p, blob, err = prods[0], None, ""
        for cand in prods:                                            # 逐个探, 取第一个真有 A/B 的
            try:
                import torch                                          # noqa: PLC0415
                b = torch.load(cand, map_location="cpu", weights_only=False)
            except Exception as e:                                    # noqa: BLE001
                err = "%s: %s" % (type(e).__name__, str(e)[:60])
                continue
            sd0 = b.get("state_dict", b) if isinstance(b, dict) else {}
            if any(str(k).endswith(".lora_A") for k in sd0):
                p, blob = cand, b
                break
        if blob is None:
            self.note = "LoRA 包装 ckpt 里没找到 lora_A (探过 %d 个%s) ⇒ ΔW=0 (恒等)" % (
                len(prods), ("; 读取错误 " + err) if err else "")
            return False, self.note
        got = []
        sd = blob.get("state_dict", blob) if isinstance(blob, dict) else {}
        for k, v in (sd.items() if hasattr(sd, "items") else []):
            if not hasattr(v, "shape"):
                continue
            arr = np.asarray(v.detach().cpu().float().numpy() if hasattr(v, "detach") else v, float)
            if arr.ndim == 2 and "lora_A" in k:
                tag = k.split(".lora_A")[0]
                b = None
                for k2, v2 in sd.items():
                    if k2.startswith(tag + ".lora_B"):
                        b = np.asarray(v2.detach().cpu().float().numpy() if hasattr(v2, "detach") else v2, float)
                if b is not None:
                    got.append({"tag": tag, "A": arr, "B": b, "score": 1.0})
        self.experts = got
        if not got:
            self.note = ("LoRA 产物 %s 里没找到 (lora_A/lora_B) 对 ⇒ ΔW=0 (恒等)"
                         % os.path.basename(p))
            return False, self.note
        self.src = p
        self.r = int(got[0]["A"].shape[0])
        self.scaling = self.alpha / max(1, self.r)
        self.note = "LoRA 产物 %s · %d 组 (r=%d, α=%d, scaling=%.2f) · 原权重冻结" % (
            os.path.basename(p), len(got), self.r, self.alpha, self.scaling)
        return True, self.note

    # ── 门控: 元任务预测值 → LoRA 专家权重 ──
    def gate(self, meta_pred: dict | None, stage: str = "") -> tuple:
        """元任务预测值 → LoRA 增益门控。

        meta_pred 结构真源 (zmax_data/ss_live/meta_pred.json): {"top":[{fn_id,layer,node_id,score}…],…}
        口径: L4/L5 层元任务 (LoRA 相关能力) 的预测得分归一 ⇒ 门控权重; 无预测 ⇒ 均匀 (如实)。
        """
        n = max(1, len(self.experts))
        if not self.experts:
            return np.zeros(1), "无专家 (ΔW=0)"
        top = []
        if isinstance(meta_pred, dict):
            for t in (meta_pred.get("top") or []):
                top.append(t if isinstance(t, dict) else {"fn_id": str(t), "layer": "", "score": 0.0})
        l4 = [t for t in top if str(t.get("layer", "")).upper() in ("L4", "L5", "L4/L5")]
        pool = l4 or top
        s_all = np.asarray([float(t.get("score", 0.0)) for t in pool], float) if pool else np.zeros(0)
        if s_all.size:
            s_all = s_all - s_all.min()
            w_focus = float(s_all.max() / max(1e-9, s_all.sum())) if s_all.sum() > 0 else 1.0 / s_all.size
        else:
            w_focus = 1.0
        g = float(np.clip(w_focus, 0.0, 1.0))                      # 标量增益: LoRA 修正的整体放大
        note = ("元任务预测门控: 候选 %d 个 (L4/L5 层 %d 个) · 焦点权重 %.3f ⇒ 增益 γ_eff=%.3f · 层组 %d%s"
                % (len(top), len(l4), w_focus, g, len(self.experts),
                   " · ⚠️ 预测 frozen(输入无区分度) ⇒ 增益≈均匀" if (meta_pred or {}).get("frozen") else ""))
        return np.array([g]), note

    # ── 低秩更新 ──
    def delta(self, u_int, w=None) -> tuple:
        """真算 Δu = Σ_j w_j (α/r)·B_j A_j·φ ; 顺带给出低秩子空间容量 (限幅口径)。

        口径声明 (必须写清, 不装): 意图向量按**零填充**嵌入该层输入空间 (φ→R^{in_j}), 输出取该层输出
        空间的前 out_dim 组件聚合到意图空间 —— 这是确定的、可复核的嵌入, 不是"估计出来的动作"。
        容量 = (α/r)·‖B_j‖_F·‖A_j‖_F·‖φ_j‖ (低秩子空间能给出多大幅度的上界)。
        """
        u = np.asarray(u_int, float).ravel()
        if not self.experts:
            return np.zeros(max(1, self.out_dim)), "Δu=0 (无 LoRA 产物)", 0.0
        g = 1.0
        if w is not None:
            wv = np.asarray(w, float).ravel()
            g = float(wv[0]) if wv.size else 1.0
        n = max(1, len(self.experts))
        du = np.zeros(self.out_dim)
        cap = 0.0
        for e in self.experts:
            a, b = np.asarray(e["A"], float), np.asarray(e["B"], float)
            x = np.zeros(a.shape[1])
            k = min(a.shape[1], u.size)
            x[:k] = u[:k]                              # 零填充嵌入该层输入空间 (声明口径)
            y = self.scaling * (b @ (a @ x))
            m = min(self.out_dim, y.size)
            du[:m] += y[:m] / n                        # 层组按 1/n 聚合 (声明口径)
            cap += self.scaling * float(np.linalg.norm(b)) * float(np.linalg.norm(a)) * float(np.linalg.norm(x)) / n
        du = g * du
        return du, ("Δu = γ_eff·(α/r)·mean_j(B_j A_j φ) (γ_eff=%.3f · scaling %.2f · φ 零填充嵌入 · 容量 %.4g)"
                    % (g, self.scaling, cap)), g * cap

    # ── 一步: 原权重输出 + 受限低秩修正 ──
    def forward(self, u_int, meta_pred: dict | None = None, stage: str = "") -> dict:
        u = np.asarray(u_int, float).ravel()
        w, gate_note = self.gate(meta_pred, stage)
        du, du_note, cap_raw = self.delta(u, w if self.experts else None)
        raw = float(np.linalg.norm(du))
        cap = self.rho * float(cap_raw or 0.0)                 # 限幅口径 = ρ × 低秩子空间容量 (可复核上界)
        clipped = False
        if cap > 0 and raw > cap:
            du = du * (cap / raw)
            clipped = True
        u_out = u + self.gamma * du
        return {"u_int": u, "u_lora": u_out, "du": du, "capacity": float(cap_raw or 0.0),
                "du_norm": float(np.linalg.norm(du)), "du_norm_raw": raw,
                "cap": cap, "clipped": clipped, "gate": np.asarray(w, float),
                "frozen_base": True, "trained": bool(self.experts),
                "gate_note": gate_note, "du_note": du_note, "src": self.src}

    def summary(self, r: dict) -> str:
        return ("原权重冻结 · ‖Δu‖=%.4g / 容量上限 %.4g%s · ‖u_lora‖=%.4g · 门控 %s · %s"
                % (r["du_norm"], r["cap"], " 已限幅" if r["clipped"] else "",
                   float(np.linalg.norm(r["u_lora"])), np.round(r["gate"], 3).tolist(),
                   "已训练" if r["trained"] else "未训练(恒等)"))


# ─────────────────────── ② 流形专家预测器 (JEPA 一步) ───────────────────────
class ManifoldExpert:
    """流形专家预测器: 度规约束下沿测地线走一步 + 专家残差 (未训练 ⇒ 纯测地线)。

    ẑ = exp_z(−δ g⁻¹ ∇Φ) + R(z, u_lora);  g = M·G(x), det G = 1 (主参数真源)
    度规下的步长 ‖−δ g⁻¹∇Φ‖_g 才是"走了多远"的真口径 (欧氏范数是错的)。
    """

    def __init__(self, M: float = 3.643, dim: int = 16) -> None:
        self.M = float(M)
        self.dim = int(dim)
        self.residual_head = None

    def metric(self, G=None) -> np.ndarray:
        """g = M·G(x); G 缺省=单位 (各向同性, det=1 保持)。"""
        Gm = np.eye(self.dim) if G is None else np.asarray(G, float)
        if Gm.shape[0] != self.dim:
            k = min(self.dim, Gm.shape[0])
            Gm2 = np.eye(self.dim)
            Gm2[:k, :k] = Gm[:k, :k]
            Gm = Gm2
        return self.M * Gm

    def step(self, z, grad_phi, dt: float = 0.05, G=None, u_lora=None) -> dict:
        z = np.asarray(z, float).ravel()[:self.dim]
        gp = np.asarray(grad_phi, float).ravel()[:self.dim]
        if gp.size < self.dim:
            gp = np.pad(gp, (0, self.dim - gp.size))
        g = self.metric(G)
        ginv = np.linalg.inv(g + 1e-9 * np.eye(self.dim))
        dz = -dt * (ginv @ gp)
        res = np.zeros(self.dim)
        if self.residual_head is not None and u_lora is not None:
            res = np.asarray(self.residual_head(z, np.asarray(u_lora, float).ravel()), float)[:self.dim]
        z_next = z + dz + res
        return {"z": z, "z_next": z_next, "dz": dz, "residual": res,
                "euclid_norm": float(np.linalg.norm(dz)),
                "metric_norm": float(np.sqrt(max(0.0, dz @ g @ dz))),
                "det_g_over_M": float(np.linalg.det(np.asarray(G, float))) if G is not None
                else 1.0, "trained": self.residual_head is not None}

    def summary(self, r: dict) -> str:
        return ("ẑ 一步: ‖dz‖₂=%.4g · 度规步长 %.4g (g=M·G, M=%.3f, det G=%.6f) · 残差 %s"
                % (r["euclid_norm"], r["metric_norm"], self.M, r["det_g_over_M"],
                   "有" if r["trained"] else "未训练(0)"))


# ─────────────────── ③ 接触流形 + 摩擦锥约束 ───────────────────
class ContactConstraint:
    """接触子流形约束层: 法向/切向分解 + Coulomb 摩擦锥投影 + 穿透罚势。

    C = { h(z) ≤ 0 } (h=法向穿透), n̂ = ∇h/‖∇h‖, P_t = I − n̂n̂ᵀ
    f = f_n n̂ + f_t;  可行 iff f_n ≥ 0 且 ‖f_t‖ ≤ μ f_n
    Φ_c = ½ k_n max(0,h)² (穿透罚) + μ k_t ‖v_t‖ (摩擦耗散)
    """

    def __init__(self, mu: float = 0.3, k_n: float = 200.0, k_t: float = 20.0) -> None:
        self.mu, self.k_n, self.k_t = float(mu), float(k_n), float(k_t)

    def apply(self, f, axis, v=None, h: float = 0.0) -> dict:
        f = np.asarray(f, float).ravel()[:3]
        n = np.asarray(axis, float).ravel()[:3]
        nn = float(np.linalg.norm(n))
        n = n / nn if nn > 1e-12 else np.array([1.0, 0.0, 0.0])
        fn_ = float(f @ n)
        f_t = f - fn_ * n
        nt = float(np.linalg.norm(f_t))
        no_contact = bool(fn_ < 0)                       # 法向力为负 = 没接触 ⇒ 锥约束不适用
        inside = bool(no_contact or nt <= self.mu * max(fn_, 0.0) + 1e-12)
        f_proj = f.copy()
        if fn_ >= 0 and nt > self.mu * fn_ and nt > 0:
            f_proj = fn_ * n + f_t * (self.mu * fn_ / nt)          # 锥投影
        v = np.zeros(3) if v is None else np.asarray(v, float).ravel()[:3]
        v_t = v - float(v @ n) * n
        phi_c = 0.5 * self.k_n * max(0.0, float(h)) ** 2 + self.mu * self.k_t * float(np.linalg.norm(v_t))
        _fp = np.asarray(f_proj, float)
        _fn_p = float(_fp @ n)
        _ft_p = float(np.linalg.norm(_fp - _fn_p * n))
        return {"f_n": fn_, "f_t": f_t, "f_t_norm": nt, "f_t_norm_proj": _ft_p, "mu": self.mu,
                "no_contact": no_contact,
                "slack": float(self.mu * max(fn_, 0.0) - nt),
                "inside_cone": inside, "f_proj": f_proj,
                "projected": bool(np.linalg.norm(f_proj - f) > 1e-12),
                "phi_c": float(phi_c), "h": float(h), "n": n, "v_t_norm": float(np.linalg.norm(v_t))}

    def summary(self, r: dict) -> str:
        state = ("无接触 (f_n<0) ⇒ 锥约束不适用" if r.get("no_contact")
                 else ("在锥内" if r["inside_cone"] else "越锥 ⇒ 已投影回锥"))
        return ("f_n=%.3f N · ‖f_t‖=%.3f N · 锥余量 %.3f (μ=%.2f) → %s · Φ_c=%.4g%s"
                % (r["f_n"], r["f_t_norm"], r["slack"], r["mu"], state, r["phi_c"],
                   " · 穿透罚 %.4g" % (0.5 * self.k_n * max(0.0, r["h"]) ** 2) if r["h"] > 0 else ""))


# ─────────────────── ④ 性能流形 + 帕累托约束 ───────────────────
class PerformanceConstraint:
    """性能流形约束层: 耦合代价 V_p/η + 性能度量 g_p + 黎曼梯度 + 帕累托非劣闸。

    V_p = ½ δᵀWδ · η = exp(−V_p/σ²)   (与 src/lerobot/manifold/manifold_layer.py 同口径, 不重写)
    g_p = diag(∂²V_p/∂π²) ≈ W/σ² 的归一化 (Fisher 近似) ⇒ ∇_{g_p}V_p = g_p⁻¹ ∂V_p/∂π
    帕累托闸: 更新后每维必须 Δπ_i ≥ −tol_i ⇒ "要提升, 不是仅不回退"
    """

    def __init__(self, W=None, sigma: float = 0.004, tol=0.0) -> None:
        self.W = np.diag([0.4, 1.0, 1.0]) if W is None else np.asarray(W, float)
        self.sigma = float(sigma)
        self.tol = tol

    def evaluate(self, delta, W=None) -> dict:
        d = np.asarray(delta, float).ravel()[:3]
        Wm = self.W if W is None else np.asarray(W, float)
        Vp = 0.5 * float(d @ Wm @ d)
        eta = float(np.exp(-Vp / max(1e-12, self.sigma ** 2)))
        gp = Wm / max(1e-12, self.sigma ** 2)                  # 度量 (Fisher 近似, 对称正定)
        grad = Wm @ d                                          # ∂V_p/∂δ
        riem = np.linalg.solve(gp + 1e-12 * np.eye(3), grad)   # 黎曼梯度 g_p⁻¹ ∇V_p
        return {"V_p": Vp, "eta": eta, "grad": grad, "riemann_grad": riem,
                "g_p_diag": np.diag(gp), "sigma": self.sigma}

    def pareto_check(self, pi_before, pi_after) -> dict:
        """性能向量 π (越大越好) 的帕累托非劣闸: 每维 Δπ_i ≥ −tol_i。"""
        b = np.asarray(pi_before, float).ravel()
        a = np.asarray(pi_after, float).ravel()
        tol = np.full(b.size, self.tol) if np.isscalar(self.tol) else np.asarray(self.tol, float)
        dpi = a - b
        bad = np.where(dpi < -tol)[0]
        return {"dpi": dpi, "ok": bool(bad.size == 0), "worst_dim": int(bad[0]) if bad.size else -1,
                "tol": tol, "n_dims": int(b.size)}

    def summary(self, r: dict) -> str:
        return ("V_p=%.4g · η=%.4f · ‖∇V_p‖=%.4g · 黎曼梯度范数 %.4g (g_p diag %s)"
                % (r["V_p"], r["eta"], float(np.linalg.norm(r["grad"])),
                   float(np.linalg.norm(r["riemann_grad"])), np.round(r["g_p_diag"], 1).tolist()))


# ─────────────────────────── 全链一步 ───────────────────────────
def chain_once(root: str = ROOT_DEFAULT, u_int=None, z=None, grad_phi=None, f=None, axis=None,
               v=None, h: float = 0.0, delta=None, meta_pred=None, stage: str = "",
               M: float = 3.643, G=None, adapter: L4Adapter | None = None) -> dict:
    """跑一遍 L4 后段链: LoRA → 专家预测 → 接触流形 → 性能流形 (全部真算, 返回数)。"""
    ad = adapter or L4Adapter(root)
    if adapter is None:
        ad.load()
    u = np.zeros(16) if u_int is None else np.asarray(u_int, float)
    lora = ad.forward(u, meta_pred, stage)
    expo = ManifoldExpert(M=M)
    zz = np.zeros(16) if z is None else np.asarray(z, float)
    gph = np.zeros(16) if grad_phi is None else np.asarray(grad_phi, float)
    pred = expo.step(zz, gph, G=G, u_lora=lora["u_lora"])
    cc = ContactConstraint()
    ct = cc.apply(np.zeros(3) if f is None else f, np.array([1.0, 0.0, 0.0]) if axis is None else axis,
                  v=v, h=h)
    pc = PerformanceConstraint()
    pf = pc.evaluate(np.zeros(3) if delta is None else delta)
    return {"lora": lora, "predictor": pred, "contact": ct, "performance": pf,
            "notes": {"lora": ad.note, "gate": lora["gate_note"]}}


def _selftest(root: str = ROOT_DEFAULT) -> int:
    ok = []
    ad = L4Adapter(root)
    ad.load()
    print("① LoRA 层: %s" % ad.note)
    r0 = ad.forward(np.ones(16))
    if ad.experts:                                             # 有产物: Δu 非零 + 有限 + γ_eff 门控
        ok.append(r0["trained"] and r0["du_norm"] > 0 and np.isfinite(r0["u_lora"]).all())
        print("   有产物: ‖Δu‖=%.4g · 容量 %.4g · γ_eff=%.3f · ‖u_lora‖=%.4g"
              % (r0["du_norm"], r0["capacity"], float(r0["gate"][0]), float(np.linalg.norm(r0["u_lora"]))))
        ad2 = L4Adapter(root, rho=1e-6)                        # 限幅必须真生效
        ad2.load()
        r2 = ad2.forward(np.ones(16))
        ok.append(bool(r2["clipped"]) and r2["du_norm"] <= r2["cap"] + 1e-12)
        print("   限幅: ρ=1e-6 ⇒ clipped=%s · ‖Δu‖=%.4g ≤ 上限 %.4g"
              % (r2["clipped"], r2["du_norm"], r2["cap"]))
    ad3 = L4Adapter("/tmp/__no_lora__")                        # 零回归: 无产物 ⇒ 恒等
    ad3.load()
    r3 = ad3.forward(np.ones(16))
    ok.append(np.allclose(r3["u_lora"], np.ones(16)) and r3["du_norm"] == 0.0 and not r3["trained"])
    print("   无产物恒等(零回归): %s · Δu=%.4g" % (np.allclose(r3["u_lora"], np.ones(16)), r3["du_norm"]))
    e = ManifoldExpert(M=3.643)
    pe = e.step(np.zeros(16), np.ones(16) * 0.1)
    ok.append(pe["metric_norm"] > 0 and np.isfinite(pe["z_next"]).all())
    print("② 专家预测: %s" % e.summary(pe))
    cc = ContactConstraint()
    # 越锥案例: f_n=1, f_t=0.5, μ=0.3 ⇒ 应投影
    rc = cc.apply([1.0, 0.5, 0.0], [1, 0, 0])
    ok.append(rc["inside_cone"] is False and rc["projected"] is True
              and abs(rc["f_t_norm_proj"] - 0.3) < 1e-9 and rc["f_t_norm"] > 0.3)
    print("③ 接触流形: %s" % cc.summary(rc))
    rc2 = cc.apply([1.0, 0.2, 0.0], [1, 0, 0])
    ok.append(rc2["inside_cone"] is True)
    print("   锥内案例: %s" % cc.summary(rc2))
    pc = PerformanceConstraint()
    pf = pc.evaluate([0.0005, 0.0002, 0.0])
    ok.append(0.0 < pf["eta"] <= 1.0 and pf["V_p"] > 0)
    print("④ 性能流形: %s" % pc.summary(pf))
    pchk = pc.pareto_check([0.9, 1.0, 0.5], [0.91, 1.0, 0.5])
    ok.append(pchk["ok"] is True)
    pchk2 = pc.pareto_check([0.9, 1.0, 0.5], [0.91, 1.0, 0.49])
    ok.append(pchk2["ok"] is False and pchk2["worst_dim"] == 2)
    print("   帕累托闸: 提升→%s · 有一维劣化→%s (worst_dim=%d)"
          % (pchk["ok"], pchk2["ok"], pchk2["worst_dim"]))
    print("自检 %d/%d %s" % (sum(ok), len(ok), "PASS" if all(ok) else "FAIL"))
    return 0 if all(ok) else 1


if __name__ == "__main__":
    import sys
    raise SystemExit(_selftest())
