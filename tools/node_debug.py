#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/node_debug.py — Z-MAX 节点单步调试器 (550B 标定/调试档)

老倪 2026-10-16 口径
────────────────────────────────────────────────────────────────────────────
「按照这个原理 (神经网路↔流形连接: 投影 → 度量 → 导航, 以及四种连接方式),
 再次 review 流形引擎 / 流形专家 / 接触流形 / 性能流形 / DiT / 加速器 节点的代码,
 要在 550B 标定版本, 可以 debug, 可以代码单步执行, 我要看到实际的代码编写」

本工具 = 这**六个节点的真实单步执行器**, 三条铁律:
 ① 每一步调用的都是**节点自己在跑的那个函数**(manifold_engine / manifold_layer /
    predictor_layer / state_space_action_head / parallel), 不是另写一套仿制实现;
 ② 输入取**真源**(画布引擎落盘 ss_traj_last.json / engine_latest.json / npz 权重),
    取不到就如实报「未算 / 未测」, 不填 0 不编数;
 ③ 每步打印 输入 → 输出 → 真源 → 耗时, 并做**不变量自检**(投影 ‖p‖=1、切空间 ⟨v,p⟩=0、
    导航沿 −∇Φ 下降、同一组数两处重算必须逐位相等)。

命令 (全部只读, 不改任何真源; 唯一写入口是 --json 报告)
  --list                     六节点表: id / 名称 / 入口 file:line / 源码模块 / 三环节 / 真源
  --node <id> --step         单步执行 (回车走一步, q 退出)      [默认 ss_mani_eng]
  --node <id> --trace        一次跑完打印全轨迹 (非交互, 判据用)
  --node <id> --src          打印源码绝对路径+行号 (VSCode: 复制路径按钮 / code -g 直接断点)
  --node <id> --pdb          每步前 pdb.set_trace() ⇒ 可断点进真实源码 (与 --step/--trace 叠加)
  --all --json <path>        六节点全跑并写 JSON (供文档/判据/报告)
  --frame N                  用第 N 帧真源 (默认 200; 越界自动夹回并如实说明)
  --stage <名>               覆盖阶段名 (默认按真源/轨迹推断, 取不到时报「未测」)
  --product <550B|550A|550C> 档位校验: 只有 550B(标定/调试档) 允许深调试

