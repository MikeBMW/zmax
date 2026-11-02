# -*- coding: utf-8 -*-
"""moveit_backend — 把容器内 MoveIt plan-only 的真实规划结果接进运动规划节点

老倪 2026-11-02:「那就用, 真接上」
  ⇒ 规划节点不再只拿 MoveItPlan.plan() 那个探针, 而是读容器里
    moveit_plan_live.py 每 3s 真规划出来的轨迹 (RRTConnect + IK + FK),
    用它的**TCP 折线**当段表, 用它的**时长**当段时长, rule 后端降级成回退。

真源 (只读, 不规划不下发):
  ~/zmax/zmax_data/runtime/moveit_plan/live_plan_latest.json
    ts / plan_code / n_points / plan_time_s / end_err_mm / fk_start_pos_err_mm
    tcp_path   : 扁平 3N 个数, 单位 **米**, base 系
    joints_path: 扁平 6N 个数 (关节轨迹原件, 备份用)

铁律:
  · 过期 / plan_code≠1 / 点数不足 ⇒ 返回 None, 节点回退 rule (绝不拿旧规划冒充)
  · 单位米→毫米在这里一次换完, 下游只认毫米
  · 每段带 abs_mm (l2_daemon 段表要求绝对坐标) 和 t (MoveIt 参数化时长按段长分摊)
"""
from __future__ import annotations

import json
import os
import time

_ROOT = os.path.expanduser("~/zmax")
_LIVE = os.environ.get("ZMAX_MOVEIT_LIVE") or os.path.join(
    _ROOT, "zmax_data/runtime/moveit_plan/live_plan_latest.json")
FRESH_S = float(os.environ.get("ZMAX_MOVEIT_FRESH_S", "8.0"))   # 规划器 3s 一轮, 8s 算新鲜
MAX_SEGS = 64            # 段数上限放宽: 2.5m 行程按 50mm/段需要 51 段 (原来 40 会把路径截断)
MAX_STEP = 50.0          # 单段上限 mm (与执行器守卫同一口径)
MAX_DETOUR = 2.5         # 总长 / 直线 超过这个倍数 ⇒ 判为绕行异常(多因起点陈旧), 回退 rule
MAX_JSTEP = float(os.environ.get("ZMAX_MOVEIT_MAX_JSTEP", "0.8"))    # 单点关节最大跳变 rad (~46°)
MAX_JTOT = float(os.environ.get("ZMAX_MOVEIT_MAX_JTOT", "3.0"))      # 整条关节轨迹总行程 rad


