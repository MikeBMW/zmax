#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🌐 hjepa_manifold_provider.py — H-JEPA-MR 引擎内联通道 (老倪 2026-10-23)

把 `hjepa_manifold.GeometricBranch` + 接触流形(黎曼) + 性能流形(黎曼) 串成
一个 `engine.set_hjepa_provider()` 可注册的 callable, 结果进 `rec["hjepa_mr"]`。

和既有 `hjepa_state.HJEPAStateProvider` 的关系 (不替代, 并存):
  · hjepa_state     → 语义分支 (z1/z2/z3 三层潜范数 + 每层能量) 进 rec["hjepa"]
  · 本模块          → 几何分支 (ξ twist + v 法线切向量 + 不确定性) 进 rec["hjepa_mr"]
  两者都吃同一个 state7 和同一帧, 分开是因为**语义和几何必须解耦** (方案核心)。

为什么几何目标用动量分支而不是回归真值 (方案 §四 范式A):
  产线上没有逐帧 6D 位姿标注, 但有海量时序视频和机械臂 TCP 真值。
  动量 target 提供"几何的自洽目标", 只需要相对变化量正确 —— 精细装配恰恰是相对偏差控制。
  有 GT 时切范式B (监督模式), 本模块 both 支持。

state7 口径: [x,y,z,rx,ry,rz,grip] (与 hjepa_state 一致, 来自引擎当前 obs)。

