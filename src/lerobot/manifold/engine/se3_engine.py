"""SE(3) 流形引擎 —— 输出刚体变换 T / twist ξ / 势场, 并组装成 action head 的**条件约束向量**。

与 s3_chain.py 的差别 (接口层)
------------------------------
s3_chain: 条件(3维平移误差) → SU(2) 四元数 → S³ 测地线 → 角速度 ω
se3_chain: 位姿真值 T ∈ SE(3) → ξ = log(T_goal⁻¹T) ∈ se(3) → 螺旋测地线 → T(s) + ξ

数据流 (端到端, 接口对齐优先)
------------------------------
    tcp_out/latest.json (rokae SDK 真值, 10Hz)
      → T  (4×4, 平移 + 旋转齐全)
      → ξ = log(T_goal⁻¹ T)                      6 维 [ρ(平移, m); φ(旋转, rad)]
      → φ = ½‖Wξ‖²,  ∇ξ = W²ξ                    势场 + 梯度 (平移/旋转分开加权)
      → 测地线 T(s) = T·exp(s·ξ_goal), s∈[0,1]    螺旋预测
      → cond = [ξ̂(6) , manifold6 , intent(3)]     15 维标准化条件向量
      → action_head.apply_l4_cond → 条件 token → DiT → action chunk

诚实边界
--------
* 位姿真值拿不到/超过 2s ⇒ ok=False, 一律不编数;
* cond 的投影层 (l4_cond_proj) **尚未训练**: 通道真实参与前向 (可消融验证),
  但当前增益未知。本模块只保证"接口对齐 + 链路真通"。
"""
from __future__ import annotations

import json
import math
import os

import numpy as np

from lerobot.manifold.core.se3_chain import (EPS, R_to_quat, T_from_rot_t, geodesic, potential,
                        quat_to_R, read_pose_truth, se3_dist, se3_exp, se3_log)

# 归一化尺度: 平移用 mm 级行程, 旋转用 π。目的是把 6 维 twist 拉到 O(1),
# 否则平移(m) 与旋转(rad) 差三个数量级, 投影层吃不出结构。
TRAVEL_MM = 500.0
ROT_SCALE = math.pi

COND_DIM = 15          # [ξ̂ 6][manifold 6][intent 3]


def _clip(v, lim=1.0):
    return np.clip(np.asarray(v, float), -lim, lim)


def normalize_twist(xi) -> np.ndarray:
    """ξ → 6 维 O(1) 条件: 平移 mm/行程, 旋转 rad/π, 再 clip。"""
    xi = np.asarray(xi, float).reshape(6)
    out = np.empty(6)
    out[:3] = xi[:3] * 1000.0 / TRAVEL_MM
    out[3:] = xi[3:] / ROT_SCALE
    return _clip(out, 1.0)


def build_cond(xi_norm, manifold6=None, intent3=None) -> np.ndarray:
    """组装 15 维条件向量 (缺项补 0, 但元数据里标清哪些是真的)。"""
    m = np.zeros(6) if manifold6 is None else _clip(manifold6, 1.0)
    i = np.zeros(3) if intent3 is None else _clip(intent3, 1.0)
    return np.concatenate([np.asarray(xi_norm, float).reshape(6),
                           np.asarray(m, float).reshape(6),
                           np.asarray(i, float).reshape(3)]).astype(np.float32)


class ManifoldDecoder:
    """SE(3) 几何 → z7 → WorldModelPredictor + ManifoldReadout → 6 维接触/性能流形坐标。

    权重: models/l4_mani_predictor_v5.pt (predictor 11→512×3→7, readout 7→256×2→6, 已训练)。

    ⚠️ 口径诚实说明 (不得省略):
      v5 训练时的 z7 = [x−tgt, x−peg, grasped] (library.py:5326, 单位 m)。
      本模块喂的 z7 = [平移误差(m), 旋转误差(rad), grasped] —— **分布外**。
      所以 readout 读数只用于证明"接口已对齐、链路真通", 不作为可信的接触/性能预测。
      要对齐精度: 用与 v5 同口径的 z7 (需要 peg 视觉位置 + grasped 真值) 再喂。
    """

    CK = "models/l4_mani_predictor_v5.pt"

    def __init__(self, root: str = "/home/ubuntu/zmax", log=None) -> None:
        self.root = root
        self._log = log
        self.net = None
        self.ok = False
        self.why = None
        self.missing = []
        self._load()

    def _load(self):
        import os
        p = self.CK if os.path.isabs(self.CK) else os.path.join(self.root, self.CK)
        if not os.path.isfile(p):
            self.why = "缺权重 %s" % p
            return
        try:
            import torch
            from lerobot.manifold.predictor_layer import WorldModelPredictor
            net = WorldModelPredictor(z_dim=7, act_dim=4, hidden_dim=512, num_layers=4)
            sd = torch.load(p, map_location="cpu", weights_only=False)
            r = net.load_state_dict(sd, strict=False)
            self.missing = list(r.missing_keys or [])
            net.eval()
            self.net = net
            self.ok = not self.missing
            self.why = None if self.ok else "缺键 %d 个" % len(self.missing)
        except Exception as e:                                            # noqa: BLE001
            self.why = "%s: %s" % (type(e).__name__, e)

    def decode(self, z7, a4=None):
        """z7(7) [+ a4(4)] → 6 维流形坐标 [progress, risk, V, eta, rem, d_perp]。"""
        if not self.ok:
            return None
        try:
            import torch
            z = torch.as_tensor(np.asarray(z7, np.float32).reshape(1, 7))
            a = torch.as_tensor(np.zeros((1, 4), np.float32) if a4 is None
                                else np.asarray(a4, np.float32).reshape(1, 4))
            with torch.no_grad():
                out = self.net(z, a)
            return out["manifold"].reshape(-1).cpu().numpy().astype(float)
        except Exception as e:                                            # noqa: BLE001
            self.why = "%s: %s" % (type(e).__name__, e)
            return None


