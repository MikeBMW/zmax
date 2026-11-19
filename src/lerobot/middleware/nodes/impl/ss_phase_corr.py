# -*- coding: utf-8 -*-
"""ss_phase_corr — 画布节点: 相空间安全通道 (SE(3)×S1 记忆 + 速度纤维)

老倪 2026-11-20: 人为轨迹在相空间里"强跨相位线"(电机持续注入/抽取能量) ⇒ 必须用
各向异性度规在相空间里画出安全管道:

  z = [e_pose/tol ; e_vel/vlim]        (无量纲偏离, V=1 正好压在公差上)
  V_phase = ½‖z‖²                     (相空间势能)
  τ_safe  = −α·τ_lim⊙(z_pos + z_vel)  (黎曼自然梯度的工程形态, 各向异性 + 饱和)
  S¹ 相位门控: 相位不匹配 ⇒ 记忆断裂 ⇒ 注入置 0
  α_eff = min(α, λ/2) ⇒ V̇ ≤ −λV (李雅普诺夫单调下降)

真源: zmax_data/se3/se3_state_live.json (A–E) + zmax_data/se3/se3_state_history.jsonl (含速度)。
记忆中心线 = 历史流里 0.2s 前的那一帧 (同一条 5Hz 记忆流, 不另造规迹)。
只读: 不向机器人下发任何东西, 只把 V/τ/门控 落 _SS_STATE["phase_corr"] 给下游显示与判据。

entry: node_ss_phase_corr   ·   registry key: ss_phase_corr
"""

from __future__ import annotations

import json
import math
import os

from .shared_runtime import _SS_STATE  # noqa: F401

def _zmax_root() -> str:
    """仓库根: 环境变量优先, 否则从本文件向上逐级找含 zmax_data 的那一层。"""
    env = os.environ.get("ZMAX_ROOT")
    if env and os.path.isdir(os.path.join(env, "zmax_data")):
        return env
    p = os.path.dirname(os.path.abspath(__file__))
    for _ in range(8):
        if os.path.isdir(os.path.join(p, "zmax_data")):
            return p
        p = os.path.dirname(p)
    return "/home/ubuntu/zmax"


_ROOT = _zmax_root()
_D = os.path.join(_ROOT, "zmax_data", "se3")
LIVE = os.path.join(_D, "se3_state_live.json")
HIST = os.path.join(_D, "se3_state_history.jsonl")

_CORR = None


def _corridor():
    global _CORR
    if _CORR is None:
        from lerobot.manifold.phase_corridor import CorridorMetric, PhaseSpaceCorridor
        _CORR = PhaseSpaceCorridor(CorridorMetric(), epsilon=0.30, alpha=1.5, lam=2.0)
    return _CORR


def _quat_qxyz(c) -> list:
    """文件里 C.quat_S3 是 [qw,qx,qy,qz] (与 tcp_out 的 qx..qw 顺序不同) → 统一成 qx,qy,qz,qw。"""
    if not c:
        return [0.0, 0.0, 0.0, 1.0]
    c = list(c)
    if len(c) != 4:
        return [0.0, 0.0, 0.0, 1.0]
    w, x, y, z = c
    return [x, y, z, w]


def _tail(path, n=40):
    if not os.path.exists(path):
        return []
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - 64 * n))
        lines = f.read().decode("utf-8", "ignore").strip().splitlines()
    out = []
    for ln in lines[-n:]:
        try:
            out.append(json.loads(ln))
        except Exception:                          # noqa: BLE001
            continue
    return out


def _sample(rec):
    """一条记录 → 相空间样本 (pos m, quat, s1 rad)。

    两种落盘形态都要吃:
      · live  (zmax.se3_state.v1): A/B/C/D/E 分块
      · history: 扁平 16 维 vector
        [x,y,z, ax,ay,az, axis_err, qw,qx,qy,qz, roll, s, arc_mm, nearest_i, age_s]
    """
    vec = rec.get("vector")
    if vec and len(vec) >= 15:
        pos = [float(vec[0]) / 1000.0, float(vec[1]) / 1000.0, float(vec[2]) / 1000.0]
        return {
            "t": float(rec.get("ts") or 0.0),
            "pos": pos,
            "quat": _quat_qxyz([vec[7], vec[8], vec[9], vec[10]]),
            "s1": float(vec[12]) * 2.0 * math.pi,
            "axis": [float(vec[3]), float(vec[4]), float(vec[5])],
            "nearest_i": vec[14],
            "arc_mm": float(vec[13]),
        }
    a = rec.get("A") or {}
    c = rec.get("C") or {}
    e = rec.get("E") or {}
    pos = [float(v) / 1000.0 for v in (a.get("pos_mm") or [0, 0, 0])]
    return {
        "t": float(rec.get("ts") or 0.0),
        "pos": pos,
        "quat": _quat_qxyz(c.get("quat_S3")),
        "s1": float(e.get("s") or 0.0) * 2.0 * math.pi,     # s∈[0,1] 圆 → S¹ rad
        "axis": (rec.get("B") or {}).get("axis_S2"),
        "nearest_i": e.get("nearest_i"),
        "arc_mm": e.get("arc_mm"),
    }


