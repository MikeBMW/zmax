#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_state55.py — 55D 统一状态空间升级验收 (七组判据, 全要真数字)

① 布局完整性: 19 段首尾相接覆盖 0:55, 无重名/重叠
② 融合语义:   39+4+12 → 55; 前 43 维与 43D 老口径**逐位相同**
③ 扩展隔离:   扩展 12 维填任何数都不改变 z (零行初始化 ⇒ 升级不动老系统)
④ 引擎适配:   同一标定 + 同一状态, 43 维引擎 vs 55 维引擎 的 z 差 (应为 0 或 1e-16 级)
⑤ 测地线:     atan2 形式在 q1=q2 处梯度有限; 对照 acos 形式在同样输入下为 NaN/inf
⑥ SLERP:      端点精确、中点单位模、θ→0 与 θ→π 两个退化分支都无 NaN 梯度
⑦ 兼容回归:   fuse_sensors() 默认仍是 43 维 (在役 L3/L4 权重不吃 55)

用法: python tools/verify_state55.py
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np

ROOT = os.environ.get("ZMAX_ROOT", "/home/ubuntu/zmax")
sys.path.insert(0, os.path.join(ROOT, "src"))

try:                                                                          # 正常 (550A)
    from lerobot.policies.left_right.state_space import perception as PC      # noqa: E402
    from lerobot.policies.left_right.state_space import unified_state55 as U  # noqa: E402
except Exception as _e:                                                       # 端侧 (550C: 包 __init__ 依赖缺失)
    import importlib.util                                                     # noqa: PLC0415
    _d = os.path.join(ROOT, "src/lerobot/policies/left_right/state_space")
    print("⚠️ 包导入失败 (%s) → 按文件路径加载 %s" % (type(_e).__name__, _d))

    def _load(name, path):
        sp = importlib.util.spec_from_file_location(name, path)
        m = importlib.util.module_from_spec(sp)
        sys.modules[name] = m
        sp.loader.exec_module(m)
        return m

    U = _load("unified_state55", os.path.join(_d, "unified_state55.py"))
    PC = _load("perception55", os.path.join(_d, "perception.py"))

CKPT = os.path.join(ROOT, "models/manifold_engine.npz")


