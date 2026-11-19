# -*- coding: utf-8 -*-
"""ss_se3_state — 画布节点: SE(3)×S1 记忆流形 (昨日 zmax-se3-state 服务的 16 维 A–E)

老倪 2026-11-20: 「把昨天的 se3 服务增加到状态空间 simulink 画布上, 我可以直接打开」。

真源 zmax_data/se3/se3_state_live.json (zmax-se3-state.service, 5Hz, 8815 /api/se3):
  A 位置 ℝ³ · B 轴 S² · C 四元数 S³ · D 滚转 S¹ · E 弧长相位 S¹ (s/arc_mm/nearest_i)
本节点只读 + 打印 + 落 _SS_STATE["se3_state"], 供「相空间安全通道」节点吃;
不新增控制通路 (唯一三层安全 = 否决 + 限幅 + Sys0 不变)。

entry: node_ss_se3_state   ·   registry key: ss_se3_state
"""

from __future__ import annotations

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


_ROOT = _zmax_root()          # → zmax/
LIVE = os.path.join(_ROOT, "zmax_data", "se3", "se3_state_live.json")


def _load_live(path=LIVE):
    import json
    import time
    if not os.path.exists(path):
        return None, "缺文件 %s" % path
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    age = time.time() - float(d.get("ts") or 0)
    return d, age


def node_ss_se3_state(ctx):
    log = ctx.get("log")
    d, age = _load_live()
    if d is None:
        if log:
            log(f"⚠️ SE(3) 记忆流形: {age}")
        return False
    try:
        A = d.get("A") or {}
        B = d.get("B") or {}
        C = d.get("C") or {}
        D = d.get("D") or {}
        E = d.get("E") or {}
        st = {
            "ts": d.get("ts"), "age_s": round(float(age), 3),
            "svc": d.get("svc"), "truth_src": d.get("truth_src"),
            "pos_mm": A.get("pos_mm"), "axis_S2": B.get("axis_S2"),
            "axis_err_deg": B.get("axis_err_deg"), "quat_S3": C.get("quat_S3"),
            "roll_rad": D.get("roll_rad"), "s": E.get("s"),
            "arc_mm": E.get("arc_mm"), "nearest_i": E.get("nearest_i"),
            "vector": d.get("vector"), "meta": d.get("meta"),
            "src": LIVE,
        }
        _SS_STATE["se3_state"] = st
        if log:
            log("🔷 SE(3)×S1 记忆流形 (5Hz · 帧龄 %.2fs · %s)" % (age, d.get("svc") or "-"))
            log("   A 位置 ℝ³ = %s mm · 轴 S² = %s (偏差 %.2f°)" % (
                A.get("pos_mm"), B.get("axis_S2"), float(B.get("axis_err_deg") or 0)))
            log("   C 四元数 S³ = %s · D 滚转 S¹ = %.1f° · E 相位 S¹ s=%.6f (arc %.1fmm, 近点 #%s)"
                % (C.get("quat_S3"), float(D.get("roll_deg") or 0),
                   float(E.get("s") or 0), float(E.get("arc_mm") or 0), E.get("nearest_i")))
            if float(age) > 1.0:
                log("   ⚠️ 该段真值偏旧 (%.1fs) ⇒ 只作显示, 不当实时闭环源" % float(age))
        return True
    except Exception as exc:                       # noqa: BLE001
        if log:
            log(f"✗ SE(3) 记忆流形解析失败: {type(exc).__name__}: {exc}")
        return False