def _resample(pts, max_step=MAX_STEP, max_segs=MAX_SEGS):
    """把 TCP 折线按长度重采样成 ≤max_segs 段, 每段 ≤max_step mm (段表口径)。"""
    if len(pts) < 2:
        return []
    # 累积长度
    cum = [0.0]
    for i in range(1, len(pts)):
        d = sum((pts[i][k] - pts[i - 1][k]) ** 2 for k in range(3)) ** 0.5
        cum.append(cum[-1] + d)
    total = cum[-1]
    if total <= 0.5:
        return []
    n = max(1, min(max_segs, int(-(-total // max_step))))       # ceil
    out = []
    for k in range(n):
        s0, s1 = total * k / n, total * (k + 1) / n
        a = _at(pts, cum, s0)
        b = _at(pts, cum, s1)
        ln = sum((b[i] - a[i]) ** 2 for i in range(3)) ** 0.5
        out.append({"i": k + 1, "kind": "move",
                    "a": [round(v, 2) for v in a], "b": [round(v, 2) for v in b],
                    "abs_mm": [round(v, 2) for v in b],
                    "len_mm": round(ln, 2)})
    return out


def _at(pts, cum, s):
    """沿折线取弧长 s 处的点 (线性插值)。"""
    if s <= 0:
        return list(pts[0])
    if s >= cum[-1]:
        return list(pts[-1])
    for i in range(1, len(cum)):
        if cum[i] >= s:
            d = cum[i] - cum[i - 1]
            r = 0.0 if d <= 1e-9 else (s - cum[i - 1]) / d
            return [pts[i - 1][k] + (pts[i][k] - pts[i - 1][k]) * r for k in range(3)]
    return list(pts[-1])


def snapshot(max_age_s=None):
    """读最新一轮 MoveIt 规划。可用 ⇒ dict(ok=True, segs=[…], …); 否则 dict(ok=False, why=…) 或 None。"""
    max_age = FRESH_S if max_age_s is None else float(max_age_s)
    try:
        with open(_LIVE, encoding="utf-8") as f:
            d = json.load(f)
    except Exception as e:                                               # noqa: BLE001
        return {"ok": False, "why": "读不到 %s (%s)" % (os.path.basename(_LIVE), type(e).__name__)}
    age = time.time() - float(d.get("ts") or 0.0)
    info = {"age_s": round(age, 2), "plan_code": d.get("plan_code"),
            "n_points": d.get("n_points"), "plan_time_s": d.get("plan_time_s"),
            "end_err_mm": d.get("end_err_mm"), "fk_start_diff_mm": d.get("fk_start_pos_err_mm"),
            "frame_age_s": d.get("frame_age_s"), "gate_reason": d.get("gate_reason"),
            "src": "moveit_plan_only(live)"}
    if age > max_age:
        return dict(info, ok=False, why="规划过期 (%.1fs > %.1fs)" % (age, max_age), segs=[])
    if int(d.get("plan_code") or 0) != 1:
        return dict(info, ok=False, why="plan_code=%s (MoveIt 规划失败)" % d.get("plan_code"), segs=[])
    tp = d.get("tcp_path") or []
    pts = []
    for i in range(0, len(tp) - 2, 3):
        try:
            pts.append([float(tp[i]) * 1000.0, float(tp[i + 1]) * 1000.0, float(tp[i + 2]) * 1000.0])
        except Exception:                                                # noqa: BLE001
            continue
    segs = _resample(pts)
    if not segs:
        return dict(info, ok=False, why="TCP 折线为空/零长 (点 %d)" % len(pts), segs=[])
    total = sum(s["len_mm"] for s in segs)
    dur = float(d.get("plan_time_s") or 0.0)
    # 绕行合理性闸: 起点陈旧(3 天前的关节)时 MoveIt 会规划出一条 2.5m 的远路, 不能直接当段表
    # 关节空间闸 (2026-11-02 实测出来的真问题): RRTConnect 会挑到"IK 另一支解",
    #   TCP 只走 50mm, 关节却整体翻 180°(J1 0.16→-3.18rad) ⇒ 实机会甩一圈 4.1m。必须按关节判。
    _jp = d.get("joints_path") or []
    _J = [_jp[i:i + 6] for i in range(0, len(_jp) - 5, 6)]
    _jt = _jm = 0.0
    for i in range(1, len(_J)):
        st = sum((_J[i][k] - _J[i - 1][k]) ** 2 for k in range(6)) ** 0.5
        _jt += st
        _jm = max(_jm, st)
    info.update(joint_total_rad=round(_jt, 3), joint_max_step_rad=round(_jm, 3))
    if _J and (_jm > MAX_JSTEP or _jt > MAX_JTOT):
        return dict(info, ok=False, total_mm=round(total, 1), segs=[],
                    why="关节空间绕行: 单步 %.2frad / 总 %.2frad (限 %.2f / %.1f) ⇒ IK 另一支解, 用 rule 回退"
                        % (_jm, _jt, MAX_JSTEP, MAX_JTOT))
    straight = sum((pts[-1][k] - pts[0][k]) ** 2 for k in range(3)) ** 0.5
    if straight > 1 and total > MAX_DETOUR * straight + 300.0:
        return dict(info, ok=False, total_mm=round(total, 1), straight_mm=round(straight, 1), segs=[],
                    why="绕行异常: 总长 %.0fmm vs 直线 %.0fmm (>%.1f×) ⇒ 起点多半陈旧, 用 rule 回退"
                        % (total, straight, MAX_DETOUR))
    for s in segs:                        # MoveIt 的参数化时长按段长分摊
        s["t"] = round(max(0.02, dur * (s["len_mm"] / total)), 4) if total > 0 and dur > 0 else None
    return dict(info, ok=True, why="ok", segs=segs, total_mm=round(total, 1),
                dur_s=round(dur, 3), n_seg=len(segs), goal_xyz_mm=[round(v, 2) for v in (d.get("goal_xyz") or [])],
                pose_note="起点=容器 side 真关节 (FK 差 %s mm)" % d.get("fk_start_pos_err_mm"))


if __name__ == "__main__":
    import pprint
    s = snapshot()
    if s:
        s2 = dict(s)
        s2["segs"] = (s2.get("segs") or [])[:2]
        pprint.pprint(s2)
    else:
        print("无")