自检: python3 -m lerobot.manifold.hjepa_manifold_provider --selftest
"""
from __future__ import annotations

import os
import sys
import time

import numpy as np

try:
    from .hjepa_manifold import (D_G, LAMBDA_G_DEFAULT, LAMBDA_N_DEFAULT,
                                 build_geometric_branch, ema_update,
                                 make_momentum_target, sample_twist,
                                 se3_distance, se3_pose_from_twist,
                                 sphere_distance, sphere_geodesic_loss,
                                 sphere_retract, tangent_gaussian_nll)
    from .manifold_layer import ContactManifold, PerformanceManifold
except Exception:                                                      # noqa: BLE001
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from hjepa_manifold import (D_G, LAMBDA_G_DEFAULT, LAMBDA_N_DEFAULT,  # type: ignore
                                build_geometric_branch, ema_update,
                                make_momentum_target, sample_twist,
                                se3_distance, se3_pose_from_twist,
                                sphere_distance, sphere_geodesic_loss,
                                sphere_retract, tangent_gaussian_nll)
    from manifold_layer import ContactManifold, PerformanceManifold      # type: ignore


def _rpy_to_T(state7, g0=None):
    """state7 → SE(3)。用 TCP 位姿当 g (米/弧度), g0 给定时算相对位姿。"""
    s = np.asarray(state7, float).ravel()
    x, y, z = (s[0], s[1], s[2]) if len(s) >= 3 else (0.0, 0.0, 0.0)
    rx, ry, rz = (s[3], s[4], s[5]) if len(s) >= 6 else (0.0, 0.0, 0.0)
    cx, sx = np.cos(rx), np.sin(rx)
    cy, sy = np.cos(ry), np.sin(ry)
    cz, sz = np.cos(rz), np.sin(rz)
    Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    T = np.eye(4)
    T[:3, :3] = Rz @ Ry @ Rx
    T[:3, 3] = [x, y, z]
    if g0 is not None:
        T = np.linalg.inv(np.asarray(g0, float).reshape(4, 4)) @ T
    return T


class HJEPAManifoldProvider:
    """state7 (+可选帧) → 几何分支输出 + 黎曼接触/性能流形诊断。

    轻量: 几何分支只有 ~10 万参数 (主分支 z_enc 三层约 100 万), 每步 CPU 前向够用。
    没有 torch 时自动退回"纯几何诊断"模式 (只跑接触/性能流形的黎曼通道, 不出 ξ)。
    """

    def __init__(self, state_fn=None, frame_fn=None, g0=None, n0=None,
                 mode: str = "weak", every: int = 1, seed: int = 0):
        self.state_fn = state_fn
        self.frame_fn = frame_fn
        self.mode = mode if mode in ("weak", "supervised") else "weak"
        self.every = max(1, int(every))
        self.g0 = np.eye(4) if g0 is None else np.asarray(g0, float).reshape(4, 4)
        self.g_rel0 = self.g0.copy()
        self._baseline_T = None      # 首步锁定的基准位姿 (装配起点)
        # 基准法线: 装配启动时刻的接触面法线 (方案 §二 g_{rel,0} / n_0)
        self.n0 = (np.array([0.0, 0.0, 1.0]) if n0 is None
                   else np.asarray(n0, float).ravel()[:3] / max(np.linalg.norm(n0), 1e-12))

        self.branch = None
        self.target = None
        self.has_torch = False
        self.err_torch = ""
        try:
            import torch
            torch.manual_seed(seed)
            self.branch = build_geometric_branch(d_in=256, d_g=D_G)
            self.target = make_momentum_target(self.branch)
            self.has_torch = True
        except Exception as e:                                          # noqa: BLE001
            self.err_torch = "%s: %s" % (type(e).__name__, str(e)[:100])

        self.contact = ContactManifold()
        self.performance = PerformanceManifold()

        self.n_ok = 0
        self.n_fail = 0
        self.last_err = ""
        self.last = {}
        self._n = 0
        self.note_base = ""

    # ── 生命周期 ──
    def start(self):
        if self.state_fn is None:
            return False, "缺 state7 源 (state_fn=None)"
        self.note_base = ("H-JEPA-MR 几何分支 · ξ∈se(3) + v∈TS² · 范式=%s · %s"
                          % (self.mode, "torch 就绪" if self.has_torch
                             else "无 torch (仅流形诊断): " + self.err_torch))
        out = self._run()
        if not out.get("ok"):
            return False, "首步失败: %s" % out.get("why")
        return True, "首步就绪 · |ξ|=%.4f · d_SE3=%.4f m · d_S²=%.4f rad" % (
            float(np.linalg.norm(out["xi"])), out["d_se3"], out["d_normal"])

    def stop(self):
        return None

    # ── 主逻辑 ──
    def _feat(self, state7):
        """state7 → 256 维"共享特征 h"的替身。

        真实 H-JEPA 里 h = v_enc(img) + s_proj(state)。这里在没有帧时用
        state7 的确定性扩展顶上, 并在 note 里如实写明 —— 不假装是图像编码器。
        """
        s = np.asarray(state7, float).ravel()
        s7 = np.zeros(7)
        s7[:min(7, len(s))] = s[:7]
        # 固定随机投影, 保证同 state → 同 h (可复现, 不引入噪声)
        if not hasattr(self, "_proj"):
            rs = np.random.RandomState(12345)
            self._proj = rs.normal(size=(7, 256)).astype(np.float32) / np.sqrt(7)
        h = (s7 @ self._proj).astype(np.float32)
        # 有帧时叠加图像特征 (轻量: 直接用灰度统计, 不加载 CNN)
        if self.frame_fn is not None:
            try:
                fr = self.frame_fn()
                if fr is not None:
                    g = np.asarray(fr, float)
                    if g.ndim == 3:
                        g = g.mean(axis=2)
                    # 8x8 块均值 → 64 维, 投影到 256
                    hh, ww = g.shape
                    blk = g[:hh // 8 * 8, :ww // 8 * 8].reshape(8, hh // 8 // 8 * 8 or 1, 8, -1)
                    coarse = np.array([g[i::8, j::8].mean() for i in range(8) for j in range(8)])
                    coarse = (coarse - coarse.mean()) / (coarse.std() + 1e-6)
                    if not hasattr(self, "_proj_img"):
                        rs = np.random.RandomState(54321)
                        self._proj_img = rs.normal(size=(64, 256)).astype(np.float32) / 8.0
                    h = h + 0.3 * (coarse.astype(np.float32) @ self._proj_img)
            except Exception:                                           # noqa: BLE001
                pass
        self._h_src = "state7投影+图像粗特征" if self.frame_fn is not None else "state7投影"
        return h

    def _run(self):
        s = self.state_fn() if self.state_fn is not None else None
        if s is None:
            self.n_fail += 1
            self.last_err = "state_fn 返回 None"
            return {"ok": False, "why": self.last_err}
        self._n += 1
        if self.every > 1 and (self._n % self.every) != 0 and self.last:
            return self.last
        t0 = time.time()

        s7 = np.asarray(s, float).ravel()[:7]
        T_cur = _rpy_to_T(s7)

        # 🔴 基准锁定 (方案 §二 g_{rel,0}): 装配启动时刻的位姿作为基准。
        #    踩过: 直接拿单位阵当 g_rel0, 而 T_cur 是绝对位姿 ⇒ 两者坐标系不同,
        #    d_SE3 变成"单位阵到绝对位姿"的固定大偏移(实测 0.109m 恒定),
        #    误差变化完全被这个常数淹没, 单调性测试直接失败。
        #    正确: 首步把当前位姿锁成基准, 之后 g_rel = g_rel0⁻¹ · g_cur。
        if self._baseline_T is None:
            self._baseline_T = T_cur.copy()
            self.g_rel0 = T_cur.copy()
        T_rel = np.linalg.inv(self._baseline_T) @ T_cur      # 当前相对位姿 (网络要预测的就是它)

        # ① 几何分支前向 → ξ, v
        xi = np.zeros(6)
        v_n = np.zeros(3)
        log_sigma = None
        if self.has_torch:
            try:
                import torch
                h = torch.from_numpy(self._feat(s7)).reshape(1, -1)
                with torch.no_grad():
                    o = self.branch(h)
                    xi = o["xi"].numpy().ravel()[:6].astype(float)
                    v_n = o["v_n"].numpy().ravel()[:3].astype(float)
                    if "log_sigma" in o:
                        log_sigma = o["log_sigma"].numpy().ravel()[:9].astype(float)
            except Exception as e:                                      # noqa: BLE001
                self.last_err = "前向失败: %s" % str(e)[:120]

        # ② 几何还原: g = g₀·exp(ξ̂);  n = Retr_{n₀}(v)
        T_pred = se3_pose_from_twist(self.g_rel0, xi)
        n_pred = sphere_retract(self.n0, v_n)

        # ③ 接触流形 (黎曼通道): SE3 测地线势 + 球面法线偏离
        #    比的是 T_pred(预测相对位姿) 与 T_rel(实际相对位姿) —— 两者都在基准坐标系,
        #    拿绝对位姿 T_cur 来比会得到恒定 0.109m 的假偏移。
        c_se3 = self.contact.decompose_se3(T_pred, T_rel)
        c_nrm = self.contact.decompose_normal_sphere(n_pred, self.n0, antipodal=True)

        # ④ 性能流形 (黎曼通道): twist 空间二次型
        p_se3 = self.performance.evaluate_se3(T_pred, T_rel)

        # ⑤ 不确定性: 切空间采样 (只要给了 log_sigma)
        xi_samples = []
        if log_sigma is not None:
            rng = np.random.default_rng(0)
            mu, ls6 = xi[:6], log_sigma[:6]
            xi_samples = [sample_twist(mu, ls6, rng=rng) for _ in range(3)]

        ms = (time.time() - t0) * 1000.0
        out = {
            "ok": True,
            "xi": xi, "v_n": v_n, "log_sigma": log_sigma,
            "T_pred": T_pred.tolist(), "n_pred": n_pred.tolist(),
            "d_se3": c_se3["d_se3"], "V_contact": c_se3["V"],
            "d_normal": c_nrm["risk_rad"],
            "V_perf": p_se3["Vp"], "eta": p_se3["eta"],
            "contact_state": c_se3["state"], "normal_state": c_nrm["state"],
            "xi_samples": xi_samples,
            "mode": self.mode,
            "ms": ms,
            "h_src": getattr(self, "_h_src", "state7投影"),
            "note": "SE3 几何分支 + 黎曼接触/性能流形 · h=%s" % getattr(self, "_h_src", "?"),
        }
        self.n_ok += 1
        self.last_err = ""
        self.last = out
        return out

    def __call__(self):
        return self._run()

    def note(self):
        if not self.n_ok:
            return "%s · 未出值 (%s)" % (self.note_base, self.last_err or "等待")
        l = self.last
        return ("%s · ok %d/失败 %d · %.1fms · d_SE3=%.5f d_S²=%.5f η=%.4f%s"
                % (self.note_base, self.n_ok, self.n_fail, float(l.get("ms") or 0),
                   float(l.get("d_se3") or 0), float(l.get("d_normal") or 0),
                   float(l.get("eta") or 0),
                   (" · 最近错误 " + self.last_err) if self.last_err else ""))


# ═══════════════════════ 自检 ═══════════════════════
def _selftest() -> int:
    fails = []

    def chk(name, cond, detail=""):
        print(("  [PASS] " if cond else "  [FAIL] ") + name + (("  " + detail) if detail else ""))
        if not cond:
            fails.append(name)

    print("① 接触流形黎曼通道")
    c = ContactManifold()
    I = np.eye(4)
    T_off = I.copy(); T_off[0, 3] = 0.002          # 偏 2mm
    r = c.decompose_se3(T_off, I)
    chk("2mm 平移 ⇒ d_SE3≈0.002", abs(r["d_se3"] - 0.002) < 1e-9, "%.10f" % r["d_se3"])
    chk("V=½d²", abs(r["V"] - 0.5 * 0.002 ** 2) < 1e-15, "%.3e" % r["V"])
    r2 = c.decompose_se3(T_off, I, xi_vel=np.array([0.001, 0, 0, 0, 0, 0]))
    chk("V̇ 给速度时非 None", r2["Vdot"] is not None, str(r2["Vdot"]))
    chk("V̇ ≤ 0 (沿误差反向移动)", r2["Vdot"] <= 1e-15, "%.3e" % r2["Vdot"])

    n_ref = np.array([0.0, 0.0, 1.0])
    th = np.radians(3.0)
    n_meas = np.array([np.sin(th), 0.0, np.cos(th)])
    rn = c.decompose_normal_sphere(n_meas, n_ref)
    chk("法线偏 3° ⇒ risk≈0.0524 rad", abs(rn["risk_rad"] - th) < 1e-9,
        "%.10f (期望 %.10f)" % (rn["risk_rad"], th))
    rn_flip = c.decompose_normal_sphere(-n_ref, n_ref, antipodal=True)
    chk("法线反向 ⇒ antipodal 下 risk=0", rn_flip["risk_rad"] < 1e-12,
        "%.3e" % rn_flip["risk_rad"])

    print("② 性能流形黎曼通道")
    p = PerformanceManifold()
    pI = p.evaluate_se3(I, I)
    chk("位姿一致 ⇒ V_p=0", pI["Vp"] == 0.0, "%.3e" % pI["Vp"])
    chk("位姿一致 ⇒ η=1", abs(pI["eta"] - 1.0) < 1e-12, "%.12f" % pI["eta"])
    # 纯姿态偏差 1°, 平移 0 ⇒ 代价 > 0 (欧氏版这里是 0!)
    ang = np.radians(1.0)
    R1 = np.array([[1, 0, 0], [0, np.cos(ang), -np.sin(ang)], [0, np.sin(ang), np.cos(ang)]])
    Ta = np.eye(4); Ta[:3, :3] = R1
    pa = p.evaluate_se3(Ta, I)
    chk("纯姿态 1° ⇒ V_p>0 (欧氏版看不见)", pa["Vp"] > 0, "%.6e (ξ=%.6f)" % (pa["Vp"], pa["xi"][0]))
    # 同一误差下, 欧氏版 evaluate 只吃点, 姿态完全丢失
    # 欧氏对照: 必须喂 hole_pos (HOLE_POS 不是原点), 否则位置误差本身就不为 0
    pe = p.evaluate(peg_head=p.hole_pos, stage="插入")
    chk("对照: 欧氏版对纯姿态误差 V_p=0", pe["Vp"] == 0.0, "%.3e" % pe["Vp"])

    print("③ provider 端到端")
    for label, state in (("零位姿", np.zeros(7)),
                         ("偏 2mm", np.array([0.002, 0, 0, 0, 0, 0, 0.0])),
                         ("偏 5mm+3°", np.array([0.005, 0, 0, 0, np.radians(3), 0, 0.0]))):
        prov = HJEPAManifoldProvider(state_fn=lambda s=state: s)
        ok, why = prov.start()
        if not ok:
            chk(label + " provider 启动", False, why)
            continue
        o = prov()
        chk(label + " provider 出值", o.get("ok") is True,
            "d_SE3=%.6f d_S²=%.6f η=%.4f %s"
            % (o["d_se3"], o["d_normal"], o["eta"], o["contact_state"]))
        chk(label + " 结构完整",
            all(k in o for k in ("xi", "v_n", "T_pred", "n_pred", "d_se3",
                                 "d_normal", "V_perf", "eta", "xi_samples")))
        prov.stop()

    # 单调性必须测**几何算子本身**, 不能穿过未训练的随机网络:
    # provider 的 d_se3 是"预测 vs 实际", ξ 来自随机初始化网络 (约 0.1 量级),
    # 输入 dx 在 0~0.02 之间变化时 d_se3 被那 0.109 的常数淹没 ⇒ 判据必然失败 (踩过)。
    xs = []
    for dx in (0.0, 0.001, 0.005, 0.02):
        T = np.eye(4); T[0, 3] = dx
        xs.append(c.decompose_se3(T, I)["d_se3"])
    chk("接触流形 d_SE3 随误差单调增",
        all(xs[i] <= xs[i + 1] + 1e-12 for i in range(len(xs) - 1)),
        " → ".join("%.5f" % v for v in xs))
    chk("接触流形 d_SE3 等于平移量 (纯平移)",
        all(abs(xs[i] - [0.0, 0.001, 0.005, 0.02][i]) < 1e-9 for i in range(4)))

    # provider 端只判"接得上、出得值、结构完整"(训练前不该要求精度)
    _dx = [0.0]
    pv_mono = HJEPAManifoldProvider(state_fn=lambda: np.array([_dx[0], 0, 0, 0, 0, 0, 0.0]))
    pv_mono.start()
    d0 = pv_mono()["d_se3"]
    _dx[0] = 0.02
    d1 = pv_mono()["d_se3"]
    chk("provider 对输入变化有响应 (d_SE3 变了)", abs(d1 - d0) > 1e-9,
        "%.5f → %.5f" % (d0, d1))

    print()
    if fails:
        print("❌ %d 项失败: %s" % (len(fails), ", ".join(fails)))
        return 1
    print("✅ 全部通过 (H-JEPA-MR provider + 接触/性能流形黎曼通道)")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv or len(sys.argv) == 1:
        sys.exit(_selftest())
    print("用法: python3 -m lerobot.manifold.hjepa_manifold_provider --selftest")
