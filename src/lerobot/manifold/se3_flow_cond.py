"""A~E(五流形) + TQ(切空间) → flow-matching 的条件编码 + 流形感知噪声。

老倪 2026-11-19:「A B C D E 6 个几何流形都有了么? 能做成条件编码噪声, 注入到 flow matching 么?」

这条模块只做两件事, 都是**可判据**的:
  ① `encode()`     五流形量 → 20 维条件向量 c (S¹ 用 sin/cos, 不许线性减)
  ② `sample_noise()` 从**当前状态出发**在各自流形上采初始噪声 x0 (切空间高斯 → 指数映射),
                     而不是纯 N(0,I)。这样 t=0 的样本天然落在可行域内,
                     去噪网络只需学"沿测地线的残差", 且 x_t 与真值同分布。
  ③ `interpolate()`  FM 的插值路径**在流形上做**(逐层测地线, 与引擎同一份 `SE3Layered.geodesic`),
                     不在 20 维欧氏里直线插 —— 否则 B/C 两点直线会跑出单位球。

注入点(仓里已有 flow matching, 不用新造头):
  · `src/lerobot/policies/multi_task_dit/modeling_multi_task_dit.py:135`
    `conditioning_vec = self.observation_encoder.encode(batch)` → 把本模块的 c 拼进去 (conditioning_dim +20)
  · `src/lerobot/policies/smolvla/modeling_smolvla.py:812`
    `sample_actions(..., noise=...)` 直接吃本模块的 `sample_noise()` 输出
  · 本仓 L3 节点 `src/lerobot/engineering/nodes/flow_matching_impl.py` 走的就是上面两个模型

⚠ 现状(不许含混): 五流形目前只做**观测/闸门/看板**, 没有进任何训练目标 ⇒ 本模块给的是
"可接、接法确定、可判据", **不是"已经提升"**。要进默认档必须同口径训练+对照(见 `selftest` 末尾门槛)。
"""
from __future__ import annotations

import math
import time

import numpy as np

try:
    from .se3_hopf import hopf, hopf_join, q_normalize, quat_angle_deg, roll_delta_deg
    from .se3_layers import SE3Layered
except ImportError:                                                          # 裸脚本
    from se3_hopf import hopf, hopf_join, q_normalize, quat_angle_deg, roll_delta_deg  # type: ignore
    from se3_layers import SE3Layered                                        # type: ignore

COND_DIM = 20          # A3 + B3 + C4 + D2 + E2 + TQ6
LAYOUT = {"A": (0, 3), "B": (3, 6), "C": (6, 10), "D": (10, 12), "E": (12, 14), "TQ": (14, 20)}
TWO_PI = 2.0 * math.pi


def _wrap(a: float) -> float:
    return (a + math.pi) % TWO_PI - math.pi


