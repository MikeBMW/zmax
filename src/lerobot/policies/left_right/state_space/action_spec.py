# -*- coding: utf-8 -*-
"""📐 action 契约唯一真源 (老倪 2026-11-15: "机器人已经确定 action 接口了, L2 L3 L4 L5 要对齐它")

所有层只认这一个口径, 别再各写一份:
    · 位置: milli-meter, **基座系** (frame="base")
    · 姿态: 欧拉 a/b/c = deg (ZYX 口径, 与 tcp_out/latest.json 同源) + 四元数 qx,qy,qz,qw (w 在后)
    · 速度: u = [vx, vy, vz, grip] — 前三 **m/s** (与 FSM v_cap 0.35 / from_ss 的 u·dt·1000 同源),
      第 4 维夹爪 (>0.5 合 / <=0.5 开)
    · 夹爪: grip_mm 0=全合 70=全开; grip_act ∈ {open, close, hold}
    · 三件套证据: align{frame, unit, pose_truth, delta_mm, step_mm, max_step_mm, truth_age_s,
                       truth_fresh, step_ok}

逐来源字段地图 (谁读哪个块, 别猜):
    src="traj215"  位姿 + i + pose_now + grip_*            (215 点真值回放, 无速度)
    src="plan"     位姿 + plan{u(标量 0..1 速度因子), seg_i, seg_kind, seg_a, seg_b, plan_id}
                   + align{...}                            (运动规划节点输出 ⇒ 机器人节点逐字执行)
    src="ss"       位姿 + u[vx,vy,vz,grip] (m/s + 夹爪) + pose{x,y,z,a,b,c,qx..qw,dt_s}
                   + align{...}                            (状态空间/模型输出)

用法:
    from lerobot.policies.left_right.state_space.action_spec import validate, REQUIRED
    issues = validate(act)          # [] 表示合格
"""
from __future__ import annotations

import math

FRAME = "base"
UNIT = "mm"
GRIP_OPEN_MM = 70.0
GRIP_CLOSE_MM = 0.0
MAX_STEP_MM = 25.0
TRUTH_FRESH_S = 1.0
U_DIM = 4

REQUIRED = ("src", "x", "y", "z", "a", "b", "c", "qx", "qy", "qz", "qw",
            "grip_mm", "grip_act", "ts")

# 每种来源额外必须有的块
EXTRA = {
    "plan": ("plan", "align", "pose"),
    "ss": ("u", "align", "pose"),
    "traj215": ("i", "pose_now"),
}

POS_LIMIT_MM = 3000.0          # 基座系可达范围上限 (超过必是单位错/坐标系错)
GRIP_LIMIT_MM = 120.0


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v))


def validate(act, *, src=None) -> list:
    """→ 问题清单 (空 = 合格)。src 可强制指定期望来源。"""
    p = []
    if not isinstance(act, dict):
        return ["action 不是 dict: %r" % type(act).__name__]
    for k in REQUIRED:
        if k not in act:
            p.append("缺字段 %s" % k)
    if p:
        return p
    s = str(act.get("src") or "")
    if src and s != src:
        p.append("src 应为 %s, 实际 %s" % (src, s))
    # 位置
    for k in ("x", "y", "z"):
        v = act.get(k)
        if not _num(v):
            p.append("%s 非数值: %r" % (k, v))
        elif abs(float(v)) > POS_LIMIT_MM:
            p.append("%s=%s 超基座系量程 (±%gmm) ⇒ 单位/坐标系可疑" % (k, v, POS_LIMIT_MM))
    # 姿态
    for k in ("a", "b", "c"):
        v = act.get(k)
        if v is not None and (not _num(v) or abs(float(v)) > 360.0):
            p.append("%s=%r 非法 (deg, |·|<=360)" % (k, v))
    q = [act.get("q" + k) for k in ("x", "y", "z", "w")]
    if any(x is None for x in q):
        p.append("四元数不全: %r" % (q,))
    elif not all(_num(x) for x in q):
        p.append("四元数非数值")
    else:
        n = math.sqrt(sum(float(x) ** 2 for x in q))
        if abs(n - 1.0) > 0.02:
            p.append("四元数未归一化 |q|=%.4f" % n)
    # 夹爪
    g = act.get("grip_mm")
    if g is not None and (not _num(g) or not (GRIP_LIMIT_MM * -1 <= float(g) <= GRIP_LIMIT_MM)):
        p.append("grip_mm=%r 非法 (0合/70开)" % (g,))
    if act.get("grip_act") not in ("open", "close", "hold"):
        p.append("grip_act=%r 应为 open/close/hold" % (act.get("grip_act"),))
    # 来源相关的块
    for k in EXTRA.get(s, ()):
        if k not in act or act.get(k) is None:
            p.append("src=%s 缺 %s 块" % (s, k))
    if s in ("plan", "ss"):
        al = act.get("align") or {}
        if al.get("frame") != FRAME:
            p.append("align.frame=%r 应为 %r" % (al.get("frame"), FRAME))
        if al.get("unit") != UNIT:
            p.append("align.unit=%r 应为 %r" % (al.get("unit"), UNIT))
        st = al.get("step_mm")
        mx = al.get("max_step_mm")
        if st is not None and mx is not None and float(st) > float(mx):
            p.append("单拍步长 %.2fmm 超上限 %.2fmm" % (float(st), float(mx)))
        age = al.get("truth_age_s")
        if age is not None and float(age) > TRUTH_FRESH_S and al.get("truth_fresh"):
            p.append("真值 %.2fs 已陈旧却标 truth_fresh=True" % float(age))
    if s == "ss":
        u = act.get("u")
        if not isinstance(u, (list, tuple)) or len(u) != U_DIM:
            p.append("u 应为 %d 维 [vx,vy,vz,grip], 实际 %r" % (U_DIM, u))
        elif not all(_num(x) for x in u[:3]):
            p.append("u[:3] 含非数值: %r" % (u,))
        elif u[3] is not None and not _num(u[3]):
            p.append("u[3] 非数值 (None=保持实测): %r" % (u[3],))
        elif abs(float(u[3])) > 1.5:
            p.append("u[3] 夹爪应在 [-1,1]: %r" % (u[3],))
    return p


def describe(act) -> str:
    """一行摘要 (日志/证据用)。"""
    if not isinstance(act, dict):
        return "action? %r" % (act,)
    return ("src=%s pos=%.2f/%.2f/%.2f abc=%.3f/%.3f/%.3f grip=%s(%s) step=%s" %
            (act.get("src"), act.get("x") or 0, act.get("y") or 0, act.get("z") or 0,
             act.get("a") or 0, act.get("b") or 0, act.get("c") or 0,
             act.get("grip_mm"), act.get("grip_act"),
             ((act.get("align") or {}).get("step_mm"))))


def to_array(act):
    """给模型侧的向量化口径: [x,y,z,a,b,c,grip] (mm, deg, mm) —— 与训练归一化必须同源。"""
    import numpy as np
    return np.asarray([act.get("x"), act.get("y"), act.get("z"),
                       act.get("a"), act.get("b"), act.get("c"),
                       act.get("grip_mm")], dtype="float32")
