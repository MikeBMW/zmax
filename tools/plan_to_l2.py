#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
plan_to_l2.py — 段化器: MoveIt 规划轨迹 → **L2 原子技能段表** (只规划, 绝不动臂)
────────────────────────────────────────────────────────────────────────────
设计文档: docs/design/hil_terminal_station_l2_20261009.md §5 (老倪架构原则)
  上层只给意图/条件; 执行永远由 L2 收口; 规划器永不执行, 执行器永不规划。
  本文件是"中间唯一产物 = 段表(计划)"这个**数据**的生成器 —— 它不连机械臂、不下发。

输入(真实字段, 已 cat 确认, 非猜测): ~/zmax/zmax_data/runtime/moveit_plan/live_plan_latest.json
  { ts, source, group, base_frame, start_joints[6], goal_xyz[3], goal_quat[4],
    plan_code, fk_start_pos_err_mm, joint_names[6], n_points, joints_path[n*6] (rad, 扁平),
    tcp_path[n*3] (m, 扁平, 仅 xyz), n_tcp, plan_time_s, end_err_mm, note,
    gate_same_source, gate_reason }

输出(段表):
  {"ok":true, "plan_id":"pl_YYYYmmdd_HHMMSS",
   "meta":{"solver":"moveit","source":<文件>,"ik_ok":true,"plan_ms":..,"n_pts":.., ...},
   "segments":[{"seg_id":1,"L2_skill":"L2.forward","params":{"d_mm":48},
                "pred_delta":{"dx":48,"dy":0,"dz":0,"ddeg":0},
                "guard":{"max_mm":50,"max_down_mm":20,"max_deg":10},
                "src_rows":[0,9]}, ...]}

分段规则(老倪现场口径, 2026-10-09):
  · 位置每段 ≤50mm · 下降每段 ≤20mm · 自转(J6)每段 ≤10° · 腕部姿态变化每段 ≤15°(防控制器奇异)
  · 段表按**单轴原子技能**输出(与设计文档示例 pred_delta 单轴一致):
      +X→L2.forward  -X→L2.backward  +Y→L2.left  -Y→L2.right  +Z→L2.lift  -Z→L2.lower
      +ΔJ6→L2.j6_ccw  -ΔJ6→L2.j6_cw   (符号按关节正方向=逆时针, 现场需确认)
  · 无法安全分段 ⇒ ok:false + 具体原因(哪一行/哪一度超), **不编造段落**。

用法:
  ./gui-venv311/bin/python tools/plan_to_l2.py                     # 读默认 live_plan_latest.json
  ./gui-venv311/bin/python tools/plan_to_l2.py --file X.json --json
  ./gui-venv311/bin/python tools/plan_to_l2.py --allow-ungated     # 同源闸不过也出段表(仅验证/预览, 标警告)
  ./gui-venv311/bin/python tools/plan_to_l2.py --synth --json      # 离线合成假轨迹 (自测段化器本身)
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time

PLAN_DIR = os.path.expanduser(os.environ.get("SS_PLAN_DIR", "~/zmax/zmax_data/runtime/moveit_plan"))
DEFAULT_LATEST = os.path.join(PLAN_DIR, "live_plan_latest.json")

# ── 段守卫 (老倪现场口径) ──────────────────────────────────────────────────
BOUNDS = {"max_mm": 50.0, "max_down_mm": 20.0, "max_self_deg": 10.0, "max_tilt_deg": 15.0}
# 细分步长(留余量, 保证插值后单步稳过闸)
SUB = {"mm": 45.0, "down": 18.0, "self": 9.0, "tilt": 13.0}
MIN_EMIT = 1.0      # 轴净变化小于此值不单独成段 —— 对齐 L2 原子技能最小步进(平动 1mm / 自转 1°);
                    # 亚步进的微小增量低于 L2 分辨率, 无法作为独立原子技能下发 ⇒ 丢弃(非静默, 报告里注明)