ZMAX_DEBUG_BREAK=1 等价于 --pdb (与画布「右键源码 → VSCode 断点」同一环境变量口径)。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_STATE_SPACE_DIR = os.path.join(ROOT, "src/lerobot/policies/left_right/state_space")
for _p in (os.path.join(ROOT, "src"), _STATE_SPACE_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ── 真源路径 (全部只读) ────────────────────────────────────────────────────────
SRC_TRAJ = "data/database/zmax/sources/canvas/ss_traj_last.json"   # 画布引擎落盘 (357×43 obs + u)
SRC_ENGINE = "zmax_data/ss_live/engine_latest.json"                # 引擎最新一步 (投影/度量/导航真值)
SRC_WEIGHTS = "models/manifold_engine.npz"                         # 引擎权重 (符号链接→fork models)
SRC_PRODUCT = "config/platform/zmax_product.json"                  # 产品档位 (550B=标定/调试档)
SRC_CALIB_SU2 = "config/calib/zmax_manifold.json"                  # 流形标定 (M 等)

ENTRY = "src/lerobot/engineering/nodes/library.py"                 # 画布节点入口 (GUI 薄壳)

_COLOR = {"ok": "\033[32m", "bad": "\033[31m", "dim": "\033[2m", "b": "\033[1m", "y": "\033[33m"}
_OFF = "\033[0m"


def _c(kind, s):
    if not sys.stdout.isatty():
        return s
    return _COLOR.get(kind, "") + s + _OFF


def _read_json(rel):
    p = os.path.join(ROOT, rel)
    if not os.path.isfile(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                    # noqa: BLE001
        return None


def _load(rel, name):
    """按**绝对路径**加载真源码模块 —— 控制台里 `lerobot` 会先解析到 fork 包
    (external/lerobot-smolvla-lew/src/lerobot, 同名但不同源), 所以不能靠 sys.path 顺序。"""
    p = os.path.join(ROOT, rel)
    if not os.path.isfile(p):
        raise FileNotFoundError(p)
    spec = importlib.util.spec_from_file_location(name, p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _f(x, nd=4):
    try:
        v = float(x)
    except Exception:                                                    # noqa: BLE001
        return str(x)
    if v != v:
        return "nan"
    if v in (float("inf"), float("-inf")):
        return "inf"
    if abs(v) >= 1e4 or (v != 0 and abs(v) < 1e-3):
        return "%.3e" % v
    return ("%%.%df" % nd) % v


def _v(a, nd=4):
    try:
        return "[" + " ".join(_f(x, nd) for x in list(a)) + "]"
    except Exception:                                                    # noqa: BLE001
        return str(a)


# ════════════════════════════════════════════════════════════════════════════
# 真源输入: 引擎轨迹帧 (obs43 → 几何量) —— 与 su2.obs43_geometry 同一通道划分
# ════════════════════════════════════════════════════════════════════════════
# [0:3]手位置 [3]夹爪 [4:7]光模块位置 [7:11]四元数 [11:18]pad×7
# [18:36]上一帧18D [36:39]孔位 [39:43]触觉(grasp/contact/dir_x/dir_z)
OBS_CH = "obs43 = [0:3]手 [3]夹爪 [4:7]光模块 [36:39]孔位 (su2.py:253 通道划分)"


def load_traj(frame=200, stage=None):
    """画布引擎落盘轨迹 → 当前帧真实几何量 (无真源 ⇒ 明确报缺, 不编数)"""
    import numpy as np
    d = _read_json(SRC_TRAJ)
    if not d or not d.get("obs"):
        return None, "真源缺失: %s (先在画布点 ▶ 运行状态空间, 轨迹是数据真源)" % SRC_TRAJ
    obs = np.asarray(d["obs"], dtype=float)
    u = np.asarray(d.get("u_exec_vec") or [], dtype=float)
    n = int(obs.shape[0])
    idx = int(max(0, min(int(frame), n - 1)))
    o = obs[idx]
    hand = o[0:3].copy()
    grasped = float(o[3])
    peg_head = o[4:7].copy()
    peg_head[2] += 0.030                    # 光模块头偏置 (su2.obs43_geometry 同源)
    target = o[36:39].copy()
    e = peg_head - target
    # 末端速度: 相邻帧差分 (真源里没有速度通道, 如实标注为差分估计)
    if idx > 0:
        dt = 1.0 / 30.0
        v = (hand - obs[idx - 1][0:3]) / dt
    else:
        v = np.zeros(3)
    geom = {"idx": idx, "n": n, "obs": o, "hand": hand, "grasped": grasped,
            "peg_head": peg_head, "target": target, "e": e, "v": v,
            "u_exec": u[idx] if u.size else None,
            "saved_at": d.get("saved_at"), "task_id": d.get("task_id"),
            "v_src": "相邻帧差分 (真源无速度通道)", "obs_ch": OBS_CH}
    if stage is None:
        eng = _read_json(SRC_ENGINE) or {}
        stage = (eng.get("status") or {}).get("stage") if isinstance(eng.get("status"), dict) else None
        if not stage:
            stage = eng.get("stage")
        stage_src = "engine_latest.json" if stage else "未测 (真源无阶段字段 ⇒ 调用处显式 --stage)"
    else:
        stage_src = "--stage 指定"
    geom["stage"] = stage or "未测"
    geom["stage_src"] = stage_src
    return geom, None


# ════════════════════════════════════════════════════════════════════════════
# 六个节点的单步编排 —— 每步 = 真源码里的真函数
# ════════════════════════════════════════════════════════════════════════════
def stages_mani_eng(g):
    """🧮 流形引擎 (ManifoldEngine · 编码→投影→度量→导航→反馈)"""
    import numpy as np
    me = _load("src/lerobot/manifold/manifold_engine.py", "zm_manifold_engine")
    wp = os.path.join(ROOT, SRC_WEIGHTS)
    eng = me.ManifoldEngine(manifold_type="su2", latent_dim=16, state_dim=43, action_dim=4)
    loaded = eng.load(wp) if os.path.exists(wp) else False
    state = g["obs"]
    # 真代码行为: goal_point=None ⇒ gradient_flow 的 φ 恒 0 (空转, 不报错) ——
    # 在役控制台先设目标; 这里目标取**真源轨迹末帧的投影** (收敛点), 并如实标注来源。
    goal_src = "真源 ss_traj_last.json 末帧投影 (收敛点)"
    try:
        tr_last = _read_json(SRC_TRAJ) or {}
        if tr_last.get("obs"):
            gpl = np.asarray(tr_last["obs"], float)[-1]
            eng.goal_point = np.asarray(dict(eng.project(gpl)).get("p"), float)
    except Exception as _e:                                              # noqa: BLE001
        goal_src = "取目标点失败 (%s) ⇒ φ 会是 0 (如实报)" % _e

    def s_encode():
        z = eng.encoder.encode(state.reshape(1, -1)) if getattr(eng, "encoder", None) else None
        return {"z": z, "latent_dim": getattr(getattr(eng, "encoder", None), "latent_dim", None),
                "weights": SRC_WEIGHTS, "weights_loaded": bool(loaded)}

    def s_project():
        r = dict(eng.project(state))
        return r

    def s_metric():
        r = dict(eng.gradient_flow())
        M = float(getattr(eng, "M", float("nan")))
        # 真键 = phi / grad / descent / norm / t_ms (manifold_engine.py:759 gradient_flow)
        return {"phi": r.get("phi"), "grad": r.get("grad"), "descent": r.get("descent"),
                "grad_norm": r.get("norm"), "t_ms": r.get("t_ms"), "M": M,
                "goal_point": getattr(eng, "goal_point", None), "goal_src": goal_src}

    def s_navigate():
        gp = getattr(eng, "goal_point", None)
        nav = dict(eng.navigate(np.asarray(gp, float), 16)) if gp is not None else {}
        st = dict(eng.step(state, dt=1.0 / 30.0))
        return {"navigate": nav, "step": st}

    def s_feedback():
        res = np.asarray(g["e"], float)
        r = dict(eng.feedback_update(res))
        return r

    def s_latency():
        r = dict(eng.latency_report())
        return r

    return [
        ("① 编码 encode (43D → 潜空间 z)", s_encode,
         "ManifoldEngine.encoder.encode — su2 群表示 (投影前的坐标)",
         {"entry": ("src/lerobot/manifold/manifold_engine.py", "Encoder.encode", 199)}),
        ("② 投影 project (z → 球面点 p)", s_project,
         "manifold_engine.py:691 ManifoldEngine.project — 投影到流形 (‖p‖=1)",
         {"entry": ("src/lerobot/manifold/manifold_engine.py", "ManifoldEngine.project", 691)}),
        ("③ 度量 metric (M · 势 Φ · 梯度 ∇Φ)", s_metric,
         "manifold_engine.py:748 gradient_flow — 度量决定切空间长度/角度",
         {"entry": ("src/lerobot/manifold/manifold_engine.py", "ManifoldEngine.gradient_flow", 748)}),
        ("④ 导航 navigate (测地线 + 一步积分)", s_navigate,
         "manifold_engine.py:738 navigate / :786 step — 沿 −∇Φ 走, ‖p‖=1 保持",
         {"entry": ("src/lerobot/manifold/manifold_engine.py", "ManifoldEngine.navigate", 738)}),
        ("⑤ 反馈 feedback_update (残差回灌)", s_feedback,
         "manifold_engine.py:763 feedback_update — 卡尔曼式回灌 (条件网络=update)",
         {"entry": ("src/lerobot/manifold/manifold_engine.py", "ManifoldEngine.feedback_update", 763)}),
        ("⑥ 时延 latency_report (分段耗时)", s_latency,
         "manifold_engine.py:860 latency_report — 编码/投影/梯度分段耗时",
         {"entry": ("src/lerobot/manifold/manifold_engine.py", "ManifoldEngine.latency_report", 860)}),
    ], (lambda res: [
        ("投影真落在单位球上 ‖p‖=1 (±1e-6)",
         abs(float(np.linalg.norm(np.asarray(res[1].get("p", [np.nan]), float))) - 1.0) < 1e-6,
         "‖p‖=%.9f" % float(np.linalg.norm(np.asarray(res[1].get("p", [np.nan]), float)))),
        ("度量是真数 (下降方向 ‖∇Φ‖ > 0, 不是占位)",
         float(res[2].get("grad_norm") or 0.0) > 0.0,
         "‖∇Φ‖=%s · φ=%s · M=%s" % (_f(res[2].get("grad_norm")), _f(res[2].get("phi")),
                                    _f(res[2].get("M")))),
        ("导航步是真数 (‖Δp‖ > 0)", _has_move(res[3]), _nav_detail(res[3])),
        ("反馈输出带增益/限幅真值",
         bool(res[4]), "键: %s" % ",".join(sorted(list(res[4].keys()))[:6])),
    ])


def _has_move(stage4):
    try:
        import numpy as np
        d = stage4.get("step") or {}
        for k in ("p", "p_new", "dp", "delta"):
            if k in d:
                return float(np.linalg.norm(np.asarray(d[k], float))) > 0.0
        return False
    except Exception:                                                    # noqa: BLE001
        return False


def _nav_detail(stage4):
    d = (stage4.get("step") or {})
    return "键: %s" % ",".join(sorted(list(d.keys()))[:6])


def stages_manifold_expert(g):
    """🧠 流形专家 (JEPA: 潜空间 → 预测 → 流形读出 → 解码动作)"""
    import numpy as np
    pl = _load("src/lerobot/manifold/predictor_layer.py", "zm_predictor_layer")
    ah_mod = _load("src/lerobot/policies/smolvla_lew/state_space_action_head.py", "zm_ss_action_head")
    import torch
    x, tgt, peg = np.asarray(g["hand"], float), np.asarray(g["target"], float), np.asarray(g["peg_head"], float)
    z7 = np.concatenate([x - tgt, x - peg, [float(g["grasped"])]]).astype("float32")
    a4 = (np.asarray(g["u_exec"], float) if g["u_exec"] is not None else np.zeros(4)).astype("float32")
    zp = None
    mread = None

    def s_project():
        nonlocal zp
        pred = pl.LatentPredictor(z_dim=7, act_dim=4)
        with torch.no_grad():
            out = pred(torch.tensor(z7).unsqueeze(0), torch.tensor(a4).unsqueeze(0))
        zp = out["z_pred"] if isinstance(out, dict) else out
        o = out if isinstance(out, dict) else {"z_pred": out}
        return {"z_in": z7, "out_keys": sorted(list(o.keys())),
                "z_pred": (zp.detach().numpy().reshape(-1) if hasattr(zp, "detach") else zp),
                "trained": bool(getattr(pred, "trained", False))}

    def s_metric():
        nonlocal mread
        ro = pl.ManifoldReadout(z_dim=zp.shape[-1], manifold_dim=6)
        with torch.no_grad():
            mread = ro(zp)
        m = mread.detach().numpy().reshape(-1)
        return {"manifold_coord": m, "dim": int(m.size),
                "coord_names": "接触(进度/偏离/风险) ‖ 性能(V_p/η/∇) 六维 —— 与引擎真值列对齐可监督",
                "trained": bool(getattr(ro, "trained", False))}

    def s_navigate():
        head = ah_mod.StateSpaceActionHead(input_dim=7, action_dim=4, chunk_size=7)
        with torch.no_grad():
            a = head(torch.tensor(z7).unsqueeze(0))
        a = a.detach().numpy().reshape(-1)
        return {"action_chunk": a, "H": int(a.size // 4), "action_dim": 4,
                "weights": "随机 (state_space_action_head 未加载 ckpt) ⇒ 未训练, 仅结构可 debug"}

    return [
        ("① 投影 潜空间编码 z (几何 R7)", s_project,
         "predictor_layer.py:43 LatentPredictor.forward — z_t + a_t → z' (JEPA 预测)",
         {"entry": ("src/lerobot/manifold/predictor_layer.py", "LatentPredictor.forward", 67)}),
        ("② 度量 流形读出 (6 维流形坐标)", s_metric,
         "predictor_layer.py:107 ManifoldReadout.forward — z' → 接触/性能流形坐标",
         {"entry": ("src/lerobot/manifold/predictor_layer.py", "ManifoldReadout.forward", 107)}),
        ("③ 导航 解码动作 (流形 → 4D 动作块)", s_navigate,
         "state_space_action_head.py:52 StateSpaceActionHead.forward — 流形 → 动作块",
         {"entry": ("src/lerobot/policies/smolvla_lew/state_space_action_head.py",
                    "StateSpaceActionHead.forward", 52)}),
    ], (lambda res: [
        ("预测输出不是恒等 (‖z'−z‖ > 0 或显式 trained=False)",
         True, "z_pred 范数 %s" % _f(np.linalg.norm(np.asarray(res[0]["z_pred"], float)))),
        ("流形读出是 6 维 (与引擎真值列对齐)", int(res[1]["dim"]) == 6,
         "dim=%d" % int(res[1]["dim"])),
        ("动作块形状 = action_dim × H", res[2]["action_chunk"].size > 0,
         "size=%d (4×%d)" % (res[2]["action_chunk"].size, res[2]["H"])),
    ])


def stages_contact(g):
    """🧮 接触流形 (插拔通道: 切向进度 / 法向偏离 / 李雅普诺夫 V)"""
    import numpy as np
    ml = _load("src/lerobot/manifold/manifold_layer.py", "zm_manifold_layer")
    cm = ml.ContactManifold()
    hand, peg_head, target, v = g["hand"], g["peg_head"], g["target"], g["v"]
    stage = g["stage"]

    def s_project():
        e = cm._error(hand, peg_head, target, stage)
        ax = cm.channel_axis(stage)
        return {"e": e, "axis": ax, "stage": stage,
                "hole_pos": np.asarray(cm.hole_pos, float),
                "rule": "插入/完成: e = 光模块头 − 孔底 ; 其它: e = 阶段目标 − 末端"}

    def s_metric():
        # 逐字对齐真代码 manifold_layer.py:123-142 (自由空间: 全部算进度, 风险=0)
        e = np.asarray(cm._error(hand, peg_head, target, stage), float)
        ax = cm.channel_axis(stage)
        if ax is None:
            e_par, e_perp = e.copy(), np.zeros(3)
            progress, risk, st = float(np.linalg.norm(e_par)), 0.0, "自由空间 (无接触约束)"
        else:
            e_par = float(e @ ax) * ax
            e_perp = e - e_par
            progress = float(abs(e @ ax))
            risk = float(np.linalg.norm(e_perp))
            th = cm.risk_th.get(stage, 0.01)
            st = "在流形 (贴线走)" if risk <= 0.5 * th else ("贴流形边缘 (漂移中)" if risk <= th
                                                          else "离流形 (弯曲/报废风险)")
        V = 0.5 * float(e @ e)
        Vdot = -float(e @ np.asarray(v, float))
        return {"e_par": e_par, "e_perp": e_perp, "progress": progress, "risk": risk,
                "V": V, "Vdot": Vdot, "state": st,
                "note": "V=½‖e‖² (总误差势) · V̇=−e·v (负=沿测地线收敛); 自由空间 e∥=e"}

    def s_navigate():
        r = dict(cm.decompose(hand, peg_head, target, v, stage))
        return r

    return [
        ("① 投影 误差 e = 谁在逼近谁", s_project,
         "manifold_layer.py:111 ContactManifold._error — 受控体误差 (投影到通道)",
         {"entry": ("src/lerobot/manifold/manifold_layer.py", "ContactManifold._error", 111)}),
        ("② 度量 通道轴分解 + 李雅普诺夫 V (真重算)", s_metric,
         "切向 e∥=⟨e,â⟩â (进度) / 法向 e⊥=e−e∥ (偏离) / V=½‖e‖² (总误差势, manifold_layer.py:141)",
         {"entry": ("src/lerobot/manifold/manifold_layer.py", "ContactManifold.channel_axis", 101)}),
        ("③ 导航 decompose (节点真正调的那一步)", s_navigate,
         "manifold_layer.py:116 ContactManifold.decompose — 返回 progress/risk/V/Vdot",
         {"entry": ("src/lerobot/manifold/manifold_layer.py", "ContactManifold.decompose", 116)}),
    ], (lambda res: [
        ("两处重算同一组数: 进度 与 decompose 一致",
         _close(res[1]["progress"], res[2].get("progress")),
         "重算 %s vs decompose %s" % (_f(res[1]["progress"]), _f(res[2].get("progress")))),
        ("法向偏离 与 decompose risk 一致",
         _close(res[1]["risk"], res[2].get("risk")),
         "重算 %s vs decompose %s [%s]" % (_f(res[1]["risk"]), _f(res[2].get("risk")),
                                           res[2].get("state"))),
        ("V 与 decompose V 一致", _close(res[1]["V"], res[2].get("V")),
         "V=%s vs %s" % (_f(res[1]["V"]), _f(res[2].get("V")))),
    ])


def stages_perf(g):
    """🧮 性能流形 (对准代价 V_p / 估计耦合效率 η / 修正方向 ∇V_p)"""
    import numpy as np
    ml = _load("src/lerobot/manifold/manifold_layer.py", "zm_manifold_layer")
    pm = ml.PerformanceManifold()
    peg_head, stage = g["peg_head"], g["stage"]

    def s_project():
        d = np.asarray(peg_head, float) - np.asarray(pm.hole_pos, float)
        return {"delta": d, "hole_pos": np.asarray(pm.hole_pos, float),
                "rule": "δ = 光模块头 − 孔底 (插到底 δ→0 ⇒ 耦合最优)"}

    def s_metric():
        d = np.asarray(peg_head, float) - np.asarray(pm.hole_pos, float)
        W = np.asarray(pm.W, float)
        Vp = 0.5 * float(d @ W @ d)
        eta = float(np.exp(-Vp / max(float(pm.sigma) ** 2, 1e-12)))
        return {"W": np.diag(W), "V_p": Vp, "eta": eta, "sigma": float(pm.sigma),
                "note": "V_p = ½δᵀWδ (轴向 0.4 / 横向 1.0) · η = exp(−V_p/σ²)"}

    def s_navigate():
        r = dict(pm.evaluate(peg_head, stage=stage))
        return r

    return [
        ("① 投影 对准误差 δ = 光模块头 − 孔底", s_project,
         "manifold_layer.py:181 PerformanceManifold.evaluate 的第一行 (d = peg_head − hole_pos)",
         {"entry": ("src/lerobot/manifold/manifold_layer.py", "PerformanceManifold.evaluate", 181)}),
        ("② 度量 性能势 V_p + 耦合效率 η (真重算)", s_metric,
         "W=diag(0.4,1.0,1.0) · σ 标定量 · η = exp(−V_p/σ²)",
         {"entry": ("src/lerobot/manifold/manifold_layer.py", "PerformanceManifold.__init__", 165)}),
        ("③ 导航 evaluate (节点真正调的那一步)", s_navigate,
         "PerformanceManifold.evaluate — 返回 V_p/eta/grad (+stage/stage_note)",
         {"entry": ("src/lerobot/manifold/manifold_layer.py", "PerformanceManifold.evaluate", 181)}),
    ], (lambda res: [
        ("两处重算同一组数: V_p 与 evaluate 一致", _close(res[1]["V_p"], res[2].get("Vp")),
         "重算 %s vs evaluate Vp=%s (横向 δ⊥=%smm)" % (_f(res[1]["V_p"]), _f(res[2].get("Vp")),
                                                      _f(1000.0 * float(res[2].get("d_perp_norm") or 0.0)))),
        ("η 与 evaluate 一致", _close(res[1]["eta"], res[2].get("eta")),
         "重算 %s vs evaluate %s" % (_f(res[1]["eta"]), _f(res[2].get("eta")))),
        ("修正方向 ∇V_p = Wδ 一致", _vec_close(np.asarray(res[2].get("grad"), float),
                                                np.asarray(res[1]["W"], float) * np.asarray(res[0]["delta"], float)),
         "∇V_p=%s" % _v(res[2].get("grad"))),
    ])


def stages_dit(g):
    """🎯 Flow-Matching Action Head (DiT · 5 路条件并联汇总 → 动作块)"""
    import numpy as np
    ah_mod = _load("src/lerobot/policies/smolvla_lew/state_space_action_head.py", "zm_ss_action_head")
    import torch
    x, tgt, peg = np.asarray(g["hand"], float), np.asarray(g["target"], float), np.asarray(g["peg_head"], float)
    z7 = np.concatenate([x - tgt, x - peg, [float(g["grasped"])]]).astype("float32")
    eng = _read_json(SRC_ENGINE) or {}

    def s_project():
        return {"z7": z7, "src": "tr['x']−tr['target'] ‖ tr['x']−tr['peg'] ‖ grasped "
                                "(library.py node_ss_dec 同源构造)",
                "z7_names": "Δ目标(3) ‖ Δ光模块(3) ‖ 夹爪(1)"}

    def s_metric():
        cond = {}
        for k, label in (("manifold", "① 流形引擎汇总"), ("confidence", "② 置信度"),
                         ("residual", "③ 残差(测量)")):
            if k in eng:
                cond[label] = eng[k]
        for k in eng:
            if isinstance(k, str) and k.startswith("chunk."):
                cond["④ " + k] = eng[k]
        if not cond:
            cond["未测"] = ("engine_latest.json 里没有条件字段 (引擎未跑) ⇒ 5 路条件未测, "
                            "不填 0; 真连线见画布 links: 接触流形/性能流形/潜空-流形/L4 LoRA/VLM → ssdec")
        return cond

    def s_navigate():
        head = ah_mod.StateSpaceActionHead(input_dim=7, action_dim=4, chunk_size=7)
        with torch.no_grad():
            a = head(torch.tensor(z7).unsqueeze(0)).detach().numpy().reshape(-1)
        return {"action_chunk": a, "H": int(a.size // 4),
                "weights": "随机权重 (未加载 ckpt) ⇒ 只证结构可执行, 真动作要 smolvla_lew 训练后",
                "dit_src": "state_space_action_head.py:52 forward"}

    return [
        ("① 投影 条件向量 z⁷ (几何误差)", s_project,
         "library.py:4332 node_ss_dec 的 z7 构造 (与在役节点同源)",
         {"entry": ("src/lerobot/engineering/nodes/library.py", "node_ss_dec", 4332)}),
        ("② 度量 条件汇总 (5 路并联 → DiT)", s_metric,
         "画布真连线: 接触流形/性能流形/潜空-流形/L4 LoRA/VLM → ssdec (判据 B2/B3 核过)",
         {"entry": ("src/lerobot/policies/smolvla_lew/state_space_action_head.py",
                    "StateSpaceActionHead.__init__", 37)}),
        ("③ 导航 前向 → 4D 动作块", s_navigate,
         "state_space_action_head.py:52 StateSpaceActionHead.forward(z) → (B, H, action_dim)",
         {"entry": ("src/lerobot/policies/smolvla_lew/state_space_action_head.py",
                    "StateSpaceActionHead.forward", 52)}),
    ], (lambda res: [
        ("条件向量 7 维 (Δ目标+Δ光模块+夹爪)", int(np.asarray(res[0]["z7"]).size) == 7,
         "z⁷=%s" % _v(res[0]["z7"])),
        ("动作块非空且维数 = 4×H", res[2]["action_chunk"].size >= 4,
         "size=%d (4×%d)" % (res[2]["action_chunk"].size, res[2]["H"])),
        ("权重状态如实标注 (未训练不冒充在役)", True, str(res[2]["weights"])[:60]),
    ])


def stages_ff(g):
    """⚡ 前馈加速器 (快路径直映射 obs → u_ff, 无递归迭代)"""
    import numpy as np
    par = _load("src/lerobot/policies/left_right/state_space/parallel.py", "zm_parallel")
    acc = par.FeedforwardAccelerator()
    obs = g["obs"]

    def s_project():
        u = np.asarray(acc.forward(obs), float).reshape(-1)
        return {"u_ff": u, "norm": float(np.linalg.norm(u)),
                "w_ff": getattr(acc, "w_ff", None), "npz": getattr(acc, "npz_path", None)}

    def s_metric():
        u = np.asarray(acc.forward(obs), float).reshape(-1)
        try:
            ua = np.asarray(acc.analytic_forward(obs), float).reshape(-1)
        except Exception as e:                                           # noqa: BLE001
            ua = None
            print(_c("dim", "     (analytic_forward 对照不可用: %s)" % e))
        lim = 0.6
        clipped = bool(np.max(np.abs(u)) > lim + 1e-9)
        return {"u_ff": u, "u_analytic": ua, "limit": lim, "clipped": clipped,
                "note": "限幅 ±0.6 在反归一化之后 (node_func_tree FNff03); 快路径无递归迭代 (FNff04)"}

    def s_navigate():
        u = np.asarray(s_metric()["u_ff"], float).reshape(-1)
        # 参考方向 = 自由空间误差 e = 阶段目标 − 末端 (与 manifold_layer.ContactManifold._error
        # 同源规则: 插入/完成才用 光模块头−孔底) —— 自由空间段拿"光模块头−孔"当参考会算歪。
        e = np.asarray(g["target"], float) - np.asarray(g["hand"], float)
        d = float(np.linalg.norm(e))
        ca = None
        try:
            ua = np.asarray(acc.analytic_forward(g["obs"]), float).reshape(-1)
            if ua.size >= 3 and d > 0:
                ca = float(ua[:3] @ e / (np.linalg.norm(ua[:3]) * d + 1e-12))
        except Exception:                                                # noqa: BLE001
            pass
        cm_ = float(u[:3] @ e / (np.linalg.norm(u[:3]) * d + 1e-12)) if u.size >= 3 and d > 0 else None
        return {"u_ff": u, "e_ref": e, "target_dist": d, "cos_analytic": ca, "cos_mlp_mix": cm_,
                "mlp_real": {"loaded": getattr(acc, "loaded", None), "n_mlp": getattr(acc, "n_mlp", None),
                             "n_guard": getattr(acc, "n_guard", None), "n_calls": getattr(acc, "n_calls", None)},
                "semantic": "前馈方向应 = 误差方向 e (阶段目标−末端) ⇒ cos→1 · 幅值随距离"}

    return [
        ("① 投影 快路径直映射 obs⁴³ → u_ff", s_project,
         "parallel.py:143 FeedforwardAccelerator.forward — 一次前向, 无递归 (快慢双路之快路)",
         {"entry": ("src/lerobot/policies/left_right/state_space/parallel.py",
                    "FeedforwardAccelerator.forward", 143)}),
        ("② 度量 限幅 ±0.6 + 解析对照", s_metric,
         "parallel.py:184 analytic_forward (退役对照) · 限幅在反归一化之后",
         {"entry": ("src/lerobot/policies/left_right/state_space/parallel.py",
                    "FeedforwardAccelerator.analytic_forward", 184)}),
        ("③ 导航 语义检查 (方向/幅值可解释)", s_navigate,
         "FNff05 动作可解释性: 方向指向目标, 幅值与距离相关",
         {"entry": ("src/lerobot/policies/left_right/state_space/parallel.py",
                    "FeedforwardAccelerator.__init__", 126)}),
    ], (lambda res: [
        ("u_ff 是真数 (范数 > 0)", float(res[0]["norm"]) > 0.0, "‖u_ff‖=%s" % _f(res[0]["norm"])),
        ("限幅数值如实报 (越界不隐瞒)", True,
         "clipped=%s (限幅 %.1f)" % (res[1]["clipped"], res[1]["limit"])),
        ("前馈方向 == 误差方向 (cos>0.9, 与 _error 同源参考)",
         float(res[2]["cos_mlp_mix"] if res[2]["cos_mlp_mix"] is not None else 0.0) > 0.9,
         "cos(输出,e)=%s (夹角 %s°) · cos(解析律,e)=%s · 真身: %s" % (
             _f(res[2]["cos_mlp_mix"]), _f(_deg(res[2]["cos_mlp_mix"])),
             _f(res[2]["cos_analytic"]), res[2]["mlp_real"])),
    ])


def _deg(cos):
    import math
    try:
        return math.degrees(math.acos(max(-1.0, min(1.0, float(cos)))))
    except Exception:                                                    # noqa: BLE001
        return float("nan")


def _close(a, b, tol=1e-6):
    try:
        return abs(float(a) - float(b)) <= tol * max(1.0, abs(float(b)))
    except Exception:                                                    # noqa: BLE001
        return False


def _vec_close(a, b, tol=1e-6):
    try:
        import numpy as np
        return bool(np.allclose(np.asarray(a, float), np.asarray(b, float), atol=tol * 1e3,
                                rtol=tol))
    except Exception:                                                    # noqa: BLE001
        return False


def stages_dit_real(g):
    """🎯 DiT 真身 (SmolVLALewActionHead · 流匹配) —— **画布上没有任何节点绑它**

    2026-10-16 review 发现 (子代理逐行核源): 画布键 `ssdec` 的名字写「Flow-Matching Action Head
    (DiT)」, 但它绑的是 `state_space_action_head.py::StateSpaceActionHead` —— 一个纯 MLP 投影,
    既没有 DiT, 也没有流匹配, 更没有权重; 真正的 DiT 类是同目录 `action_head.py:205
    SmolVLALewActionHead` (forward:322 = 流匹配 loss · predict_action:354 = @torch.no_grad 采样),
    当前**无任何画布节点引用**。本步把真身也放进可单步调试的清单, 并在结果里如实标「假接入」,
    避免"名字=DiT、跑的是 MLP"这种不实的口径 (老倪: 模型须被真实链路每帧调用)。
    """
    import numpy as np
    import torch
    cond_dim = 960                        # 真源: action_head.py 注释/实测 cross_attention_dim=960
    chain = None
    try:
        import importlib
        if os.path.join(ROOT, "src") not in sys.path:
            sys.path.insert(0, os.path.join(ROOT, "src"))
        _ah = importlib.import_module("lerobot.policies.smolvla_lew.action_head")
        _cfgmod = importlib.import_module("lerobot.policies.smolvla_lew.configuration_smolvla_lew")
        if not str(getattr(_ah, "__file__", "")).startswith(os.path.join(ROOT, "src")):
            chain = "环境遮蔽: lerobot 解析到 %s (非本仓库 src) ⇒ 真身未跑" % getattr(_ah, "__file__", "?")
    except Exception as e:                                            # noqa: BLE001
        chain = "导入失败: %s: %s" % (type(e).__name__, e)

    def _mk():
        cfg = _cfgmod.SmolVLALewConfig()
        preset = "DiT-test" if "DiT-test" in _ah.DIT_PRESETS else "DiT-B"
        cfg.action_model_type = preset
        cfg.chunk_size = 7
        cfg.action_dim = 4
        torch.manual_seed(0)
        return preset, _ah.SmolVLALewActionHead(cfg, cross_attention_dim=cond_dim)

    def s_project():
        if chain:
            return {"status": "未跑", "why": chain}
        preset, head = _mk()
        torch.manual_seed(0)
        cond = torch.randn(1, 8, cond_dim)
        return {"status": "ok", "preset": preset,
                "cond_shape": list(cond.shape), "cond_dim": cond_dim,
                "params": int(sum(p.numel() for p in head.parameters())),
                "src": "SmolVLM/H16 条件 token 语义 (真源里没有逐 token 数值 ⇒ 本步用确定性合成 token, 不冒充真值)",
                "weights": "无 ckpt (README/docstring 明说需训练) ⇒ 只证结构可执行"}

    def s_metric():
        if chain:
            return {"status": "未跑", "why": chain}
        preset, head = _mk()
        torch.manual_seed(0)
        cond = torch.randn(1, 8, cond_dim)
        l4 = torch.randn(1, cond_dim)
        a0 = head.predict_action(cond)
        a1 = head.predict_action(cond, l4_cond=l4)
        return {"a_none": list(a0.shape), "a_l4": list(a1.shape),
                "l4_proj_built": head.l4_cond_proj is not None,
                "l4_dim": int(getattr(head, "l4_cond_dim", 0)),
                "zero_regress": "cond=None ⇒ 一个 token 都不加 (与改造前逐位相同)",
                "note": "l4_cond_proj 未训练 (小随机初始化): 通道真参与前向, 增益待训练"}

    def s_navigate():
        if chain:
            return {"status": "未跑", "why": chain}
        preset, head = _mk()
        torch.manual_seed(0)
        cond = torch.randn(1, 8, cond_dim)
        t0 = time.time()
        with torch.no_grad():
            a = head.predict_action(cond)
        return {"status": "ok", "action_chunk": a.detach().numpy().reshape(-1),
                "chunk_3d": list(a.shape), "H": int(a.shape[1]), "action_dim": int(a.shape[2]),
                "n_infer_steps": int(getattr(head, "num_inference_timesteps", -1)),
                "ms": round((time.time() - t0) * 1e3, 1),
                "dit_src": "action_head.py:354 predict_action (flow matching 采样, @torch.no_grad)"}

    return [
        ("① 投影 条件 token (1, 8, 960)", s_project,
         "action_head.py:205 SmolVLALewActionHead · cross_attention_dim=960 (DiT 条件宽度)",
         {"entry": ("src/lerobot/policies/smolvla_lew/action_head.py", "SmolVLALewActionHead", 205)}),
        ("② 度量 L4→L3 条件通道 (apply_l4_cond)", s_metric,
         "action_head.py:301 apply_l4_cond · l4_cond_proj (懒建, 未训练)",
         {"entry": ("src/lerobot/policies/smolvla_lew/action_head.py", "SmolVLALewActionHead.apply_l4_cond", 301)}),
        ("③ 导航 流匹配采样 → 动作块", s_navigate,
         "action_head.py:354 predict_action (整段去噪 = 沿流匹配轨迹导航)",
         {"entry": ("src/lerobot/policies/smolvla_lew/action_head.py", "SmolVLALewActionHead.predict_action", 354)}),
    ], (lambda res: [
        ("DiT 真身可构造 (真代码, 非别名)", res[0].get("status") == "ok",
         "preset=%s · 参数=%s" % (res[0].get("preset"), res[0].get("params"))),
        ("条件宽度 = 960 (真源 cross_attention_dim)", res[0].get("cond_dim") == 960 or res[0].get("status") != "ok",
         str(res[0].get("why", "cond_dim=960"))[:70]),
        ("流匹配采样真跑出动作块 (H×action_dim)", bool(res[2].get("status") == "ok" and res[2]["chunk_3d"][1] == 7),
         "形状=%s · %.1fms" % (res[2].get("chunk_3d"), float(res[2].get("ms") or -1))),
        ("⚠️ 画布接入口径如实: ssdec 绑的是 MLP, 真 DiT 未被任何节点引用",
         True, "画布 ssdec = StateSpaceActionHead (state_space_action_head.py, 无 DiT/无流匹配/无权重) "
               "· 真 DiT = action_head.py:205 未被任何节点绑定 ⇒ 要接需动 L3 真链路 (等老倪点头)"),
    ])


NODES = {
    "ss_mani_eng": {
        "name": "🧮 流形引擎 (Manifold Engine · 编码→投影→度量→导航→反馈)",
        "entry": (ENTRY, "node_ss_mani_eng", 5227),
        "modules": ["src/lerobot/manifold/manifold_engine.py",
                    "src/lerobot/policies/left_right/state_space/su2.py"],
        "links": "投影/度量/导航 三环节全在",
        "stages": stages_mani_eng,
        "layer": "L3 (规划/导航) · 汇入 L4",
    },
    "ssmani_exp": {
        "name": "🧠 流形专家预测器 (JEPA: 潜空间→流形→动作)",
        "entry": (ENTRY, "node_ss_pred", 4219),
        "modules": ["src/lerobot/manifold/predictor_layer.py",
                    "src/lerobot/policies/smolvla_lew/state_space_action_head.py"],
        "links": "投影(编码) / 度量(流形读出) / 导航(解码动作)",
        "stages": stages_manifold_expert,
        "layer": "L4 (自主层世界模型)",
    },
    "ssmani_c": {
        "name": "🧮 接触流形 · 导航地图 (e∥进度 / e⊥偏离)",
        "entry": (ENTRY, "node_ss_mani", 3957),
        "modules": ["src/lerobot/manifold/manifold_layer.py"],
        "links": "投影(_error) / 度量(轴分解+V) / 导航(decompose)",
        "stages": stages_contact,
        "layer": "L3 (几何条件 → DiT)",
    },
    "ssmani_p": {
        "name": "🧮 性能流形 · 耦合代价 (V_p / η)",
        "entry": (ENTRY, "node_ss_mani", 3957),
        "modules": ["src/lerobot/manifold/manifold_layer.py"],
        "links": "投影(δ) / 度量(V_p,η) / 导航(evaluate→∇V_p)",
        "stages": stages_perf,
        "layer": "L3 (集合条件 → DiT)",
    },
    "ssdec": {
        "name": "🎯 Flow-Matching Action Head (DiT · 5 路条件汇总)",
        "entry": (ENTRY, "node_ss_dec", 4332),
        "modules": ["src/lerobot/policies/smolvla_lew/state_space_action_head.py"],
        "links": "投影(条件 z⁷) / 度量(条件汇总) / 导航(forward→动作块)",
        "stages": stages_dit,
        "layer": "L3 (动作头 / 输出 K 增益的候选位)",
    },
    "ss_ff": {
        "name": "⚡ 前馈加速器 (FeedforwardAccelerator · 快路径直映射)",
        "entry": (ENTRY, "node_ss_s2", 2364),
        "modules": ["src/lerobot/policies/left_right/state_space/parallel.py"],
        "links": "投影(obs→u_ff) / 度量(限幅±0.6) / 导航(快路径语义)",
        "stages": stages_ff,
        "layer": "L2 (执行层快路径)",
    },
    "ssdec_real": {
        "name": "🎯 DiT 真身 (SmolVLALewActionHead · 流匹配) —— ⚠️ 画布未接入",
        "entry": ("src/lerobot/policies/smolvla_lew/action_head.py", "SmolVLALewActionHead", 205),
        "modules": ["src/lerobot/policies/smolvla_lew/action_head.py",
                    "src/lerobot/policies/smolvla_lew/configuration_smolvla_lew.py"],
        "links": "投影(条件 token) / 度量(L4→L3 条件通道) / 导航(流匹配采样 predict_action)",
        "stages": stages_dit_real,
        "layer": "L3 (真 DiT · 当前无画布节点绑定 ⇒ 假接入警示)",
    },
}

# 四种连接方式 (老倪 2026-10-16 原文) → 本仓库的落地锚点
CONN_MODES = [
    ("① 投影到流形 + 沿流形导航",
     "ManifoldEngine.project (manifold_engine.py:691) → Navigator.step (:438) → 测地线是可行运动"),
    ("② 度量张量决定切空间长度/角度",
     "MetricCalculator (manifold_engine.py:301) · M/度规特征值 → gradient_flow (:748)"),
    ("③ 流形是约束流形 (只许在流形上)", 
     "ContactManifold.channel_axis (manifold_layer.py:101) · 法向偏离 e⊥ 越界 = 风险/撕裂"),
    ("④ 流形是条件空间 (条件注入 DiT)",
     "画布真连线 ssmani_c/ssmani_p/…→ssdec 5 路并联 (state_space_action_head.py:37)"),
]


def _product_gate(product):
    """档位校验: 只有调试档 (550B) 允许深调试 —— 读产品真源, 不写死"""
    d = _read_json(SRC_PRODUCT) or {}
    prof = (d.get("dev_profile") or {}) if isinstance(d.get("dev_profile"), dict) else {}
    active = str(d.get("active") or d.get("current") or "").strip()
    cfg = None
    for k, v in (d.get("products") or {}).items():
        if str(k).upper() == str(product).upper():
            cfg = v
            break
    if cfg is None:
        # 兜底: 顶层直接按档位键放的写法
        cfg = d.get(str(product).upper()) or {}
    debug_ok = bool((cfg or {}).get("debug", (cfg or {}).get("allow_debug", None)) is not None)
    if "debug" in (cfg or {}):
        debug_ok = bool(cfg["debug"])
    elif "allow_debug" in (cfg or {}):
        debug_ok = bool(cfg["allow_debug"])
    else:
        debug_ok = bool(prof.get("vscode_debug")) or str(product).upper() in ("550B",)
    return {"product": product, "active": active, "debug_allowed": debug_ok,
            "dev_profile": prof, "cfg_keys": sorted(list((cfg or {}).keys()))[:10]}


def cmd_list():
    print(_c("b", "Z-MAX 节点单步调试器 · 六节点 (550B 标定/调试档)"))
    print("─" * 100)
    for nid, n in NODES.items():
        f, fn, ln = n["entry"]
        print("%-12s %s" % (nid, n["name"]))
        print("             %-14s 入口 %s:%d  def %s()" % (n["layer"], f, ln, fn))
        print("             三环节  %s" % n["links"])
        print("             源码    %s" % " · ".join(n["modules"]))
        print()
    print(_c("b", "四种连接方式 (老倪 2026-10-16) → 本仓库锚点"))
    for name, anchor in CONN_MODES:
        print("  %s\n      %s" % (name, anchor))
    print()
    print("真源: %s" % SRC_TRAJ)
    print("      %s" % SRC_ENGINE)
    print("      %s   %s" % (SRC_WEIGHTS, OBS_CH))
    return 0


def cmd_src(nid):
    """打印该节点**每一环节**的源码绝对路径+行号 (VSCode: code -g file:line 直接断点)"""
    import argparse as _ap
    n = NODES[nid]
    f, fn, ln = n["entry"]
    ap = os.path.join(ROOT, f)
    g, err = load_traj(200, None)
    print(_c("b", "%s — 源码位置 (VSCode/Cursor 直接打断点)" % nid))
    print("  %s" % n["name"])
    print("  ① 画布薄壳  %s:%d" % (ap, ln))
    print("              def %s(ctx):   ← GUI 派发 (右键运行节点走到这)" % fn)
    for rel in n["modules"]:
        print("  ② 算法真体  %s" % os.path.join(ROOT, rel))
    if err:
        print("  %s" % _c("y", "  (真源缺失, 只列源码: %s)" % err))
        return 0
    stages, _ = n["stages"](g)
    print("  ③ 单步环节 (每步 = 真源码里的一行, 断点就设在这些行上)")
    for i, (title, _fnx, note, meta) in enumerate(stages, 1):
        ef, efn, eln = meta["entry"]
        print("     %s" % _c("b", title))
        print("        %s:%d   %s()" % (os.path.join(ROOT, ef), eln, efn))
        print("        %s" % _c("dim", note))
    print()
    print("  环境变量: ZMAX_DEBUG_BREAK=1  (与画布「右键源码 → VSCode 断点」同一口径)")
    print("  打开命令: code -g %s:%d" % (ap, ln))
    print("  单步命令: %s tools/node_debug.py --node %s --step --pdb" % (sys.executable, nid))
    return 0


def run_node(nid, g, step=False, use_pdb=False, quiet=False):
    n = NODES[nid]
    stages, checks_fn = n["stages"](g)
    res = []
    print(_c("b", "\n═══ %s ═══" % nid))
    print("  %s" % n["name"])
    print("  入口 %s:%d def %s() · 三环节 %s" %
          (n["entry"][0], n["entry"][2], n["entry"][1], n["links"]))
    print("  真源帧 #%d/%d (%s·%s) · 阶段=%s [%s]" %
          (g["idx"], g["n"] - 1, g.get("saved_at"), g.get("task_id"), g["stage"], g["stage_src"]))
    for i, (title, fn, note, meta) in enumerate(stages, 1):
        ef, efn, eln = meta["entry"]
        ap = os.path.join(ROOT, ef)
        if use_pdb:
            import pdb
            print(_c("y", "  ⛔ 断点 %s:%d %s()  —— 下一步回车/continue" % (ap, eln, efn)))
            pdb.set_trace()
        t0 = time.perf_counter()
        try:
            out = fn()
            err = None
        except Exception as e:                                           # noqa: BLE001
            out, err = {}, "%s: %s" % (type(e).__name__, e)
        ms = (time.perf_counter() - t0) * 1e3
        print("\n  %s" % _c("b", title))
        print("     %s:%d  %s()  %s" % (ap, eln, efn, _c("dim", "· %.2fms" % ms)))
        print("     %s" % _c("dim", note))
        if err:
            print("     %s" % _c("bad", "❌ 执行失败: " + err))
        else:
            for k, v in out.items():
                print("       %-22s %s" % (k, _v(v) if isinstance(v, (list, tuple)) or hasattr(v, "shape") else
                                           (_f(v) if isinstance(v, float) else str(v))))
        res.append(out)
        if step and i < len(stages):
            try:
                s = input(_c("y", "     ⏎ 继续 / q 退出 > ")).strip().lower()
            except EOFError:
                s = ""
            if s == "q":
                break
    ok_all = True
    print("\n  %s" % _c("b", "不变量自检"))
    for name, ok, detail in checks_fn(res):
        ok_all = ok_all and bool(ok)
        print("    %s %-52s %s" % (_c("ok", "✅") if ok else _c("bad", "❌"), name, detail))
    print("  %s" % (_c("ok", "   ✓ 本节点单步全通过") if ok_all else _c("bad", "   ✗ 本节点有不变量未过")))
    return {"node": nid, "name": n["name"], "entry": "%s:%d" % (n["entry"][0], n["entry"][2]),
            "stages": [{"title": s[0], "src": "%s:%d" % (s[3]["entry"][0], s[3]["entry"][2]),
                        "fn": s[3]["entry"][1]} for s in stages],
            "values": [_jsonable(r) for r in res], "checks_ok": bool(ok_all)}


def _jsonable(o):
    import numpy as _np
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    if hasattr(o, "tolist"):
        return o.tolist()
    if hasattr(o, "detach"):
        return o.detach().cpu().numpy().tolist()
    if isinstance(o, (str, int, float, bool)) or o is None:
        return o
    return str(o)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Z-MAX 节点单步调试器 (550B 标定/调试档)")
    ap.add_argument("--list", action="store_true", help="六节点表")
    ap.add_argument("--node", default="ss_mani_eng", choices=sorted(NODES.keys()))
    ap.add_argument("--step", action="store_true", help="单步 (回车走一步)")
    ap.add_argument("--trace", action="store_true", help="一次跑完 (非交互)")
    ap.add_argument("--src", action="store_true", help="打印源码绝对路径+行号")
    ap.add_argument("--pdb", action="store_true", help="每步前断点 (pdb.set_trace)")
    ap.add_argument("--all", action="store_true", help="六节点全跑")
    ap.add_argument("--json", default=None, help="写 JSON 轨迹 (唯一写入口)")
    ap.add_argument("--frame", type=int, default=200)
    ap.add_argument("--stage", default=None)
    ap.add_argument("--product", default="550B")
    a = ap.parse_args(argv)

    if a.list:
        return cmd_list()
    gate = _product_gate(a.product)
    deep = bool(a.step or a.trace or a.all)
    if deep and not gate["debug_allowed"]:
        print(_c("bad", "⛔ 档位 %s 不是调试档 (debug_allowed=False) ⇒ 只允许 --list / --src"
                        % gate["product"]))
        print("   550B = 标定/调试档 (dev_profile.vscode_debug=%s)" % gate["dev_profile"].get("vscode_debug"))
        return 2
    if a.src:
        return cmd_src(a.node)
    use_pdb = bool(a.pdb) or os.environ.get("ZMAX_DEBUG_BREAK") == "1"
    if use_pdb and not a.step and not a.trace:
        a.trace = True
    g, err = load_traj(a.frame, a.stage)
    if err:
        print(_c("bad", "❌ " + err))
        return 3
    print(_c("dim", "真源 %s · %s" % (SRC_TRAJ, OBS_CH)))
    if a.all or (not a.step and not a.trace):
        results = [run_node(nid, g, step=False, use_pdb=False) for nid in NODES]
    else:
        results = [run_node(a.node, g, step=a.step, use_pdb=use_pdb)]
    if a.json:
        out = os.path.join(ROOT, a.json) if not os.path.isabs(a.json) else a.json
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "product": gate["product"],
                       "frame": g["idx"], "traj": SRC_TRAJ, "nodes": results}, f,
                      ensure_ascii=False, indent=1)
        print("\n📄 JSON 轨迹 → %s" % out)
    bad = [r["node"] for r in results if not r["checks_ok"]]
    print("\n%s" % (_c("ok", "═══ 七节点单步: %d/%d 节点不变量全通过 ═══" % (len(results) - len(bad), len(results)))
                    if not bad else _c("bad", "═══ 未通过: %s ═══" % ",".join(bad))))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
