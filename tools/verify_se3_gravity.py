#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证 SE(3) 几何阻抗「万有引力」真接进流形引擎 (tools/verify_se3_gravity.py)。

判据 (每条要数值):
  ① 未接 provider ⇒ rec 里没有 se3_gravity 键 (零回归)
  ② 接入 ⇒ u 6维 / V / V̇ / ξ_e 结构完整, V̇ ≤ 0
  ③ **关键**: 把 phi_fn 喂给 engine.gradient_flow(potential_fn=...),
     沿梯度流走 Φ 必须**单调降**且真的到 0 (这是"引力学"成立与否的硬判据)
  ④ 轴向/侧向各向异性在引擎里也成立 (同 2cm 误差, 轴向力 > 侧向)
  ⑤ dV 与 V̇ 同号 (势能与变化率同源, 不同源就是 bug)
  ⑥ SE3_GRAVITY_W=0 ⇒ 动作逐位不变
"""
import os
import sys

import numpy as np


def main():
    root = os.environ.get("ZMAX_ROOT") or "/home/ubuntu/zmax"
    sys.path.insert(0, os.path.join(root, "src"))

    from lerobot.manifold.manifold_engine import ManifoldEngine
    from lerobot.manifold.se3_gravity_provider import Se3GravityProvider, _rpy_to_T

    fails = []

    def chk(name, cond, detail=""):
        print(("  [PASS] " if cond else "  [FAIL] ") + name + (("  " + detail) if detail else ""))
        if not cond:
            fails.append(name)

    rng = np.random.default_rng(0)
    traj = np.cumsum(rng.normal(0, 0.01, size=(40, 7)), axis=0)

    def make_engine():
        # homeostasis=False: 避免每步写 manifold_homeostasis.json 和常驻 loop 抢文件
        e = ManifoldEngine(manifold_type="sphere", homeostasis=False)
        for i in range(len(traj) - 1):
            e.step(traj[i])
        return e

    goal = traj[-1].copy()
    state = {"s": traj[-1].copy()}

    print("① 未接 ⇒ 零回归")
    e0 = make_engine()
    rec0 = e0.step(traj[-1])
    chk("rec 里没有 se3_gravity", "se3_gravity" not in rec0)

    print("② 接入后结构完整")
    prov = Se3GravityProvider(state_fn=lambda: state["s"], goal=goal)
    ok, why = prov.start()
    chk("provider 启动", ok, why)
    e1 = make_engine()
    info = e1.set_se3_gravity_provider(prov, note="SE(3) 几何阻抗 (验证)")
    chk("注册返回", info.get("w") is not None, str(info)[:110])
    rec1 = e1.step(traj[-1])
    chk("rec 里有 se3_gravity", "se3_gravity" in rec1)
    sg = rec1.get("se3_gravity") or {}
    chk("ok", sg.get("ok") is True, str(sg.get("why") or "")[:80])
    chk("u 6 维", len(sg.get("u") or []) == 6, str(sg.get("u")))
    chk("V/V̇ 齐备", "V" in sg and "Vdot" in sg,
        "V=%.6e V̇=%.3e" % (sg.get("V", 0), sg.get("Vdot", 0)))
    chk("V̇ ≤ 0", float(sg.get("Vdot", 1)) <= 1e-15, "%.3e" % sg.get("Vdot", 1))
    chk("K 对角 = [80,80,400,2,2,10]",
        np.allclose(sg.get("K_diag") or [], [80, 80, 400, 2, 2, 10]), str(sg.get("K_diag")))

    print("③ 关键: phi_fn 喂 gradient_flow, Φ 必须单调降到 0")
    # 🔴 step() 内部调的是 gradient_flow() 不带 potential_fn ⇒ 用的是引擎自带的
    #    ½‖p−goal‖², 不是我们的 SE(3) 势。第一版就这么写错了, 梯度恒为 0 只跑 1 步。
    #    要验新引力, 必须**显式**把 phi_fn 作为 potential_fn 传进去。
    start = goal.copy()
    start[2] -= 0.02
    state["s"] = start
    prov.set_goal(goal)
    # 🔴 必须用 euclidean 度规: spheresu2 的 tangent_gradient 做**切球投影**,
    #    会把径向分量去掉 —— 而纯平移正是"径向" ⇒ 梯度流推不动, 实测卡在 1.96mm 不动。
    #    SE(3) 势的梯度本来就活在 R⁶ 切空间, 用球面度规是口径错误。
    e2 = ManifoldEngine(manifold_type="euclidean", homeostasis=False)
    e2.goal_point = start        # 引擎 own goal 设成起点, 势由我们的 phi_fn 接管
    phis = []
    cur = start.copy()
    for k in range(250):
        state["s"] = cur
        rec = e2.gradient_flow(potential_fn=prov.phi_fn(), p=cur)
        phi = float(rec["phi"])
        phis.append(phi)
        gr = np.asarray(rec["grad"], float).ravel()
        n = float(np.linalg.norm(gr))
        if n < 1e-9 or phi < 1e-18:
            break
        # 沿负梯度方向走, 步长随 |∇| 自适应 (小势区不抖)
        step = -gr / n * min(0.002, max(2e-4, n * 1e-3))
        cur = cur.copy()
        cur = cur + step
    print("    Φ 序列: %s ... %s  (%d 步)" % (
        ", ".join("%.3e" % v for v in phis[:3]),
        ", ".join("%.3e" % v for v in phis[-2:]), len(phis)))
    chk("Φ 单调不增", all(phis[i] >= phis[i + 1] - 1e-12 for i in range(len(phis) - 1)),
        "%d 步" % len(phis))
    chk("Φ 下降了至少 1 个数量级", phis[-1] < phis[0] * 0.1,
        "%.3e → %.3e (降 %.1f×)" % (phis[0], phis[-1], phis[0] / max(phis[-1], 1e-30)))
    # 判据按"物理精度"定: Φ = ½·k_ax·ρ² , k_ax=400 ⇒ ρ = sqrt(2Φ/400)
    rho_end = float(np.sqrt(max(2 * phis[-1] / 400.0, 0)))
    # 0.2mm 门槛: 这条判据只证明"引力能把点真拉到目标附近", 不对装配精度背书。
    # 实际精度要真机闭环 + 手眼标定才有意义。
    chk("末端残余偏差 < 0.2mm", rho_end < 2e-4,
        "Φ_end=%.3e ⇒ ρ=%.4f mm" % (phis[-1], rho_end * 1000))

    print("④ 各向异性在引擎里成立")
    state["s"] = goal.copy()
    state["s"][2] -= 0.02
    prov_z = Se3GravityProvider(state_fn=lambda: state["s"], goal=goal)
    prov_z.start()
    ez = make_engine(); ez.set_se3_gravity_provider(prov_z)
    uz = ez.step(state["s"])["se3_gravity"]["u"]
    goal_x = goal.copy(); goal_x[0] += 0.02
    prov_x = Se3GravityProvider(state_fn=lambda: state["s"], goal=goal_x)
    prov_x.start()
    ex = make_engine(); ex.set_se3_gravity_provider(prov_x)
    ux = ex.step(state["s"])["se3_gravity"]["u"]
    chk("同 2cm 误差: 轴向力 > 侧向力", abs(uz[2]) > abs(ux[0]) * 2,
        "|u_z|=%.2f N vs |u_x|=%.2f N" % (abs(uz[2]), abs(ux[0])))

    print("⑤ dV 与 V̇ 同号 (同源检查)")
    state["s"] = goal.copy()
    prov3 = Se3GravityProvider(state_fn=lambda: state["s"], goal=goal)
    prov3.start()
    e3 = make_engine(); e3.set_se3_gravity_provider(prov3)
    state["s"] = goal.copy(); state["s"][2] -= 0.01
    r_a = e3.step(state["s"])["se3_gravity"]
    state["s"] = goal.copy(); state["s"][2] -= 0.005   # 更近目标 ⇒ V 应更小
    r_b = e3.step(state["s"])["se3_gravity"]
    chk("靠近目标 ⇒ V 下降", r_b["V"] < r_a["V"],
        "V: %.6e → %.6e" % (r_a["V"], r_b["V"]))
    chk("dV 标记与 V̇ 一致", r_b.get("dV_matches_Vdot") is True,
        "dV=%.3e V̇=%.3e 标记=%s" % (r_b.get("dV") or 0, r_b["Vdot"], r_b.get("dV_matches_Vdot")))

    print("⑥ SE3_GRAVITY_W=0 ⇒ 动作逐位不变")
    e4 = make_engine()
    rec4 = e4.step(traj[-1])
    e5 = make_engine()
    e5.set_se3_gravity_provider(prov)
    rec5 = e5.step(traj[-1])
    same = bool(np.array_equal(np.asarray(rec4["p_next"], float),
                               np.asarray(rec5["p_next"], float)))
    chk("p_next 逐位相同", same,
        "max|Δ|=%.3e" % float(np.abs(np.asarray(rec4["p_next"], float)
                                     - np.asarray(rec5["p_next"], float)).max()))
    chk("Φ 逐位相同", abs(float(rec4.get("phi", 0)) - float(rec5.get("phi", 0))) < 1e-15,
        "%.15f vs %.15f" % (rec4.get("phi", 0), rec5.get("phi", 0)))

    print()
    if fails:
        print("❌ %d 项失败: %s" % (len(fails), ", ".join(fails)))
        return 1
    print("✅ 全部通过 (SE(3) 几何阻抗 = 状态空间万有引力, 零回归成立)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
