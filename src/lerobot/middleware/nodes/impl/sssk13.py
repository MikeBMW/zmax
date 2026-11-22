# -*- coding: utf-8 -*-
"""sssk13 — ⑬ 自动翻转 · SK13 (节点实现正文)

分工 (2026-11-22 老倪「自动翻转放料 · 根据拉环朝向自动翻转 180 度 · 满足运动包络约束」):
  本节点只做**判据 + 包络**: 拉环/模块朝向 vs 目标朝向 ⇒ 要不要翻; 要翻就给出
  「先抬净空 → 每拍 ≤5° 分段转 → 回落」的动作序列, 交运动规划 (n_moveit) 展开成 action。
  它**不产目标位姿** —— 翻转后的目标位姿仍由 🧭 测地线规划引导 (n_geoplan) 给。

输入 (按画布连线):
  in1 ← sslimit   限幅后控制 (含当前位姿, 用来取"现在是多高、多远")
  in2 ← ssskill   L3 技能序列编排 (选到 SK13 才走这里)
  in3 ← ss_mem_l2 记忆赋能 (标杆/通道, 本节点只用其位置信息)
  in4 ← n_geoplan 目标位姿 (quat → 目标朝向; 判据靠它)
输出:
  out1 → n_moveit 翻转动作序列 {flip_call, deg, plan[], n_steps, why}
  out2 → ssphys   本段物理上限 (v_cap/a_max/单拍角度, 供动力学闸取数)

registry key = sssk13 · 算法真源 skills/atomic_skills.py:class SK13Flip
"""


def _yaw_deg_from_quat_wxyz(q):
    """四元数(w,x,y,z) → 绕 Z 的偏航角(deg)。取不到就 None (绝不猜)。"""
    import math
    if not q or len(q) < 4:
        return None
    try:
        w, x, y, z = [float(v) for v in q[:4]]
    except Exception:                                                       # noqa: BLE001
        return None
    n = math.sqrt(w * w + x * x + y * y + z * z)
    if n < 1e-9:
        return None
    w, x, y, z = w / n, x / n, y / n, z / n
    return math.degrees(math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z)))


def _first_pos(d):
    """从各种口径里取一个 3 维位置 (mm): pos_mm / grasp_mm / tcp / pos。"""
    if not isinstance(d, dict):
        return None
    for k in ("grasp_mm", "pos_mm", "tcp", "pos", "xyz"):
        v = d.get(k)
        if isinstance(v, (list, tuple)) and len(v) >= 3:
            try:
                return [float(v[0]), float(v[1]), float(v[2])]
            except Exception:                                               # noqa: BLE001
                continue
    return None


def node_ss_flip(ctx):
    """⑬ 自动翻转: 判据 → (要翻) 抬净空 + 分段旋转序列 → 交运动规划。"""
    from lerobot.policies.left_right.state_space.skills.atomic_skills import SK13Flip

    src_tgt = (ctx.get("in4") or {}).get("value")
    src_ctl = (ctx.get("in1") or {}).get("value")
    if not isinstance(src_tgt, dict):
        src_tgt = {}
    if not isinstance(src_ctl, dict):
        src_ctl = {}

    # 口径(2026-11-22 修): 引导给的 quat = **模块/拉环现在的朝向** (yaw_mod 默认取它);
    #   目标朝向 = 槽位/工位要求 (显式 target_yaw_deg / slot_yaw_deg, 或节点参数)。
    #   原来两个都要求显式给, 结果引导明明带了 quat 却报"缺朝向" —— 属于接口写反。
    quat = src_tgt.get("quat") or src_tgt.get("q")
    yaw_mod = next((v for v in (src_tgt.get("module_yaw_deg"), src_tgt.get("yaw_module_deg"),
                                src_ctl.get("yaw_module_deg")) if v is not None), None)
    if yaw_mod is None and quat:
        yaw_mod = _yaw_deg_from_quat_wxyz(quat)          # 引导位姿的姿态就是模块朝向
    yaw_tgt = next((v for v in (src_tgt.get("target_yaw_deg"), src_tgt.get("yaw_target_deg"),
                                src_tgt.get("slot_yaw_deg"), src_ctl.get("target_yaw_deg"),
                                src_ctl.get("slot_yaw_deg"),
                                (ctx.get("params") or {}).get("target_yaw_deg")) if v is not None), None)

    if yaw_tgt is None or yaw_mod is None:
        miss = "模块/拉环朝向(引导 quat)" if yaw_mod is None else "目标朝向(槽位/工位要求)"
        status = "缺%s ⇒ 不动作 (不猜朝向)" % miss
        return {"out1": {"flip_call": None, "why": status, "skill": SK13Flip.code,
                         "yaw_module_deg": None if yaw_mod is None else round(float(yaw_mod), 2)},
                "out2": {"phys": SK13Flip().clamp([0.0, 0.0, 0.0, 1.0]).get("phys")}}

    call, ddeg, why = SK13Flip.needs_flip(yaw_mod, yaw_tgt)
    pos = _first_pos(src_tgt) or _first_pos(src_ctl)
    out = {"skill": SK13Flip.code, "stage": SK13Flip.stage, "flip_call": bool(call),
           "delta_yaw_deg": round(float(ddeg), 2), "why": why,
           "yaw_module_deg": round(float(yaw_mod), 2), "yaw_target_deg": round(float(yaw_tgt), 2)}
    if call:
        if pos is None:
            out.update({"flip_call": False, "why": why + " · 但缺位置 (pos) ⇒ 出不了翻转序列"})
        else:
            plan = SK13Flip.plan_flip(pos, quat if isinstance(quat, (list, tuple)) else None,
                                      clear_mm=SK13Flip.params["clearance_h"] * 1000.0)
            out.update({"deg": SK13Flip.params["flip_deg"], "plan": plan, "n_steps": len(plan),
                        "pos_mm": [round(v, 2) for v in pos],
                        "clearance_mm": SK13Flip.params["clearance_h"] * 1000.0,
                        "dr_max_deg": SK13Flip.DR_DEG_STEP})
    phys = SK13Flip().clamp([0.0, 0.0, 0.0, 1.0]).get("phys") or {}
    return {"out1": out, "out2": {"phys": phys}}
