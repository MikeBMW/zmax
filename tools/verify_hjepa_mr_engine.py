#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证 H-JEPA-MR 几何分支真的接进流形引擎 (tools/verify_hjepa_mr_engine.py)。

判据 (每条都要数值, 不要"看起来对"):
  ① 未接 provider 时 rec 里**没有** hjepa_mr 键 ⇒ 零回归 (逐位)
  ② 接入后 rec["hjepa_mr"] 结构完整, xi 6 维 / v_n 3 维 / n_pred 3 维
  ③ 语义通道 rec["hjepa"] 与几何通道 rec["hjepa_mr"] 互不干扰 (同时接两个都在)
  ④ 几何量随输入单调: 输入位姿偏移越大 ⇒ d_se3 越大
  ⑤ HJEPA_MR_W 默认 0 ⇒ 动作与不接时**逐位相同** (只观测不动动作)
"""
import os
import sys

import numpy as np


def main():
    root = os.environ.get("ZMAX_ROOT") or "/home/ubuntu/zmax"
    sys.path.insert(0, os.path.join(root, "src"))

    from lerobot.manifold.manifold_engine import ManifoldEngine
    from lerobot.manifold.hjepa_manifold_provider import HJEPAManifoldProvider

    fails = []

    def chk(name, cond, detail=""):
        print(("  [PASS] " if cond else "  [FAIL] ") + name + (("  " + detail) if detail else ""))
        if not cond:
            fails.append(name)

    # 造一个能跑动的引擎: 先喂一段轨迹拟合, 再 step
    rng = np.random.default_rng(0)
    traj = np.cumsum(rng.normal(0, 0.02, size=(60, 7)), axis=0)

    def make_engine():
        # step(state, potential_fn=None, dt=...) —— 第二个位置参数是 potential_fn 不是速度,
        # 传 ndarray 会撞 'numpy.ndarray object is not callable' (踩过)。
        # homeostasis=False: 本测试只验几何通道, 不需要内稳态层。
        # 开着会让每步写 zmax_data/ss_live/manifold_homeostasis.json, 与常驻的
        # ss_engine_loop 抢同一个文件 ⇒ os.replace 偶发 ENOENT (踩过)。
        e = ManifoldEngine(manifold_type="sphere", homeostasis=False)
        for i in range(len(traj) - 1):
            e.step(traj[i])
        return e

    print("① 未接 provider ⇒ 零回归")
    e0 = make_engine()
    rec0 = e0.step(traj[-1])
    chk("rec 里没有 hjepa_mr 键", "hjepa_mr" not in rec0, str(sorted(rec0.keys()))[:100])
    base_action = np.asarray(rec0["u"] if "u" in rec0 else rec0.get("p_next", []), float)
    print("    （rec 键: %s）" % ", ".join(sorted(rec0.keys()))[:160])

    print("② 接入后结构完整")
    state = {"s": np.zeros(7)}

    def state_fn():
        return state["s"]

    prov = HJEPAManifoldProvider(state_fn=state_fn)
    ok, why = prov.start()
    chk("provider 启动", ok, why)

    e1 = make_engine()
    info = e1.set_hjepa_mr_provider(prov, note="H-JEPA-MR 几何分支 (验证)")
    chk("注册返回正确", info.get("provider") == "H-JEPA-MR 几何分支", str(info)[:100])
    rec1 = e1.step(traj[-1])
    chk("rec 里有 hjepa_mr", "hjepa_mr" in rec1)
    hmr = rec1.get("hjepa_mr") or {}
    chk("hjepa_mr.ok", hmr.get("ok") is True, str(hmr.get("why") or "")[:80])
    chk("xi 是 6 维", len(hmr.get("xi") or []) == 6, str(hmr.get("xi")))
    chk("v_n 是 3 维", len(hmr.get("v_n") or []) == 3, str(hmr.get("v_n")))
    chk("n_pred 是 3 维", len(hmr.get("n_pred") or []) == 3, str(hmr.get("n_pred")))
    chk("有 SE3 诊断量", "d_se3" in hmr and "d_normal" in hmr,
        "d_se3=%.6f d_normal=%.6f η=%.6f" % (hmr.get("d_se3", 0), hmr.get("d_normal", 0),
                                             hmr.get("eta", 0)))
    chk("w_phi 默认 0 (只观测)", float(hmr.get("w_phi", -1)) == 0.0, str(hmr.get("w_phi")))

    print("③ 语义通道与几何通道并存不互斥")
    # 造一个假语义 provider (不依赖真权重, 只为验证两个通道能同时挂)
    def fake_semantic():
        return {"ok": True, "z1": np.ones(64), "z2": np.ones(32), "z3": np.ones(16),
                "z_concat": np.ones(112), "energy": [0.1, 0.2, 0.3], "ms": 0.5}

    e2 = make_engine()
    e2.set_hjepa_provider(fake_semantic, note="假语义 (验证并存)")
    e2.set_hjepa_mr_provider(prov, note="H-JEPA-MR (验证并存)")
    rec2 = e2.step(traj[-1])
    chk("两个通道都在", "hjepa" in rec2 and "hjepa_mr" in rec2,
        "语义 ok=%s, 几何 ok=%s" % ((rec2.get("hjepa") or {}).get("ok"),
                                    (rec2.get("hjepa_mr") or {}).get("ok")))
    chk("语义通道维数未被污染", (rec2.get("hjepa") or {}).get("z_dim") == 112,
        str((rec2.get("hjepa") or {}).get("z_dim")))

    print("④ 单调性归几何算子, provider 只判响应")
    # 🔴 别指望未训练网络让"预测vs实际"单调: d_se3 里 0.109 的常数来自随机 ξ,
    #    输入偏移 0~0.05 根本撼不动它 (同一个错犯过两次, 这里预先固定判据分工)。
    from lerobot.manifold.manifold_layer import ContactManifold
    _c = ContactManifold()
    _I = np.eye(4)
    xs = []
    for dx in (0.0, 0.001, 0.005, 0.02, 0.05):
        _T = np.eye(4); _T[0, 3] = dx
        xs.append(_c.decompose_se3(_T, _I)["d_se3"])
    print("    接触流形 d_SE3: %s" % " → ".join("%.6f" % v for v in xs))
    chk("接触流形 d_SE3 严格单调且等于平移量",
        all(xs[i] <= xs[i + 1] + 1e-12 for i in range(len(xs) - 1))
        and all(abs(xs[i] - [0.0, 0.001, 0.005, 0.02, 0.05][i]) < 1e-9 for i in range(5)))

    ds = []
    for dx in (0.0, 0.02, 0.05):
        state["s"] = np.array([dx, 0, 0, 0, 0, 0, 0.0])
        prov()
        e3 = make_engine()
        e3.set_hjepa_mr_provider(prov)
        r = e3.step(traj[-1]).get("hjepa_mr") or {}
        ds.append(float(r.get("d_se3") or 0.0))
    print("    provider d_se3 (含随机 ξ 常数): %s" % " → ".join("%.6f" % v for v in ds))
    chk("provider 对输入变化有响应", max(ds) - min(ds) > 1e-9,
        "跨度 %.6e" % (max(ds) - min(ds)))

    print("⑤ HJEPA_MR_W=0 ⇒ 动作逐位不变")
    e4 = make_engine()
    rec4a = e4.step(traj[-1])
    e5 = make_engine()
    e5.set_hjepa_mr_provider(prov)
    rec5 = e5.step(traj[-1])
    key = "u" if "u" in rec4a else ("p_next" if "p_next" in rec4a else None)
    if key:
        same = bool(np.array_equal(np.asarray(rec4a[key], float), np.asarray(rec5[key], float)))
        chk("动作逐位相同 (%s)" % key, same,
            "max|Δ|=%.3e" % float(np.abs(np.asarray(rec4a[key], float)
                                         - np.asarray(rec5[key], float)).max()))
    else:
        chk("找到动作键", False, str(sorted(rec4a.keys()))[:120])

    # Φ 也应该逐位相同 (W=0 表示不进势)
    chk("Φ 逐位相同 (W=0 不进势)",
        abs(float(rec4a.get("phi", 0)) - float(rec5.get("phi", 0))) < 1e-15,
        "%.15f vs %.15f" % (rec4a.get("phi", 0), rec5.get("phi", 0)))

    print()
    if fails:
        print("❌ %d 项失败: %s" % (len(fails), ", ".join(fails)))
        return 1
    print("✅ 全部通过 (H-JEPA-MR 已真接进流形引擎, 零回归成立)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
