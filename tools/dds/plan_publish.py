#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""📤 550B → 550C 段表下发 (ss_plan): 让 550C 成为动作下发方

为什么 (老倪 2026-10-25): 「让 550C 成为下发方」
  现状: 页面按钮 → traj_exec → 本机 FIFO → 本机 l2_daemon → Orin 桥 (550C 全程没参与)。
  目标: traj_exec 只**发布段表**, 真正的逐段下发与真值对账由 550C 做 —— 550B 只出意图。

载荷口径 (SSPlan 复用, 不新增话题):
  · tcp_path  拉平 n×3 (m, base 系) = 规划的绝对目标点 (to_mm/1000), 不是增量
  · note      JSON 串: {plan_id, n_seg, speed_mm_s, auth_epoch, auth_remaining_s, dirs[]}
                —— 授权不靠对时: 给的是**剩余秒数**, 550C 用自己收到时刻 + remaining 判过期
  · plan_code 1 = 真机 4 段闭环口径

安全: 这里只发布, 不下发; 550C 侧有独立闸门(授权剩余/段数/包络/真值对账)。
"""
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(_HERE))
for _p in (_HERE, os.path.join(ROOT, "dds")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ⚠️ Cyclone 的 transport 必须与 ws_bridge(hub) 用**同一份** XML: 那份是 AllowMulticast=false + 显式 Peers。
#    不带它(DDS 默认多播) ⇒ 同机也发现不了单播参与者: 实测 2026-10-25 21:02/21:05 三次发布,
#    发布端 wait_for_match 报 True, 而 hub 侧 ↑ss_plan 一直是 0, 550C 从头到尾没收到 ⇒ 点了不动。
#    必须在 import zmax_node **之前**设, DomainParticipant 初始化时才读这个变量。
_CFG = os.path.join(ROOT, "dds", "cyclonedds_unicast.xml")
if os.path.exists(_CFG):
    os.environ["CYCLONEDDS_URI"] = "file://" + _CFG

from zmax_node import Node, TOPICS  # noqa: E402


def publish_plan(plan: dict, speed_mm_s: float, auth: dict, plan_id: str) -> dict:
    """把一份规划(planned_traj.json)发布成 ss_plan, 返回发布摘要。"""
    segs = plan.get("segs") or []
    if not segs:
        return {"ok": False, "why": "段表为空"}
    pts_mm = [plan.get("tcp0_mm")] + [s.get("to_mm") for s in segs]
    tcp_path = []
    for p in pts_mm:
        if not p:
            continue
        tcp_path.extend([float(v) / 1000.0 for v in list(p)[:3]])
    note = json.dumps({
        "plan_id": plan_id,
        "n_seg": len(segs),
        "speed_mm_s": float(speed_mm_s),
        "auth_epoch": int(auth.get("epoch") or 0),
        "auth_remaining_s": float(max(0.0, float(auth.get("until") or 0) - time.time())),
        "dirs": [s.get("dir") for s in segs],
        "abs_mm": [s.get("to_mm") for s in segs],
        # ⚠️ 起点必须显式给出: 550C 的"起点一致性"闸是拿**当前 TCP** 比**起点**。
        #    原来只发各段目标 ⇒ 它拿第一段目标(lift 后 z=221.9)去比当前 z=161.9, 差 60mm > 20mm
        #    ⇒ 拒发且不写台账(2026-10-25 21:14 实测: seen 里有 plan_id, 台账/状态一条没有)。
        "start_mm": [float(v) for v in (plan.get("tcp0_mm") or [])[:3]],
    }, ensure_ascii=False)

    n = Node("plan_pub_550c")
    n.pub("ss_plan")
    matched = n.wait_for_match("ss_plan", 0, 5)
    for k in range(3):                                  # 发 3 次, 抗 WS 中继瞬时抖动
        msg = TOPICS["ss_plan"](
            ts=time.time(), source="tools/traj_exec.py", group="zmax_arm",
            base_frame="base_link", plan_code=1, n_points=len(segs),
            plan_time_s=float(plan.get("total_mm") or 0) / max(1.0, float(speed_mm_s)),
            joints_path=[], tcp_path=tcp_path, start_joints=[],
            goal_xyz=[float(v) for v in (segs[-1].get("to_mm") or [0, 0, 0])[:3]],
            end_err_mm=0.0, fk_start_pos_err_mm=0.0, gate_same_source=1,
            gate_reason="550C 下发口径 (段表绝对目标)", frame_age_s=0.0, note=note)
        n.send("ss_plan", msg)
        time.sleep(0.3)
    return {"ok": True, "matched": bool(matched), "n_points": len(segs),
            "plan_id": plan_id, "tcp_path_n": len(tcp_path), "note": note}
