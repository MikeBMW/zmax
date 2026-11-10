# -*- coding: utf-8 -*-
"""ss_lat — 节点实现正文 (文件名 = 画布节点: ss_lat)。

从 nodes/library.py 迁出 (2026-11-10 06:35)。老倪: 「是哪个节点, 就用哪个节点的名称」——
打开源码 / 下断点 / 改逻辑, 只面对这一个文件; library.py 只剩共享运行时和薄壳。

entry: node_ss_lat   ·   registry key: ss_lat
"""

# 共享运行时/辅助函数仍在 library.py —— 显式导入, 不搞 globals 注入
from .shared_runtime import (  # noqa: F401
    _CALIB_DIR,
    _SS_STATE,
    _load_mod,
    os,
)

def node_ss_lat(ctx):
    """🧮 潜空间 — 世界模型预测流形的标定 (维度/类别/速度场) + 观测有效维实测
    源码: src/lerobot/calibration/calibration_layer.py (LATENT_CALIB)
    地图导航视角: 潜空间=流形地图, 世界模型=导航仪 (沿速度场 prior A·x+B·u 推演);
    本节点 = 地图的几何标定 + 引擎校验: 对引擎轨迹 39D 观测做 PCA → 95% 方差有效维
    (数据流形固有维实测) vs 标定 latent_dim; 潜坐标/速度场向量取引擎真实 latent/prior。
    ⚠️ 维度/类别是引擎结构常数, 本节点只标定+校验, 不写引擎字面量 (改潜维=重构卡尔曼)。"""
    log = ctx.get("log")
    try:
        import numpy as np
        path = os.path.join(_CALIB_DIR, "calibration_layer.py")
        m = _load_mod("lerobot.calibration.calibration_layer", path)   # 正常 import (断点可绑)
        layer = m.CalibrationLayer()
        mod = ctx.get("module")
        tr = getattr(mod, "_ss_tr", None) if mod is not None else None
        if tr is None or not tr.get("t"):
            if log:
                log("⚠️ 潜空间: 无引擎轨迹 — 先点 ▶ 运行状态空间 (轨迹是数据真源)")
            return False
        idx = int(min(getattr(mod, "_ss_round", 0) or 0, len(tr["t"]) - 1))
        stage = str(tr["stage"][idx]).replace("阶段 ", "")
        # ── 潜坐标 (地图位置) + 速度场 (世界模型一步推演) — 引擎真实量 ──
        lat = np.asarray(tr.get("corrected_vec", tr["latent_vec"])[idx], dtype=float)
        lat_pred = np.asarray(tr["latent_vec"][idx], dtype=float)      # 估计器先验
        prior = np.asarray(tr.get("prior_vec", np.zeros(4))[idx], dtype=float)
        vel = prior - lat_pred                                          # 地图上速度场向量
        # ── 观测流形有效维实测: 全轨迹 39D 视觉观测 PCA (95% 累积方差) ──
        obs_all = np.asarray(tr["obs"], dtype=float)[:, :39]
        X = obs_all - obs_all.mean(axis=0)
        _, S, _ = np.linalg.svd(X, full_matrices=False)
        var = S ** 2 / max(float((S ** 2).sum()), 1e-12)
        cum = np.cumsum(var)
        eff_dim = int(np.searchsorted(cum, 0.95) + 1) if len(cum) else 0
        eff_dim99 = int(np.searchsorted(cum, 0.99) + 1) if len(cum) else 0
        # ── 校验: 标定陈述 vs 引擎实测 ──
        checks = []
        checks.append(f"标定潜维 {layer.lat['latent_dim']}D vs 引擎潜状态实际 {lat.size}D"
                      + (" ✓" if layer.lat["latent_dim"] == lat.size else " ✗ 标定过期"))
        checks.append(f"观测流形 {layer.lat['state_dim']}D → 轨迹有效维 {eff_dim}D@95% / "
                      f"{eff_dim99}D@99% (任务路径低维嵌入: 沿路径推进+夹爪; "
                      f"孔位/姿态常量维无方差)")
        _SS_STATE["latent_calib"] = {"idx": idx, "stage": stage, "latent": lat,
                                     "prior": prior, "vel": vel,
                                     "eff_dim": eff_dim, "eff_dim99": eff_dim99,
                                     "lat": dict(layer.lat)}
        # 端口: 画布 sslat.out1 → ssdec.in5(潜空间→动作头条件) / out2 → ss_mani_eng.in4
        #       / out3 → n_calib_mani.in2 (曲率/维度尺度)。原实现算完只 return True ⇒ 三路全空。
        _rb = {"kind": "latent", "layer": "L4", "ok": True,
               "idx": int(idx), "stage": stage, "t": round(float(tr["t"][idx]), 3),
               "latent": [round(float(x), 6) for x in np.asarray(lat, float).ravel()],
               "prior": [round(float(x), 6) for x in np.asarray(prior, float).ravel()],
               "vel": [round(float(x), 6) for x in np.asarray(vel, float).ravel()],
               "eff_dim": int(eff_dim), "eff_dim99": int(eff_dim99),
               "latent_dim": int(lat.size), "state_dim": int(layer.lat["state_dim"]),
               "flow_kind": str(layer.lat.get("flow_kind")),
               "prior_A": float(layer.lat.get("prior_A") or 0.0),
               "summary": str(layer.latent_summary())[:160],
               "src": "src/lerobot/middleware/nodes/impl/ss_lat.py::node_ss_lat"}
        if log:
            log(f"🧮 潜空间 (真实·t={tr['t'][idx]:.2f}s {stage}): 潜坐标 (位置3+预测力1)="
                f"{np.round(lat, 4)}")
            log(f"   速度场 (世界模型一步推演 prior−x̂₋): {np.round(vel, 4)} · "
                f"A={layer.lat['prior_A']:.1f} 恒速线性流形 ({layer.lat['flow_kind']})")
            log(f"   PCA 校验: " + " · ".join(checks))
            log(f"   标定: {layer.latent_summary()}")
        return {"out1": dict(_rb), "out2": dict(_rb), "out3": dict(_rb), **_rb}
    except Exception as e:
        if log:
            log(f"⚠️ 潜空间执行失败: {e}")
        return False


# 与既有 *_impl.py 同约定: 外部也可以 from ... import run
run = node_ss_lat