class SE3Engine:
    """一条 SE(3) 链路: 真值位姿 → twist/势场/测地线 → 条件向量。只算不下发。"""

    def __init__(self, root: str = "/home/ubuntu/zmax", dt: float = 0.1,
                 horizon: int = 8, w=None, log=None) -> None:
        self.root = root
        self.dt = float(dt)
        self.h = max(1, int(horizon))
        # 势场权重: 平移 3 维按 mm 口径 (×1000), 旋转 3 维按 rad; 默认等比
        self.w = np.ones(6) if w is None else np.asarray(w, float).reshape(6)
        self._log = log
        self.n = 0
        self._traj = None
        self.dec = None
        self._dec_tried = False

    # ── 目标位姿: 优先画布给的, 否则取 215 点真值表的下一点 ─────────────────
    def _traj_frames(self):
        if self._traj is not None:
            return self._traj
        self._traj = []
        for rel in ("tools/web/real_traj_joints.json", "zmax_data/tools/web/real_traj_joints.json"):
            f = os.path.join(self.root, rel)
            if os.path.isfile(f):
                try:
                    d = json.load(open(f))
                    self._traj = d.get("frames") or []
                except Exception:                                        # noqa: BLE001
                    self._traj = []
                break
        return self._traj

    def _goal_from_traj(self, idx: int | None):
        fr = self._traj_frames()
        if not fr:
            return None, "无 215 点真值表"
        i = 0 if idx is None else int(idx)
        i = max(0, min(len(fr) - 1, i))
        try:
            p = np.asarray(fr[i]["p"], float).reshape(3)      # 米
            q = np.asarray(fr[i]["q"], float).reshape(4)      # xyzw
            return T_from_rot_t(quat_to_R(q), p), "215点真值表 idx=%d/%d" % (i, len(fr) - 1)
        except Exception:                                                # noqa: BLE001
            return None, "215 点表字段异常"

    # ── 一拍 ────────────────────────────────────────────────────────────────
    def step(self, frame: dict | None = None, T_goal=None,
             manifold6=None, intent3=None) -> dict:
        """跑一拍: 返回 T / ξ / φ / 梯度 / 测地线预测 / 15 维 cond。拿不到真值 ⇒ ok=False。"""
        pt = read_pose_truth(self.root)
        if pt is None:
            return {"ok": False, "manifold": "se3", "why": "位姿真值不可用 (缺失或 >2s 陈旧)",
                    "cond": None, "cond_dim": COND_DIM}
        T = pt.T

        src = None
        if T_goal is None and frame:
            for k in ("T_goal", "target_pose", "tcp_goal"):
                v = frame.get(k)
                if v is not None:
                    try:
                        T_goal = np.asarray(v, float).reshape(4, 4)
                        src = "画布端口 %s" % k
                        break
                    except Exception:                                    # noqa: BLE001
                        pass
            if T_goal is None and frame.get("traj_idx") is not None:
                T_goal, src = self._goal_from_traj(frame.get("traj_idx"))
        if T_goal is None:
            T_goal, src = self._goal_from_traj(None)

        if T_goal is None:
            xi_goal = np.zeros(6)
            phi = 0.0
            grad = np.zeros(6)
            goal_src = "无目标 ⇒ ξ=0 (不编方向)"
        else:
            xi_goal = se3_log(np.linalg.inv(T_goal) @ T)
            # 势场/梯度: 权重按量纲 (m 与 rad 不能直接相加 ⇒ 平移维 ×1000 转 mm)
            w_m = np.array([self.w[0] * 1000.0, self.w[1] * 1000.0, self.w[2] * 1000.0,
                            self.w[3], self.w[4], self.w[5]])
            phi, grad_w = potential(T, T_goal, w=w_m)
            grad = grad_w
            goal_src = src or "?"

        # 螺旋测地线预测 (h 步, 每步 dt)
        traj_T = []
        if T_goal is not None:
            for k in range(1, self.h + 1):
                s = min(1.0, k * self.dt / max(self.dt * self.h, 1e-9))
                traj_T.append(geodesic(T, T_goal, s))

        # 接触/性能流形坐标: 外部给了就用外部(in5 画布端口), 否则本模块用 SE(3) 几何自算
        manifold_src = "外部(in5)" if manifold6 is not None else None
        if manifold6 is None:
            if not self._dec_tried:
                self.dec = ManifoldDecoder(self.root, log=self._log)
                self._dec_tried = True
            if self.dec is not None and self.dec.ok:
                # z7 口径: [平移误差(m) | 旋转误差(rad) | grasped(未知⇒0.5)]
                z7 = np.concatenate([xi_goal[:3], xi_goal[3:], [0.5]])
                m6 = self.dec.decode(z7)
                if m6 is not None:
                    manifold6 = m6
                    manifold_src = "SE3→z7→WorldModelPredictor(readout)"

        xi_norm = normalize_twist(xi_goal)
        cond = build_cond(xi_norm, manifold6, intent3)

        self.n += 1
        return {
            "ok": True, "manifold": "se3", "n": self.n,
            "T": T.tolist(),
            "t_mm": (T[:3, 3] * 1000.0).round(3).tolist(),
            "quat_xyzw": R_to_quat(T[:3, :3]).round(6).tolist(),
            "pose_age_s": round(pt.age_s, 3), "pose_src": pt.src, "frame": pt.frame,
            "T_goal": None if T_goal is None else np.asarray(T_goal).tolist(),
            "goal_src": goal_src,
            "xi": xi_goal.round(9).tolist(),                      # [ρ(m); φ(rad)]
            "xi_norm": xi_norm.round(6).tolist(),
            "phi": round(float(phi), 9),
            "grad_norm": round(float(np.linalg.norm(grad)), 6),
            "dist_m": (None if T_goal is None else round(se3_dist(T, T_goal), 6)),
            "rot_deg": round(math.degrees(float(np.linalg.norm(xi_goal[3:]))), 3),
            "trans_mm": round(float(np.linalg.norm(xi_goal[:3])) * 1000.0, 3),
            "plan": {"h": self.h, "dt": self.dt,
                     "T": [np.asarray(t).round(6).tolist() for t in traj_T[:3]]},  # 前 3 步样例
            "manifold6": (None if manifold6 is None else np.asarray(manifold6, float).round(6).tolist()),
            "manifold_src": manifold_src,
            "manifold_decoder": (None if self.dec is None else
                                 {"ck": ManifoldDecoder.CK, "ok": self.dec.ok, "why": self.dec.why,
                                  "z7_layout": "[平移误差(m)|旋转误差(rad)|grasped]",
                                  "z7_scale_note": "v5 训练口径为 [x-tgt, x-peg, grasped] ⇒ 本次分布外"}),
            "cond": cond.round(6).tolist(), "cond_dim": COND_DIM,
            "cond_layout": "[0:6]ξ̂(平移mm/行程,旋转rad/π) [6:12]manifold6 [12:15]intent3",
            "cond_real": {"xi": True,
                          "manifold": manifold6 is not None,
                          "intent": intent3 is not None},
            "note": "只算不下发; l4_cond_proj 未训练 ⇒ 条件通道真参与但增益未验证",
        }

    # ── 自检: 接口 + 数值一致性 (不依赖训练, 只验链路) ──────────────────────
    def selftest(self, n: int = 30) -> dict:
        rep = {"n": 0, "ok": True, "checks": {}}
        a = b = None
        ages = []
        for _ in range(n):
            o = self.step()
            if not o["ok"]:
                rep["checks"]["step"] = o.get("why")
                rep["ok"] = False
                return rep
            rep["n"] += 1
            ages.append(o["pose_age_s"])
            c = np.asarray(o["cond"], float)
            if a is None:
                a = c
            b = c
        rep["checks"]["cond_dim"] = int(a.size)
        rep["checks"]["cond_finite"] = bool(np.all(np.isfinite(a)))
        rep["checks"]["cond_range"] = [float(a.min()), float(a.max())]
        rep["checks"]["cond_clip_ok"] = bool(np.all(np.abs(a) <= 1.0 + 1e-6))
        rep["checks"]["pose_age_max_s"] = round(max(ages), 3)
        rep["checks"]["cond_changes_over_time"] = bool(not np.allclose(a, b, atol=1e-9))
        rep["ok"] = bool(rep["checks"]["cond_dim"] == COND_DIM
                         and rep["checks"]["cond_finite"]
                         and rep["checks"]["cond_clip_ok"])
        return rep


if __name__ == "__main__":
    e = SE3Engine()
    o = e.step()
    print(json.dumps({k: v for k, v in o.items() if k not in ("T", "T_goal", "plan")},
                     ensure_ascii=False, indent=2))
    print("\n-- selftest --")
    print(json.dumps(e.selftest(12), ensure_ascii=False, indent=2))