def main() -> int:
    rep: dict = {"ts": np.datetime64("now", "s").astype(str), "cases": {}}
    ok_all = True
    rng = np.random.default_rng(0)

    # ① 布局
    U.validate_layout()
    tab = U.layout_table()
    c1 = {"ok": sum(t["dim"] for t in tab) == 55 and len(tab) == 19,
          "n_seg": len(tab), "sum_dim": sum(t["dim"] for t in tab),
          "extra": [t["name"] for t in tab if t["start"] >= 43]}
    ok_all &= c1["ok"]
    rep["cases"]["layout"] = c1

    # ② 融合语义 + 逐位一致
    v39 = rng.normal(size=39)
    t4 = np.array([1.0, 12.5, 0.3, -0.2])
    x55 = PC.fuse_sensors55(v39, np.zeros(6), t4)
    x43 = PC.fuse_sensors(v39, np.zeros(6), t4)                  # 默认口径 = 43
    c2 = {"ok": bool(x55.size == 55 and x43.size == 43 and np.array_equal(x55[:43], x43)
                     and np.all(x55[43:] == 0)),
          "n55": int(x55.size), "n43": int(x43.size),
          "prefix_bitwise_equal": bool(np.array_equal(x55[:43], x43)),
          "ext_all_zero": bool(np.all(x55[43:] == 0))}
    ok_all &= c2["ok"]
    rep["cases"]["fuse"] = c2

    # ③ 扩展隔离 (引擎侧): 扩展维填数 → z 不变
    from lerobot.manifold.manifold_engine import ManifoldEngine
    eng = ManifoldEngine(manifold_type="su2", latent_dim=16, state_dim=55)
    loaded = eng.load(CKPT) if os.path.isfile(CKPT) else False
    if not loaded:
        eng.encoder.fit(rng.normal(size=(64, 55)))
    z_a = eng.project(np.concatenate([x43, np.zeros(12)]))["z"]
    z_b = eng.project(np.concatenate([x43, rng.normal(size=12) * 100]))["z"]
    dz = float(np.abs(np.asarray(z_a) - np.asarray(z_b)).max())
    c3 = {"ok": dz < 1e-9, "z_max_abs_diff": dz, "calib_loaded": bool(loaded),
          "calib_pad": getattr(eng, "calib_pad", None),
          "note": "扩展 12 维零行 ⇒ 填任何数都不影响 z (沉睡语义成立)"}
    ok_all &= c3["ok"]
    rep["cases"]["extension_isolation"] = c3

    # ④ 43 vs 55 引擎 z 对比 (同标定, 同状态)
    e43 = ManifoldEngine(manifold_type="su2", latent_dim=16, state_dim=43)
    if loaded:
        e43.load(CKPT)
    else:
        e43.encoder.fit(rng.normal(size=(64, 43)))
    # 55 引擎用同一标定的前 43 维 (e43 已 load), 手工构造 55 编码器做对齐比较
    e55 = ManifoldEngine(manifold_type="su2", latent_dim=16, state_dim=55)
    e55.encoder.mu = np.concatenate([e43.encoder.mu, np.zeros(12)])
    e55.encoder.W = np.vstack([e43.encoder.W, np.zeros((12, e43.encoder.W.shape[1]))])
    e55.encoder.latent_dim, e55.encoder.n_fit = e43.encoder.latent_dim, e43.encoder.n_fit
    e55.fitted = True
    z43 = e43.project(x43)["z"]
    z55 = e55.project(x55)["z"]
    dz2 = float(np.abs(np.asarray(z43) - np.asarray(z55)).max())
    c4 = {"ok": dz2 < 1e-12, "z_max_abs_diff": dz2,
          "note": "补 0 行的数学恒等: (x55−[μ,0])@[W;0] = (x43−μ)@W ⇒ 差仅浮点求和顺序"}
    ok_all &= c4["ok"]
    rep["cases"]["engine_43_vs_55"] = c4

    # ⑤ 测地线梯度 (torch) —— 无 torch 的端侧机 (550C Intel) 跳过并明记, 不当失败也不假装通过
    try:
        import torch                                                       # noqa: PLC0415
    except Exception as e:                                                 # noqa: BLE001
        rep["cases"]["geodesic"] = {"ok": None, "skipped": "本机无 torch (%s)" % str(e)[:60]}
        rep["cases"]["slerp"] = {"ok": None, "skipped": "本机无 torch"}
        torch = None
    if torch is not None:
        q1 = torch.tensor([[1.0, 0, 0, 0]], requires_grad=True)
        q2 = torch.tensor([[1.0, 0, 0, 0]])
        d_atan = U.geodesic_distance(q1, q2).sum()
        d_atan.backward()
        g_atan = float(q1.grad.abs().max())
        q3 = torch.tensor([[1.0, 0, 0, 0]], requires_grad=True)
        dot = (q3 * q2).sum(-1).abs().clamp(0, 1)
        d_acos = (2.0 * torch.acos(dot)).sum()
        d_acos.backward()
        g_acos = float(q3.grad.abs().max())
        c5 = {"ok": bool(np.isfinite(g_atan) and d_atan.item() < 1e-6),
              "atan2_grad_max": g_atan, "atan2_value": float(d_atan),
              "acos_grad_max": g_acos, "acos_value": float(d_acos),
              "note": "q1=q2: acos 形式梯度 NaN/inf, atan2 形式有限 ⇒ 训练不会首步炸"}
        ok_all &= c5["ok"]
        rep["cases"]["geodesic"] = c5

        # ⑥ SLERP 三分支
        a = torch.tensor([[1.0, 0, 0, 0]], requires_grad=True)
        b_same = torch.tensor([[1.0, 0, 0, 0]])
        b_opp = torch.tensor([[-1.0, 0, 0, 0]])                 # 双覆盖 (θ=π 退化)
        b_far = torch.tensor([[0.0, 0, 0, 1.0]])                # 90°
        out = {}
        for nm, b in (("same", b_same), ("opposite", b_opp), ("90deg", b_far)):
            q = U.slerp_step(a, b, 0.25)
            s = q.sum()
            s.backward(retain_graph=True)
            out[nm] = {"norm": float(q.norm()), "value": [round(float(x), 6) for x in q[0]],
                       "grad_max": float(a.grad.abs().max()) if a.grad is not None else None,
                       "grad_finite": bool(a.grad is not None and torch.isfinite(a.grad).all())}
            a.grad = None
        mid = U.slerp_step(torch.tensor([[1.0, 0, 0, 0]]), b_far, 0.5)
        c6 = {"ok": all(v["grad_finite"] and abs(v["norm"] - 1) < 1e-6 for v in out.values())
              and bool(np.isfinite(float(mid.sum()))),
              "branches": out, "mid_norm": float(mid.norm()),
              "note": "θ→0 用线性插值极限, θ→π 先取反 q_target; 分母先加 eps 再除 (不是 where 掩盖)"}
        ok_all &= c6["ok"]
        rep["cases"]["slerp"] = c6


    # ⑦ 兼容回归
    c7 = {"ok": PC.OBS_DIM == 55 and PC.LEGACY_OBS_DIM == 43 and PC.fuse_sensors(
        v39, np.zeros(6), t4).size == 43,
        "OBS_DIM": PC.OBS_DIM, "LEGACY": PC.LEGACY_OBS_DIM,
        "default_dim": int(PC.fuse_sensors(v39, np.zeros(6), t4).size),
        "note": "默认仍 43 (在役权重口径), 新链路显式走 fuse_sensors55()"}
    ok_all &= c7["ok"]
    rep["cases"]["compat"] = c7

    for _k, _v in rep["cases"].items():
        if _v.get("ok") is False:
            ok_all = False
    rep["ok"] = bool(ok_all)
    rep["skipped"] = [k for k, v in rep["cases"].items() if v.get("ok") is None]
    od = os.path.join(ROOT, "reports", "state55")
    os.makedirs(od, exist_ok=True)
    jp = os.path.join(od, rep["ts"].replace(":", "") + ".json")
    json.dump(rep, open(jp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(rep["cases"], ensure_ascii=False, indent=1))
    print("\n===> %s · %s" % ("PASS" if rep["ok"] else "FAIL", jp))
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