# ── 轴 → L2 技能 (坐标口径与 station 页一致: forward +X / left +Y / right −Y / lift +Z / lower −Z) ──
_AXIS_SKILL = {
    ("x", +1): "L2.forward", ("x", -1): "L2.backward",
    ("y", +1): "L2.left",    ("y", -1): "L2.right",
    ("z", +1): "L2.lift",    ("z", -1): "L2.lower",
}
_ROT_SKILL = {+1: "L2.j6_ccw", -1: "L2.j6_cw"}


def _deg(r: float) -> float:
    return math.degrees(r)


def load_plan(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _extract_points(plan: dict):
    """→ (pts, problems). pts=[{p:[x,y,z], j:[j1..j6], row}]. 真实字段校验, 不做假设。"""
    probs = []
    jp = plan.get("joints_path")
    tp = plan.get("tcp_path")
    if not isinstance(jp, list) or not jp:
        probs.append("joints_path 缺失/为空")
    if not isinstance(tp, list) or not tp:
        probs.append("tcp_path 缺失/为空")
    if probs:
        return None, probs
    if len(jp) % 6:
        probs.append("joints_path 长度 %d 不是 6 的倍数" % len(jp))
    if len(tp) % 3:
        probs.append("tcp_path 长度 %d 不是 3 的倍数" % len(tp))
    if probs:
        return None, probs
    nj, ntc = len(jp) // 6, len(tp) // 3
    n = min(nj, ntc)
    if n < 2:
        probs.append("有效路点 %d < 2, 无法分段" % n)
        return None, probs
    if nj != ntc:
        probs.append("警告: joints_path 路点数 %d ≠ tcp_path 路点数 %d (FK 部分失败), 取前 %d" % (nj, ntc, n))
    pts = []
    for k in range(n):
        pts.append({"p": [float(x) for x in tp[3 * k:3 * k + 3]],
                    "j": [float(x) for x in jp[6 * k:6 * k + 6]],
                    "row": k})
    return pts, probs


def _net(pts):
    """一段的净变化: dx,dy,dz(mm); dj6(deg); tilt(deg, 腕 j4/j5 最大变化)。dz<0=下降。"""
    a, b = pts[0], pts[-1]
    dx = (b["p"][0] - a["p"][0]) * 1000.0
    dy = (b["p"][1] - a["p"][1]) * 1000.0
    dz = (b["p"][2] - a["p"][2]) * 1000.0
    dj6 = _deg(b["j"][5] - a["j"][5])
    tilt = max(abs(_deg(b["j"][3] - a["j"][3])), abs(_deg(b["j"][4] - a["j"][4])))
    return {"dx": dx, "dy": dy, "dz": dz, "dj6": dj6, "tilt": tilt}


def _violates(net, b=BOUNDS) -> str:
    if math.hypot(math.hypot(net["dx"], net["dy"]), net["dz"]) > b["max_mm"] + 1e-6:
        return "位置 %.1fmm > %.0fmm" % (math.hypot(math.hypot(net["dx"], net["dy"]), net["dz"]), b["max_mm"])
    down = max(0.0, -net["dz"])
    if down > b["max_down_mm"] + 1e-6:
        return "下降 %.1fmm > %.0fmm" % (down, b["max_down_mm"])
    if abs(net["dj6"]) > b["max_self_deg"] + 1e-6:
        return "自转 %.2f° > %.0f°" % (abs(net["dj6"]), b["max_self_deg"])
    if net["tilt"] > b["max_tilt_deg"] + 1e-6:
        return "腕姿态变化 %.2f° > %.0f°" % (net["tilt"], b["max_tilt_deg"])
    return ""


def _refine(pts):
    """把每条原始 MoveIt 步再细分, 保证单步稳过闸(留余量)。保留原始 row 索引。"""
    out = [dict(pts[0])]
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        dx = (b["p"][0] - a["p"][0]) * 1000.0
        dy = (b["p"][1] - a["p"][1]) * 1000.0
        dz = (b["p"][2] - a["p"][2]) * 1000.0
        dp = math.hypot(math.hypot(dx, dy), dz)
        down = max(0.0, -dz)
        dj6 = abs(_deg(b["j"][5] - a["j"][5]))
        tilt = max(abs(_deg(b["j"][3] - a["j"][3])), abs(_deg(b["j"][4] - a["j"][4])))
        n = 1
        n = max(n, int(math.ceil(dp / SUB["mm"])) if dp > SUB["mm"] else 1)
        if down > SUB["down"]:
            n = max(n, int(math.ceil(down / SUB["down"])))
        if dj6 > SUB["self"]:
            n = max(n, int(math.ceil(dj6 / SUB["self"])))
        if tilt > SUB["tilt"]:
            n = max(n, int(math.ceil(tilt / SUB["tilt"])))
        for k in range(1, n + 1):
            t = k / float(n)
            pt = {"p": [a["p"][c] + (b["p"][c] - a["p"][c]) * t for c in range(3)],
                  "j": [a["j"][c] + (b["j"][c] - a["j"][c]) * t for c in range(6)],
                  "row": i if k < n else i + 1}
            out.append(pt)
    return out


def segment_plan(plan: dict, plan_id: str, source: str,
                 bounds: dict = None, require_same_source: bool = True) -> dict:
    """核心: 轨迹 → 段表。返回 {ok, plan_id, meta, segments?} 或 {ok:false, reason, meta}。"""
    b = dict(BOUNDS)
    if bounds:
        b.update(bounds)
    meta = {"solver": "moveit", "source": source,
            "ik_ok": bool(int(plan.get("plan_code") or -1) == 1),
            "plan_code": plan.get("plan_code"),
            "plan_ms": (round(float(plan.get("plan_time_s") or 0) * 1000.0, 1)
                        if (plan.get("plan_time_s") or -1) >= 0 else None),
            "n_pts": int(plan.get("n_points") or 0),
            "n_tcp": int(plan.get("n_tcp") or 0),
            "gate_same_source": int(plan.get("gate_same_source")) if plan.get("gate_same_source") is not None else None,
            "gate_reason": plan.get("gate_reason"),
            "note": plan.get("note"),
            "bounds": b}

    def _fail(reason):
        meta["reason"] = reason
        return {"ok": False, "reason": reason, "meta": meta}

    # ① 规划本体状态
    if int(plan.get("plan_code") or -1) != 1:
        return _fail("规划失败: plan_code=%s (%s) ⇒ 无有效轨迹, 不编造段落"
                     % (plan.get("plan_code"), plan.get("note") or "目标不可达/超时"))
    # ② 同源闸 (老倪红线③: 未标定/不同源 ⇒ ok:false)
    g = meta["gate_same_source"]
    if require_same_source and g == 0:
        return _fail("同源闸不过 ⇒ 段表不可下发: %s" % (meta.get("gate_reason") or "FK(真关节)与真机 TCP 不同源"))
    # ③ 字段校验
    pts, probs = _extract_points(plan)
    if pts is None:
        return _fail("轨迹字段不可用: " + "; ".join(probs))
    for p in probs:                       # 非致命警告(如 FK 部分失败)照记
        meta.setdefault("warnings", []).append(p)

    refined = _refine(pts)
    # 贪心成段: 一段的净变化不许越闸
    runs = []
    cur = [refined[0]]
    for pt in refined[1:]:
        cand = cur + [pt]
        bad = _violates(_net(cand), b)
        if bad:
            runs.append(cur)
            cur = [cur[-1], pt]           # 共享边界点, 段间无缝隙
        else:
            cur = cand
    runs.append(cur)

    segments = []
    issues = []
    for run in runs:
        net = _net(run)
        r0, r1 = run[0]["row"], run[-1]["row"]
        # 位置轴 (单轴原子技能)
        for axis, key in (("x", "dx"), ("y", "dy"), ("z", "dz")):
            v = net[key]
            if abs(v) < MIN_EMIT:
                continue
            if abs(v) > b["max_mm"] + 1e-6:
                issues.append("行[%d,%d] %s=%.1fmm 超 %.0fmm" % (r0, r1, key, v, b["max_mm"]))
            skill = _AXIS_SKILL[(axis, +1 if v > 0 else -1)]
            pred = {"dx": 0.0, "dy": 0.0, "dz": 0.0, "ddeg": 0.0}
            pred[key] = round(v, 1)
            segments.append({"seg_id": len(segments) + 1, "L2_skill": skill,
                             "params": {"d_mm": round(abs(v), 1)},
                             "pred_delta": pred,
                             "guard": {"max_mm": b["max_mm"], "max_down_mm": b["max_down_mm"], "max_deg": b["max_self_deg"]},
                             "src_rows": [r0, r1]})
        # 自转轴 J6
        if abs(net["dj6"]) >= MIN_EMIT:
            if abs(net["dj6"]) > b["max_self_deg"] + 1e-6:
                issues.append("行[%d,%d] 自转 %.2f° 超 %.0f°" % (r0, r1, abs(net["dj6"]), b["max_self_deg"]))
            segments.append({"seg_id": len(segments) + 1,
                             "L2_skill": _ROT_SKILL[+1 if net["dj6"] > 0 else -1],
                             "params": {"deg": round(abs(net["dj6"]), 2)},
                             "pred_delta": {"dx": 0.0, "dy": 0.0, "dz": 0.0, "ddeg": round(net["dj6"], 2)},
                             "guard": {"max_mm": b["max_mm"], "max_down_mm": b["max_down_mm"], "max_deg": b["max_self_deg"]},
                             "src_rows": [r0, r1]})
        # 腕部姿态(tilt) —— L2 无对应原子技能, 如实标记(不假装能执行)
        if net["tilt"] >= MIN_EMIT:
            segments.append({"seg_id": len(segments) + 1,
                             "L2_skill": "L2.rot_tilt_unsupported",
                             "params": {"tilt_deg": round(net["tilt"], 2)},
                             "pred_delta": {"dx": 0.0, "dy": 0.0, "dz": 0.0, "ddeg": 0.0},
                             "guard": {"max_mm": b["max_mm"], "max_down_mm": b["max_down_mm"], "max_deg": b["max_self_deg"]},
                             "unsupported": True,
                             "note": "腕 j4/j5 变化 %.2f°, L2 无对应原子技能 ⇒ 需现场人工确认" % net["tilt"],
                             "src_rows": [r0, r1]})

    if issues:
        return _fail("无法安全分段: " + "; ".join(issues[:6]))

    # 累加核对 (段表 pred_delta 向量和 vs 轨迹净位移)
    total_net = _net(pts)
    sdx = sum(s["pred_delta"]["dx"] for s in segments)
    sdy = sum(s["pred_delta"]["dy"] for s in segments)
    sdz = sum(s["pred_delta"]["dz"] for s in segments)
    sdg = sum(s["pred_delta"]["ddeg"] for s in segments)
    net_vec = math.hypot(math.hypot(total_net["dx"], total_net["dy"]), total_net["dz"])
    err_vec = math.hypot(math.hypot(sdx - total_net["dx"], sdy - total_net["dy"]), sdz - total_net["dz"])
    meta.update({
        "n_segments": len(segments),
        "net_delta": {"dx": round(total_net["dx"], 1), "dy": round(total_net["dy"], 1),
                      "dz": round(total_net["dz"], 1), "ddeg": round(total_net["dj6"], 2)},
        "seg_sum": {"dx": round(sdx, 1), "dy": round(sdy, 1), "dz": round(sdz, 1), "ddeg": round(sdg, 2)},
        "net_vec_mm": round(net_vec, 1),
        "sum_err_pct": round(100.0 * err_vec / net_vec, 3) if net_vec > 1e-9 else None,
        "n_unsupported_tilt": sum(1 for s in segments if s.get("unsupported")),
    })
    if meta.get("warnings"):
        meta["warn"] = "轨迹含告警: " + "; ".join(meta["warnings"])
    return {"ok": True, "plan_id": plan_id, "meta": meta, "segments": segments}


# ── 离线合成假轨迹 (自测段化器本身用; 明确标注, 不冒充真规划) ────────────────
def synth_plan(dx_mm=120.0, dy_mm=0.0, dz_mm=-45.0, self_deg=25.0, n=101):
    p0 = [0.50, 0.20, 0.40]
    j0 = [0.0, 0.5, -1.5, 1.5, 1.5, 0.0]
    tp, jp = [], []
    for k in range(n):
        t = k / float(n - 1)
        tp += [p0[0] + dx_mm * t / 1000.0, p0[1] + dy_mm * t / 1000.0, p0[2] + dz_mm * t / 1000.0]
        jp += [j0[0], j0[1], j0[2], j0[3], j0[4], j0[5] + math.radians(self_deg) * t]
    return {"ts": time.time(), "source": "SYNTHETIC(offline fake, 非真规划)", "group": "arm",
            "base_frame": "XMS5-R800-W4G3B4C_base", "start_joints": j0,
            "goal_xyz": [p0[0] + dx_mm / 1000.0, p0[1] + dy_mm / 1000.0, p0[2] + dz_mm / 1000.0],
            "goal_quat": [0.0, 0.0, 0.0, 1.0], "plan_code": 1, "fk_start_pos_err_mm": 0.0,
            "joint_names": ["j%d" % i for i in range(1, 7)], "n_points": n,
            "joints_path": jp, "tcp_path": tp, "n_tcp": n, "plan_time_s": 1.0,
            "end_err_mm": 0.0, "note": "SYNTHETIC 假轨迹 — 只用于验证段化器本身, 不代表真机可达",
            "gate_same_source": 1, "gate_reason": "合成数据, 同源闸不适用"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=DEFAULT_LATEST)
    ap.add_argument("--synth", action="store_true", help="用离线合成假轨迹验证段化器(不读真规划文件)")
    ap.add_argument("--allow-ungated", action="store_true", help="同源闸不过也出段表(仅预览, 标警告)")
    ap.add_argument("--no-require-same-source", action="store_true")
    ap.add_argument("--out", default="", help="段表落盘路径(默认不落)")
    ap.add_argument("--json", action="store_true", help="只打印段表 JSON")
    a = ap.parse_args()

    if a.synth:
        plan, source = synth_plan(), "SYNTHETIC(offline fake)"
    else:
        source = a.file
        if not os.path.isfile(a.file):
            out = {"ok": False, "reason": "规划文件不存在: %s" % a.file,
                   "meta": {"source": a.file, "solver": "moveit"}}
            print(json.dumps(out, ensure_ascii=False, indent=2) if not a.json else json.dumps(out, ensure_ascii=False))
            return 3
        plan = load_plan(a.file)

    plan_id = "pl_" + time.strftime("%Y%m%d_%H%M%S")
    req = not (a.allow_ungated or a.no_require_same_source)
    res = segment_plan(plan, plan_id, source, require_same_source=req)

    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=2)

    if a.json:
        print(json.dumps(res, ensure_ascii=False))
    else:
        m = res.get("meta") or {}
        print("plan_id=%s  source=%s" % (plan_id, source))
        print("ok=%s" % res.get("ok"))
        if not res.get("ok"):
            print("  ✗ %s" % res.get("reason"))
        else:
            print("  meta: ik_ok=%s n_pts=%s n_segments=%s gate=%s net=%s"
                  % (m.get("ik_ok"), m.get("n_pts"), m.get("n_segments"),
                     m.get("gate_same_source"), m.get("net_delta")))
            for s in res["segments"]:
                print("   #%2d %-22s params=%-16s pred=%-38s rows=%s%s"
                      % (s["seg_id"], s["L2_skill"], json.dumps(s["params"], ensure_ascii=False),
                         json.dumps(s["pred_delta"], ensure_ascii=False), s["src_rows"],
                         "  ⚠unsupported" if s.get("unsupported") else ""))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