class SE3FlowCond:
    """五流形条件编码 + 流形感知噪声 + 流形上插值 (只算, 不下发)。"""

    def __init__(self, layered: SE3Layered | None = None,
                 sigma_p_mm: float = 20.0, sigma_axis_deg: float = 8.0,
                 sigma_quat_deg: float = 12.0, sigma_roll_deg: float = 10.0,
                 sigma_phase: float = 0.02, sigma_tq: float = 0.10) -> None:
        self.L = layered or SE3Layered()
        self.sig = {"p_mm": float(sigma_p_mm), "axis": math.radians(sigma_axis_deg),
                    "quat": math.radians(sigma_quat_deg), "roll": math.radians(sigma_roll_deg),
                    "phase": float(sigma_phase), "tq": float(sigma_tq)}

    # ── ① 条件编码 ────────────────────────────────────────────────────────────
    def encode(self, p_mm, n, q, phi, s, tq=None) -> np.ndarray:
        """五流形 → 20 维条件向量。S¹(D/E) 用 (cos, sin), 不传裸角度。"""
        c = np.zeros(COND_DIM, dtype=np.float32)
        c[0:3] = np.asarray(p_mm, float).ravel()[:3] / 1000.0        # m (与其他量级对齐)
        c[3:6] = np.asarray(n, float).ravel()[:3]
        qv = np.asarray(q_normalize(q), float)
        if qv[3] < 0:                                                # 双覆盖: 统一到 w≥0
            qv = -qv
        c[6:10] = qv
        c[10] = math.cos(float(phi))
        c[11] = math.sin(float(phi))
        c[12] = math.cos(TWO_PI * float(s))
        c[13] = math.sin(TWO_PI * float(s))
        if tq is not None:
            v = np.asarray(tq, float).ravel()[:6]
            c[14:20] = v / 100.0                                     # 关节速度 %/s → 无量纲
        return c

    def encode_snapshot(self, snap: dict) -> np.ndarray:
        """直接用引擎快照 (SE3Layered.snapshot 的返回) 出条件向量。"""
        tq = (snap.get("TQ") or {}).get("dq_deg_s")
        return self.encode(snap["A"]["mm"], snap["B"]["n"], snap["C"]["q"],
                           math.radians(snap["D"]["phi_deg"]), snap["E"]["s"], tq)

    # ── ② 流形感知噪声 (x0) ───────────────────────────────────────────────────
    def sample_noise(self, p_mm, n, q, phi, s, tq=None, rng=None) -> tuple[np.ndarray, dict]:
        """从当前状态在**各自流形上**采初始噪声; 返回 (20 维 x0, 逐层明细)。

        每层都做真几何, 不是把高斯直接加到欧氏坐标上:
          A: p + σ·N(0,I3)                       (欧氏, 无约束)
          B: 切平面 v⊥n, θ=‖v‖ ⇒ n'=cosθ·n+sinθ·v̂ (球面测地线)
          C: q ⊗ exp(½·σ·ω), ω~N(0,I3)            (S³ 右乘, 保持单位)
          D/E: 角度环绕相加                        (S¹, 跨 ±π 必须 wrap)
        """
        r = rng or np.random.default_rng()
        out: dict = {}

        p0 = np.asarray(p_mm, float).ravel()[:3] + r.normal(0.0, self.sig["p_mm"], 3)
        out["A"] = p0

        n0 = np.asarray(n, float).ravel()[:3]
        n0 = n0 / (np.linalg.norm(n0) or 1.0)
        v = r.normal(0.0, 1.0, 3)
        v = v - np.dot(v, n0) * n0                                   # 投影到切平面
        vn = np.linalg.norm(v)
        th = float(r.normal(0.0, self.sig["axis"]))                  # 测地角(弧度)
        if vn > 1e-12:
            n1 = math.cos(th) * n0 + math.sin(th) * (v / vn)
        else:
            n1 = n0
        n1 = n1 / (np.linalg.norm(n1) or 1.0)
        out["B"] = n1

        w = r.normal(0.0, self.sig["quat"] / 2.0, 3)                 # 半角噪声
        ang = float(np.linalg.norm(w))
        if ang > 1e-12:
            ax = w / ang
            dq = (ax[0] * math.sin(ang), ax[1] * math.sin(ang), ax[2] * math.sin(ang), math.cos(ang))
            qv = q_normalize(q)
            x1, y1, z1, w1 = qv
            x2, y2, z2, w2 = dq
            q1 = (w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
                  w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
                  w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
                  w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2)
        else:
            q1 = q_normalize(q)
        out["C"] = np.asarray(q_normalize(q1), float)

        phi1 = (float(phi) + r.normal(0.0, self.sig["roll"])) % TWO_PI
        out["D"] = phi1
        s1 = (float(s) + r.normal(0.0, self.sig["phase"])) % 1.0
        out["E"] = s1

        tqv = np.zeros(6)
        if tq is not None:
            tqv = np.asarray(tq, float).ravel()[:6] * (1.0 + r.normal(0.0, self.sig["tq"], 6))
        out["TQ"] = tqv

        x0 = self.encode(p0, n1, out["C"], phi1, s1, tqv)
        return x0, out

    # ── ③ 流形上的 FM 插值 (与引擎同一份测地线) ────────────────────────────────
    def interpolate(self, x_cur: dict, x_goal: dict, t: float) -> dict:
        """x_t = geodesic(x0, x1, t) —— 逐层走各自流形, 不在 20 维欧氏里直线插。

        x_cur / x_goal = {"A":p_mm, "B":n, "C":q, "D":phi, "E":s, "TQ":v}
        """
        L = self.L
        out = {}
        out["A"] = np.asarray(L.geodesic("A", x_cur["A"], x_goal["A"], t), float)
        out["B"] = np.asarray(L.geodesic("B", x_cur["B"], x_goal["B"], t), float)
        out["C"] = np.asarray(L.geodesic("C", x_cur["C"], x_goal["C"], t), float)
        d = math.radians(roll_delta_deg(float(x_cur["D"]), float(x_goal["D"])))
        out["D"] = (float(x_cur["D"]) + t * d) % TWO_PI
        ds = (float(x_goal["E"]) - float(x_cur["E"]) + 0.5) % 1.0 - 0.5
        out["E"] = (float(x_cur["E"]) + t * ds) % 1.0
        out["TQ"] = (1 - t) * np.asarray(x_cur.get("TQ") or np.zeros(6), float) + \
                    t * np.asarray(x_goal.get("TQ") or np.zeros(6), float)
        return out

    def vector_field_input(self, x_t: dict, t: float, cond: np.ndarray) -> np.ndarray:
        """喂给速度场网络的输入向量: [x_t(20) · t(1) · cond(20)] = 41 维。

        这就是"条件编码"的落地形状: 噪声与条件**同时**进网络, 而不是只在输入端加噪。
        """
        c_t = self.encode(x_t["A"], x_t["B"], x_t["C"], x_t["D"], x_t["E"], x_t.get("TQ"))
        return np.concatenate([c_t, np.array([float(t)], np.float32), cond]).astype(np.float32)


