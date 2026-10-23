#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""orbit_predict.py — 流形引擎 · 对称轨道预测 (老倪 2026-10-23)

命题 (老倪原话的数学化): **预测 = 沿对称群轨道做等距离推演**。
「等距离」不是空间距离, 而是**对称变换的一步** —— 只要物理律在群 G 下不变, 状态 x 与 g·x
物理上完全等价 (同一轨道), 于是「已知点看到什么, 沿轨道推一步同样看到什么」。

落到本引擎 (球面/SU(2) 档, p ∈ S³): 群作用下的轨道就是**大圆 (测地线)**,
「等距离的一步」= **恒定弧长的测地线步**。严格写法只用球面几何原语 (单真源 sphere.py):

    U_i     = log_{p_i}(p_{i+1})              # 第 i 步的切向量 (挂在 p_i)
    V_host  = PT_{p_{n-1}→p_n}(U_{n-1})       # 把上一步"速度"沿轨道搬到当前点
    p̂_{n+k} = 反复 exp/PT 推进 k 步 (等弧长)   # k=1 精确; k>1 逐步平行搬移
    ‖U_i‖ ≡ 常数                              # 「等距离」的判据: 弧长不随步变

自由运动 (无外力矩) ⇒ 速度沿轨道平行不变 ⇒ 上式**精确**外推 (实测一步误差 0.0 rad)。
这就是"利用对称性把已知点平移到未知点"的可算形式。

对称破缺 (预测的边界) —— 四种可测破缺, 任一超阈即判**无效**, 只报破缺, 绝不外推:
  1. `drift` = std(‖U‖)/mean(‖U‖)                弧长不再等距 ⇒ 外力矩/势梯度在扭曲轨道
  2. `accel` = |‖U_last‖−‖U_prev‖| / mean(‖U‖)    这一步速度突变 (接触/指令/碰撞)
  3. `bend`  = ∠(V_host, U_last) / mean(‖U‖)      方向被扭 ⇒ 轨道弯曲 ⇒ 势非不变
  4. `phi_drift` = |ΔΦ| / mean(‖U‖)               势沿轨道变化 ⇒ 该方向群对称被势破坏

纪律: 只用 `manifold/sphere.py` 的原语, 本文件不写第二套 exp/log; 没有观测就不外推
      (n < 2 ⇒ valid=False, 明说"不猜"); 静止 ⇒ speed=0 且标 static (不假装预测成功)。