def _valid(s) -> bool:
    """历史流里可能混入全 0 的陈旧样本 (断电/重启初期) —— 不许拿来当记忆中心线。"""
    return any(abs(v) > 1e-9 for v in s["pos"])


def _vel(prev, cur):
    dt = max(cur["t"] - prev["t"], 1e-3)
    v = [(cur["pos"][i] - prev["pos"][i]) / dt for i in range(3)]
    # 角速度: 用四元数增量近似 (小角) → 世界系 ω
    q0, q1 = prev["quat"], cur["quat"]
    w0, q1x, q1y, q1z = q1[3], q0[0], q0[1], q0[2]
    dot = abs(sum(a * b for a, b in zip(q0, q1)))
    ang = 2.0 * math.acos(min(1.0, dot))
    om = [0.0, 0.0, 0.0]
    if ang > 1e-9:
        om = [ang / dt * s for s in (q1x, q1y, q1z)]
    return v, om


def node_ss_phase_corr(ctx):
    log = ctx.get("log")
    try:
        if not os.path.exists(LIVE):
            if log:
                log(f"⚠️ 相空间通道: 缺真值 {LIVE}")
            return False
        with open(LIVE, encoding="utf-8") as f:
            live = json.load(f)
        hist = [s for s in (_sample(r) for r in _tail(HIST, 60)) if _valid(s)]
        cur = _sample(live)
        if not hist:
            if log:
                log("⚠️ 相空间通道: 无历史流 (se3_state_history.jsonl 空) ⇒ 无法取速度纤维")
            return False
        # 记忆中心线 = 历史流里 0.2s 前那一帧; 速度用最近两帧差分
        prev = hist[-1]
        if abs(prev["t"] - cur["t"]) < 1e-9 and len(hist) >= 2:
            prev = hist[-2]
        ref = None
        for s in reversed(hist):
            if cur["t"] - s["t"] >= 0.2:
                ref = s
                break
        if ref is None:
            ref = hist[0]

        v_cur, w_cur = _vel(prev, cur)
        v_ref, w_ref = ([0.0, 0.0, 0.0], [0.0, 0.0, 0.0])
        if len(hist) >= 2:
            v_ref, w_ref = _vel(hist[-2], hist[-1])

        r = _corridor().compute(
            {"pos": cur["pos"], "quat": cur["quat"], "s1": cur["s1"],
             "vel": v_cur, "omega": w_cur},
            {"pos": ref["pos"], "quat": ref["quat"], "s1": ref["s1"],
             "vel": v_ref, "omega": w_ref},
            axis=cur["axis"])

        out = r.as_dict()
        out.update({
            "src": "se3_state_live.json + history(0.2s 记忆中心线)",
            "cur_mm": [round(x * 1000, 2) for x in cur["pos"]],
            "ref_mm": [round(x * 1000, 2) for x in ref["pos"]],
            "v_cur_mm_s": [round(x * 1000, 2) for x in v_cur],
            "nearest_i": cur["nearest_i"], "arc_mm": cur["arc_mm"],
            "ts": cur["t"],
        })
        _SS_STATE["phase_corr"] = out
        if log:
            log("🌀 相空间安全通道 · " + r.summary())
            log("   记忆中心线: 当前 %s mm → 0.2s 前 %s mm · 速度 %s mm/s · 近点 #%s"
                % (out["cur_mm"], out["ref_mm"], out["v_cur_mm_s"], cur["nearest_i"]))
        return True
    except Exception as exc:                       # noqa: BLE001
        if log:
            log(f"✗ 相空间通道失败: {type(exc).__name__}: {exc}")
        return False