def selftest(n_frames: int = 40, seed: int = 0) -> dict:
    """可判据自检: 编码维度 / 噪声是否真在流形上 / 插值端点是否精确 / 耗时。"""
    rng = np.random.default_rng(seed)
    F = SE3FlowCond()
    fr = F.L.frames()
    res: dict = {"cond_dim": COND_DIM, "layout": LAYOUT, "criteria": {}}

    # ① 编码: 维度 + 有限值 + 双覆盖统一 (w≥0)
    idx = list(range(0, len(fr), max(1, len(fr) // n_frames)))[:n_frames]
    ws, dims = [], set()
    for i in idx:
        snap = F.L.snapshot(i)
        c = F.encode_snapshot(snap)
        dims.add(int(c.size))
        ws.append(float(c[9]))
        assert np.all(np.isfinite(c)), i
    res["criteria"]["encode"] = {"dims": sorted(dims), "w_min": round(min(ws), 6),
                                 "all_w_ge_0": bool(min(ws) >= 0.0)}

    # ② 噪声: 是否真在流形上 (球面/单位四元数) + 角度在值域
    bad_n = bad_q = bad_ang = 0
    for i in idx:
        snap = F.L.snapshot(i)
        x0, d = F.sample_noise(snap["A"]["mm"], snap["B"]["n"], snap["C"]["q"],
                               math.radians(snap["D"]["phi_deg"]), snap["E"]["s"],
                               (snap.get("TQ") or {}).get("dq_deg_s"), rng=rng)
        if abs(np.linalg.norm(d["B"]) - 1.0) > 1e-9:
            bad_n += 1
        if abs(np.linalg.norm(d["C"]) - 1.0) > 1e-9:
            bad_q += 1
        if not (0.0 <= d["D"] < TWO_PI and 0.0 <= d["E"] < 1.0) or not np.all(np.isfinite(x0)):
            bad_ang += 1
    res["criteria"]["noise_on_manifold"] = {"samples": len(idx), "bad_B_norm": bad_n,
                                            "bad_C_norm": bad_q, "bad_range": bad_ang}

    # ③ 插值: t=0 回当前、t=1 回目标 (逐层误差), 中点仍在流形上
    e0 = e1 = 0.0
    bad_mid = 0
    for k in range(1, len(idx)):
        a, b = idx[k - 1], idx[k]
        sa, sb = F.L.snapshot(a), F.L.snapshot(b)
        xa = {"A": sa["A"]["mm"], "B": sa["B"]["n"], "C": sa["C"]["q"],
              "D": math.radians(sa["D"]["phi_deg"]), "E": sa["E"]["s"]}
        xb = {"A": sb["A"]["mm"], "B": sb["B"]["n"], "C": sb["C"]["q"],
              "D": math.radians(sb["D"]["phi_deg"]), "E": sb["E"]["s"]}
        z0 = F.interpolate(xa, xb, 0.0)
        z1 = F.interpolate(xa, xb, 1.0)
        e0 = max(e0, float(np.linalg.norm(np.asarray(z0["A"]) - np.asarray(xa["A"]))))
        e1 = max(e1, float(np.linalg.norm(np.asarray(z1["A"]) - np.asarray(xb["A"]))))
        zm = F.interpolate(xa, xb, 0.5)
        if abs(np.linalg.norm(zm["B"]) - 1.0) > 1e-9 or abs(np.linalg.norm(zm["C"]) - 1.0) > 1e-9:
            bad_mid += 1
    res["criteria"]["interpolate"] = {"t0_p_mm_err": round(e0, 9), "t1_p_mm_err": round(e1, 9),
                                      "mid_offmanifold": bad_mid}

    # ④ 网络输入: 维度 + 条件不被噪声污染 (cond 段逐位不变)
    snap = F.L.snapshot(idx[-1])
    cond = F.encode_snapshot(snap)
    x0, _ = F.sample_noise(snap["A"]["mm"], snap["B"]["n"], snap["C"]["q"],
                           math.radians(snap["D"]["phi_deg"]), snap["E"]["s"], None, rng=rng)
    xt = {k: (snap["A"]["mm"] if k == "A" else snap["B"]["n"] if k == "B" else
              snap["C"]["q"] if k == "C" else math.radians(snap["D"]["phi_deg"]) if k == "D"
              else snap["E"]["s"]) for k in ("A", "B", "C", "D", "E")}
    vec = F.vector_field_input(xt, 0.3, cond)
    res["criteria"]["net_input"] = {"dim": int(vec.size), "cond_tail_identical":
                                    bool(np.allclose(vec[21:], cond, atol=0))}

    # ⑤ 耗时
    t0 = time.perf_counter()
    for _ in range(50):
        s = F.L.snapshot(idx[-1])
        F.encode_snapshot(s)
        F.sample_noise(s["A"]["mm"], s["B"]["n"], s["C"]["q"],
                       math.radians(s["D"]["phi_deg"]), s["E"]["s"], None, rng=rng)
    res["criteria"]["ms_per_condition"] = round((time.perf_counter() - t0) * 1000.0 / 50.0, 3)

    res["ok"] = bool(res["criteria"]["encode"]["dims"] == [COND_DIM]
                     and res["criteria"]["encode"]["all_w_ge_0"]
                     and bad_n == 0 and bad_q == 0 and bad_ang == 0
                     and e0 < 1e-9 and e1 < 1e-9 and bad_mid == 0
                     and res["criteria"]["net_input"]["dim"] == 41)
    res["gate_for_default_tier"] = ("接入后必须同口径对照(同数据/同折/同评估函数): "
                                    "动作误差与成功率**有提升**才进默认档; 仅不回退只能留影子")
    return res


if __name__ == "__main__":
    import json
    print(json.dumps(selftest(), ensure_ascii=False, indent=1))