"""

from __future__ import annotations

import numpy as np

try:                                       # 被当包导入 (引擎 / 判据脚本)
    from . import sphere as _sp
except Exception:                          # 当脚本跑 (python src/lerobot/manifold/orbit_predict.py)
    import os as _os
    import sys as _sys
    _SRC = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    if _SRC not in _sys.path:
        _sys.path.insert(0, _SRC)
    from lerobot.manifold import sphere as _sp

EPS = 1e-12
STATIC_EPS = 1e-6      # 步长低于此即视为静止 (真机遥测抖动地板 ~1e-6 rad/帧, 实测 4e-7)


def _dist(p, q, manifold: str = "sphere") -> float:
    if manifold != "euclidean":
        return float(_sp.distance(p, q))
    return float(np.linalg.norm(np.asarray(q, float).ravel() - np.asarray(p, float).ravel()))


def _step_vec(p, q, manifold: str = "sphere") -> np.ndarray:
    """轨迹的一步 = 挂在 p 上的切向量 (球面 log_map; 欧氏直接差)。"""
    if manifold == "euclidean":
        return np.asarray(q, float).ravel() - np.asarray(p, float).ravel()
    return _sp.log_map(p, q)


def _push(u, p_from, p_to, manifold: str = "sphere") -> np.ndarray:
    """把切向量沿轨道平行搬到下一点 —— 「速度不随位置变」的实现。"""
    if manifold == "euclidean":
        return np.asarray(u, float).ravel()
    return _sp.parallel_transport(p_from, p_to, np.asarray(u, float).ravel())


def _apply(p, v, manifold: str = "sphere") -> np.ndarray:
    """从 p 沿切向量 v 走一步 (exp 映射)。"""
    if manifold == "euclidean":
        return np.asarray(p, float).ravel() + np.asarray(v, float).ravel()
    return _sp.exp_map(p, np.asarray(v, float).ravel())


def _angle_between(u, v) -> float:
    nu, nv = float(np.linalg.norm(u)), float(np.linalg.norm(v))
    if nu < EPS or nv < EPS:
        return 0.0
    c = float(np.dot(np.asarray(u, float).ravel(), np.asarray(v, float).ravel()) / (nu * nv))
    return float(np.arccos(max(-1.0, min(1.0, c))))


class OrbitPredictor:
    """沿对称群轨道做等距离推演 + 对称破缺检测 (常驻可用, 每拍 O(window·d))。

    参数:
      window     统计等距性/速度离散的步数窗口 (>=2)。
      horizons   多步预测步数, 如 (1,2,5)。
      drift_tol  弧长离散度阈值。超此 ⇒ 轨道被力矩扭曲。
      accel_tol  单步速度相对突变阈值。超此 ⇒ 破缺 (接触/指令)。
      bend_tol   方向扭转阈值 (弧度/平均步长)。超此 ⇒ 轨道弯曲。
      phi_tol    势沿轨道的相对漂移阈值。
      manifold   "sphere"(su2/so3/S^n) 或 "euclidean"。
    """

    # 阈值来源: 在 400 帧真 episode 上做的门控扫描 (见 zmax_data/eval/orbit_predict_*.json)
    #   取「覆盖 × 精度」最优点: 覆盖 76.9% 时 valid 拍误差 = 保持基线的 19%。
    #   drift 放宽到 1.0 是因为真机步长本身抖 (CV 大), 真正做判别的是 accel 与残差 (bend)。
    def __init__(self, window: int = 6, horizons=(1, 2, 5), drift_tol: float = 1.0,
                 accel_tol: float = 0.60, bend_tol: float = 0.50, phi_tol: float = 0.50,
                 manifold: str = "sphere"):
        self.window = max(2, int(window))
        self.horizons = tuple(sorted({int(h) for h in horizons if int(h) >= 1})) or (1,)
        self.drift_tol = float(drift_tol)
        self.accel_tol = float(accel_tol)
        self.bend_tol = float(bend_tol)
        self.phi_tol = float(phi_tol)
        self.manifold = str(manifold)
        self.reset()

    # ── 状态 ────────────────────────────────────────────────────────────
    def reset(self) -> None:
        self.hist: list[np.ndarray] = []
        self.steps: list[float] = []
        self.phi_hist: list[float] = []
        self._pending: dict[int, np.ndarray] = {}
        self.errors: list[float] = []
        self.resid = 0.0                       # 上一步「预测残差/步长」= 轨道假设的实际违反量
        self.n_valid = self.n_invalid = 0
        self.n_ahead = 0

    def host_velocity(self) -> np.ndarray | None:
        """V_host = 上一步速度沿轨道搬到当前点 (等距推演的"速度")。"""
        if len(self.hist) < 2:
            return None
        u = _step_vec(self.hist[-2], self.hist[-1], self.manifold)     # ∈ T_{p_{n-1}}
        # 必须搬到 T_{p_n}: 不搬就等于把上个切空间的向量硬用在当前点 (实测偏 3.75e-5 rad)
        return _push(u, self.hist[-2], self.hist[-1], self.manifold)

    def predict(self, p, k: int = 1, v=None) -> np.ndarray:
        """沿轨道等距推 k 步 (逐步平行搬移, 恒定弧长)。"""
        q = np.asarray(p, float).ravel()
        vel = self.host_velocity() if v is None else np.asarray(v, float).ravel()
        if vel is None:
            return q.copy()
        for _ in range(int(max(1, k))):
            q2 = _apply(q, vel, self.manifold)
            vel = _push(vel, q, q2, self.manifold)
            q = q2
        return q

    # ── 主入口 ──────────────────────────────────────────────────────────
    def observe(self, p, phi: float | None = None) -> dict:
        p = np.asarray(p, float).ravel() if p is not None else np.zeros(0)
        if p.size == 0:
            return {"n": 0, "valid": False, "break_reason": "no_point", "pred": {}}

        # ① 结算上一步预测误差 (真值到了才记账)
        err = None
        pend = self._pending.get(1)
        if pend is not None and pend.size == p.size:
            err = _dist(pend, p, self.manifold)
            self.errors.append(err)
            self.n_ahead += 1
            prev_mean = float(np.mean(self.steps[-self.window:])) if self.steps else 0.0
            self.resid = float(err / max(prev_mean, EPS)) if prev_mean > EPS else 0.0

        # ② 记历史与步长
        if self.hist and self.hist[-1].size == p.size:
            self.steps.append(_dist(self.hist[-1], p, self.manifold))
        self.hist.append(p)
        if phi is not None:
            self.phi_hist.append(float(phi))
        keep = self.window + 3
        self.hist = self.hist[-keep:]
        self.steps = self.steps[-keep:]
        self.phi_hist = self.phi_hist[-keep:]

        n = len(self.hist)
        v_host = self.host_velocity()
        u_last = _step_vec(self.hist[-2], self.hist[-1], self.manifold) if n >= 2 else None
        speed = float(np.linalg.norm(u_last)) if u_last is not None else 0.0
        step_mean = float(np.mean(self.steps[-self.window:])) if self.steps else 0.0

        # ③ 破缺判读 (全部是"与等距轨道"的偏差)
        drift = accel = bend = 0.0
        if len(self.steps) >= 2:
            a = np.asarray(self.steps[-self.window:], float)
            drift = float(a.std() / max(a.mean(), EPS))
            accel = float(abs(self.steps[-1] - self.steps[-2]) / max(a.mean(), EPS))
        # 注: bend 必须在**同一切空间**比 —— u_last 在 T_{p_{n-1}}, V_host 在 T_{p_n},
        # 直接比会凭空多出一个步长的夹角 (实测 =θ)。真正可测的"轨道被扭"是
        # **预测残差 / 步长** (resid): 上一拍的外推若已经偏了半拍以上, 说明轨道假设已破。
        bend = self.resid

        preds = {int(h): self.predict(p, h, v=v_host) for h in self.horizons}
        phi_drift = 0.0
        break_reason, valid = "", True
        if n < 2:
            valid, break_reason = False, "insufficient_history"
        elif step_mean < STATIC_EPS:
            valid, break_reason = True, ""          # 静止: 预测=保持 (平凡, static 标记)
        elif drift > self.drift_tol:
            valid, break_reason = False, "orbit_distorted(step_length_dispersion)"
        elif accel > self.accel_tol:
            valid, break_reason = False, "symmetry_broken(speed_step_change)"
        elif bend > self.bend_tol:
            valid, break_reason = False, "orbit_bent(prediction_residual)"

        # ④ 势沿轨道是否变化: Φ 不变 ⇔ 该方向对称; 变了 ⇒ 势破坏了对称 (自发破缺/边界)
        if valid and phi is not None and len(self.phi_hist) >= 2 and step_mean > EPS:
            dphi = float(self.phi_hist[-1] - self.phi_hist[-2])
            phi_drift = abs(dphi) / max(step_mean, EPS)
            if phi_drift > self.phi_tol:
                valid, break_reason = False, "phi_not_invariant(potential_breaks_orbit)"

        self.n_valid += 1 if valid else 0
        self.n_invalid += 0 if valid else 1
        self._pending = preds if n >= 2 else {}   # 没速度就不算"预测", 不记账

        em = float(np.mean(self.errors[-50:])) if self.errors else None
        rm = float(np.sqrt(np.mean(np.square(self.errors[-50:])))) if self.errors else None
        hit = float(np.mean([e < 0.01 for e in self.errors[-50:]])) if self.errors else None
        return {
            "n": n, "speed_rad": round(speed, 8), "step_mean": round(step_mean, 8),
            # 轨道速度本身 (挂在 p 上): 上层要"沿轨道推进/约束动作"时必须拿它, 不能只看预测点
            "v": [round(float(x), 8) for x in (v_host if v_host is not None else np.zeros(p.size))],
            "pred": {str(h): [round(float(x), 6) for x in q] for h, q in preds.items()},
            "valid": bool(valid), "break_reason": break_reason,
            "static": bool(step_mean < STATIC_EPS),
            "drift": round(drift, 5), "accel": round(accel, 5),
            "bend": round(bend, 5), "phi_drift": round(phi_drift, 5),
            "err_rad": None if err is None else round(err, 8),
            "rmse_rad": None if rm is None else round(rm, 8),
            "mean_rad": None if em is None else round(em, 8),
            "hit_rate": None if hit is None else round(hit, 4),
            "n_ahead": self.n_ahead, "n_valid": self.n_valid, "n_invalid": self.n_invalid,
        }


# ══════════════════════════════════════════════════════════════════════
# 纯函数版 (离线判据/复算, 无状态)
# ══════════════════════════════════════════════════════════════════════
def orbit_velocity(p0, p1, manifold: str = "sphere") -> np.ndarray:
    """一步的切向量 U = log_{p0}(p1) (挂在 p0 上)。"""
    return _step_vec(p0, p1, manifold)


def orbit_extrapolate(p, v, k: int = 1, manifold: str = "sphere") -> np.ndarray:
    """从 p 出发沿切向量 v 走 k 步 (等弧长, 逐步平行搬移)。"""
    q = np.asarray(p, float).ravel()
    vel = np.asarray(v, float).ravel()
    for _ in range(int(max(1, k))):
        q2 = _apply(q, vel, manifold)
        vel = _push(vel, q, q2, manifold)
        q = q2
    return q


def symmetry_residual(states, manifold: str = "sphere", window: int = 6) -> dict:
    """量一串流形点「还剩多少轨道对称性」(离线判据用)。

    equal_step_cv=0 ⇒ 弧长完全等距 (理想群轨道); bend=0 ⇒ 轨道是直的 (同一大圆)。
    """
    S = [np.asarray(s, float).ravel() for s in states if s is not None]
    if len(S) < 3:
        return {"n": len(S), "ok": False, "why": "need>=3"}
    step = [_dist(S[i], S[i + 1], manifold) for i in range(len(S) - 1)]
    w = step[-int(window):]
    mean = float(np.mean(w))
    drift = float(np.std(w) / max(mean, EPS))
    accel = float(abs(step[-1] - step[-2]) / max(mean, EPS))
    bends = []
    for i in range(1, len(S) - 1):
        u_prev = _push(_step_vec(S[i - 1], S[i], manifold), S[i - 1], S[i], manifold)  # 搬到同一切空间
        u_cur = _step_vec(S[i], S[i + 1], manifold)
        bends.append(_angle_between(u_prev, u_cur))
    bend = float(np.mean(bends[-int(window):]) / max(mean, EPS)) if bends else 0.0
    return {"n": len(S), "ok": True, "speed": round(mean, 8),
            "drift": round(drift, 6), "accel": round(accel, 6), "bend": round(bend, 6),
            "equal_step_cv": round(drift, 8),
            "steps": [round(float(x), 8) for x in step[-8:]]}


def _selftest() -> int:
    """等速轨道必须**精确**复现; 变轨必须被抓住; 静止必须标 static。"""
    rng = np.random.default_rng(0)
    p0 = _sp.normalize(rng.normal(size=4))[0]        # normalize 返回 (p, meta)
    v0 = _sp.tangent_project(p0, np.array([0.0, 0.03, -0.02, 0.01]))
    traj = [p0]                     # 速度沿轨道逐步平行搬移 ⇒ 真正的等速大圆
    vel = v0
    for _ in range(12):
        q = _apply(traj[-1], vel)
        vel = _push(vel, traj[-1], q)
        traj.append(q)
    d = [_dist(traj[i], traj[i + 1]) for i in range(len(traj) - 1)]
    print("  等距性: 步长 %.12f ± %.2e (CV %.2e)" % (np.mean(d), np.std(d), np.std(d) / np.mean(d)))
    r = symmetry_residual(traj)
    print("  对称残余: speed=%.6f drift=%.2e accel=%.2e bend=%.2e"
          % (r["speed"], r["drift"], r["accel"], r["bend"]))

    pr = OrbitPredictor(window=6)
    out = [pr.observe(p) for p in traj]
    errs = [o["err_rad"] for o in out if o["err_rad"] is not None]
    ok_a = all(o["valid"] for o in out[2:]) and (max(errs) if errs else 1) < 1e-9
    print("  ① 等速轨道: 有效 %d/%d · 最大一步误差 %.2e · %s"
          % (sum(1 for o in out[2:] if o["valid"]), len(out) - 2,
             max(errs) if errs else -1, "✅" if ok_a else "❌"))

    # ② 破缺: 第 8 步起速度翻倍 (外部力矩) ⇒ 必须在第 8/9 拍被抓住
    v2 = 2.0 * _push(v0, traj[6], traj[7])
    bad = list(traj[:8]) + [_apply(traj[7], v2)]
    for _ in range(3):
        vv = _push(v2, bad[-2], bad[-1])
        bad.append(_apply(bad[-1], vv))
    pr2 = OrbitPredictor(window=6)
    outs = [pr2.observe(p) for p in bad]
    flags = [i for i, o in enumerate(outs) if i >= 2 and not o["valid"]]
    ok_b = bool(flags) and min(flags) in (8, 9)
    print("  ② 速度突变: 首次判无效 @第 %s 拍 (%s) · %s"
          % (min(flags) if flags else "-",
             outs[min(flags)]["break_reason"] if flags else "-", "✅" if ok_b else "❌"))

    # ③ 静止: 预测=保持, 标 static (不假装预测成功)
    pr3 = OrbitPredictor(window=4)
    outs3 = [pr3.observe(traj[0]) for _ in range(6)]
    ok_c = bool(outs3[-1]["static"]) and outs3[-1]["valid"]
    print("  ③ 静止序列: speed=%.1e static=%s valid=%s %s"
          % (outs3[-1]["speed_rad"], outs3[-1]["static"], outs3[-1]["valid"], "✅" if ok_c else "❌"))

    ok = (np.std(d) < 1e-12) and ok_a and ok_b and ok_c
    print("  自检:", "✅" if ok else "❌")
    return 0 if ok else 1


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    print(__doc__)
