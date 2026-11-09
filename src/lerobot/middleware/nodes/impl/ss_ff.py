# -*- coding: utf-8 -*-
"""ss_ff — 节点实现正文 (文件名 = 画布节点: ss_ff)。

从 nodes/library.py 迁出 (2026-11-10 06:35)。老倪: 「是哪个节点, 就用哪个节点的名称」——
打开源码 / 下断点 / 改逻辑, 只面对这一个文件; library.py 只剩共享运行时和薄壳。

entry: node_ss_s2   ·   registry key: ss_ff
"""

# 共享运行时/辅助函数仍在 library.py —— 显式导入, 不搞 globals 注入
from .shared_runtime import (  # noqa: F401
    _SS_STATE,
    _ss_ensure_obs43,
    _ss_env_obs,
    _ss_import,
)

def node_ss_s2(ctx):
    """并行处理层 — ⚡前馈加速器(FeedforwardAccelerator) / 🔮状态估计器(AdaptiveStateEstimator) (parallel.py)"""
    log = ctx.get("log")
    try:
        import numpy as np
        name = ctx.get("name", "")
        par = _ss_import("parallel")
        obs43 = _ss_ensure_obs43(log)
        if "估计" in name:
            est = par.AdaptiveStateEstimator()
            act4 = np.concatenate([_SS_STATE.get("u_prev", np.zeros(3)), [0.0]])
            lat = _SS_STATE.get("latent", obs43[:4])
            latent_pred = est.predict(np.asarray(lat, dtype=float), act4)
            # 🐛 2026-09-02 老倪: 估计器必须预测+校正闭环 — 原只 predict 没 update,
            #   "自适应状态估计器"的卡尔曼校正(用观测 z_k 修正先验)根本没执行, 名不副实
            obs39 = _SS_STATE.get("obs39")
            if obs39 is None:
                obs39, _ = _ss_env_obs(log)
            z_k = np.concatenate([obs39[0:3], [obs39[3]]])   # 观测: 手位置 + 夹爪开度 (与 latent 同维)
            latent = est.update(np.asarray(latent_pred, dtype=float), np.asarray(z_k, dtype=float))
            _SS_STATE["latent"] = np.asarray(latent, dtype=float)
            if log:
                log(f"🔮 状态估计器 (真实): predict→{np.round(latent_pred,4)} · "
                    f"update(K·(z−x̂₋))→latent={np.round(latent,4)} (parallel.py AdaptiveStateEstimator)")
            return {"out1": {"kind": "state_est", "latent": [float(x) for x in np.asarray(latent).ravel()],
                             "latent_pred": [float(x) for x in np.asarray(latent_pred).ravel()]},
                    "out2": None, "ok": True}
        accel = par.FeedforwardAccelerator()
        u_ff = accel.forward(obs43)
        # 🧠 2026-09-08 老倪目检实锤: 域外布局 forward 走解析守卫 → probe 空 → 直方图无数据。
        #   补一次真 MLP 前向仅填探针 (诊断通道, 不参与控制) — 直方图展示真实 MLP 激活。
        if not (accel.probe or {}).get("act_raw") and getattr(accel, "_ff", None) is not None:
            try:
                accel._ff(np.asarray(obs43[:39], dtype=np.float32))  # 覆盖探针 key+_seq 自增
            except Exception:
                pass
        _SS_STATE["u_ff"] = np.asarray(u_ff, dtype=float)
        _SS_STATE["ff_probe"] = accel.probe   # 🧠 探针缓存 (前馈激活直方图节点消费)
        if log:
            # 🧠 探针 (2026-09-04): 展示 MLP 在想什么 — 层活跃/能量 + 输出归因 top 单元
            _p = accel.probe
            if _p and "layers" in _p:
                _ls = _p["layers"]
                _act = " · ".join(f"L{i+1}:{l['active']}/{l['dim']}活 E={l['act_l2']:.1f}"
                                  for i, l in enumerate(_ls))
                _top = " · ".join(
                    f"u{d+1}←单元{j}({c:+.3f})" for d in range(3)
                    for j, c in _p["out_contrib"][d][:1])
                log(f"⚡ 前馈加速器 (真实): u_ff={np.round(u_ff,3)} · 🧠[{_act}] · 归因 {_top} "
                    f"(parallel.py; obs: 手{_p['obs']['hand']}→目标{_p['obs']['target']} d={_p['obs']['d_h']})")
            else:
                log(f"⚡ 前馈加速器 (真实): forward(obs43) → u_ff={np.round(u_ff,3)} (parallel.py)")
        # ⚠️ 2026-10-30 实锤两连坑: ① 直接返回 accel.probe → float32 不可 JSON 序列化;
        #   ② default=float 对 numpy **数组** 报 "only 0-dimensional arrays can be converted"。
        #   ⇒ 必须按类型分流 (ndarray→tolist / np标量→item), 否则壳 step 抛异常整节点废掉。
        import json as _js

        def _conv(o):
            try:
                if isinstance(o, np.ndarray):
                    return o.tolist()
                if isinstance(o, np.generic):
                    return o.item()
                return float(o)
            except Exception:                                          # noqa: BLE001
                return str(o)

        _probe = accel.probe if isinstance(accel.probe, dict) else {}
        _probe = _js.loads(_js.dumps(_probe, default=_conv))
        return {"out1": {"kind": "ff_probe", "probe": _probe},
                "out2": {"kind": "u_ff", "layer": "L2", "role": "前馈建议动作",
                         "u_ff": [round(float(x), 6) for x in np.asarray(u_ff).ravel()],
                         "w_ff": float((ctx.get("params") or {}).get("w_ff", 0.3)),
                         "source": "parallel.py FeedforwardAccelerator"},
                "ok": True}
    except Exception as e:
        if log:
            log(f"⚠️ 并行处理层真实执行失败: {e}")
        return {"out1": None, "out2": None, "ok": False, "error": str(e)}


# 与既有 *_impl.py 同约定: 外部也可以 from ... import run
run = node_ss_s2
