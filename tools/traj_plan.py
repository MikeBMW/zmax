#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""轨迹规划 → 落盘 + 画进三维视图 (只规划, 不动作)。

老倪 2026-10-25: 「你要先规划好你要执行的轨迹，在三维视图里画出三维轨迹，我看到之后，
同意后，将这个轨迹发给运动规划节点」「将三维视图下面的 对准轨迹 按钮改名成 执行轨迹」

产出:
  zmax_data/runtime/traj/planned_traj.json   段表 + 逐点三维坐标 + 预检结论(执行器/页面都读这一份)
  data/scene/overlay_spec.json               cameras.arm.boxes 里 origin='plan' 的 path3d
                                             (推流/AR 页每帧热读 ⇒ 画完立刻看得见, 不用重启)

为什么只用**轴对齐**段: 执行侧 l2_daemon 的原子技能就是 lift/lower/forward/backward/left/right
(registry.json 里 ros=line_rel + axis 字段, d_mm 1..300) —— 轨迹拆成这些段才是**真能执行**的,
凭空造一个任意 XYZ 技能等于给执行链开口子。

用法:
  python tools/traj_plan.py --segs "lift:40,backward:60,lower:40,forward:60" [--note "说明"] [--draw-only]
  python tools/traj_plan.py --show        # 只看当前规划的轨迹(不重算)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

TRAJ_DIR = os.path.join(REPO, "zmax_data", "runtime", "traj")
PLAN = os.path.join(TRAJ_DIR, "planned_traj.json")
SPEC = os.path.join(REPO, "data", "scene", "overlay_spec.json")

# 技能 → (轴 0=x/1=y/2=z, 符号)；数值口径: +X 前 · +Y 左 · +Z 上
AX = {
    "lift": (2, +1), "lower": (2, -1),
    "forward": (0, +1), "backward": (0, -1),
    "left": (1, +1), "right": (1, -1),
}
SKILL = {
    "lift": "L2.lift", "lower": "L2.lower", "forward": "L2.forward", "backward": "L2.backward",
    "left": "L2.left", "right": "L2.right",
}
CN = {"lift": "抬升(+Z)", "lower": "下降(-Z)", "forward": "前进(+X)", "backward": "后退(-X)",
      "left": "向左(+Y)", "right": "向右(-Y)"}
LIMIT = 300.0          # registry.json 单段 d_mm 上限
MIN_CLEAR = 20.0       # 与 precheck 同一门槛


def live_tcp():
    """活读真机 TCP(mm) —— 只读 Orin 宿主 ROS, 不用陈旧文件。"""
    import precheck_move as PM
    q, tcp, age = PM.read_joints()
    if age > 5.0:
        raise SystemExit("⛔ 位姿帧龄 %.1fs > 5s ⇒ 不规划(拿旧位姿画轨迹等于画错)" % age)
    return [float(v) for v in tcp], q, age


def precheck_point(tcp_mm):
    """单点净空: 复用 precheck 的盒表与算法(当前姿态连杆 + 到该点的直线)。"""
    import precheck_move as PM
    boxes, margin = PM.load_boxes()
    worst = (1e9, "", "")
    for b in boxes:
        d = PM.dist_point_box(tcp_mm, b["lo"], b["hi"])
        if d < worst[0]:
            worst = (d, "夹爪/TCP", b["name"])
    return {"clear_mm": round(worst[0], 1), "obj": worst[2], "ok": worst[0] >= MIN_CLEAR}


def build_segs(seg_spec):
    segs, bad = [], []
    for item in [s.strip() for s in seg_spec.split(",") if s.strip()]:
        if ":" not in item:
            bad.append(item)
            continue
        k, v = item.split(":", 1)
        k = k.strip().lower()
        try:
            d = float(v)
        except ValueError:
            bad.append(item)
            continue
        if k not in AX:
            bad.append(item)
            continue
        if d <= 0:
            bad.append(item + "(距离必须>0)")
            continue
        if d > LIMIT:
            bad.append("%s:%.0f(超过单段上限 %.0fmm, 请拆段)" % (k, d, LIMIT))
            continue
        segs.append({"skill": SKILL[k], "dir": k, "axis": AX[k][0], "sign": AX[k][1], "d_mm": d})
    if bad:
        raise SystemExit("⛔ 段无法解析: %s（可用: %s）" % (", ".join(bad), "/".join(sorted(AX))))
    return segs


def draw(points_m, label):
    """把轨迹写进 overlay_spec 的 plan 轨迹(热读文件, 写完页面即见)。先备份。"""
    if not os.path.exists(SPEC):
        return "⚠ overlay_spec.json 不存在, 未画"
    shutil.copy2(SPEC, SPEC + ".bak_traj_%s" % time.strftime("%Y%m%d_%H%M%S"))
    d = json.load(open(SPEC, encoding="utf-8"))
    arm = ((d.get("cameras") or {}).get("arm") or {})
    boxes = arm.get("boxes") or []
    keep = [b for b in boxes if not (b.get("kind") == "path3d" and b.get("origin") == "plan")]
    keep.append({"origin": "plan", "label": label, "kind": "path3d", "pts3d": points_m,
                 "width": 4, "no_label": True, "conf": 1.0})
    arm["boxes"] = keep
    d.setdefault("cameras", {})["arm"] = arm
    d["ts"] = time.time()
    d["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    tmp = SPEC + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, SPEC)
    return "已画 %d 点" % len(points_m)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--segs", default="", help='段序列, 例 "lift:40,backward:60,lower:40,forward:60"')
    ap.add_argument("--note", default="")
    ap.add_argument("--show", action="store_true", help="只显示当前规划")
    ap.add_argument("--draw-only", action="store_true", help="不重算, 只把已规划轨迹重新画进视图")
    a = ap.parse_args()

    os.makedirs(TRAJ_DIR, exist_ok=True)

    if a.show:
        if not os.path.exists(PLAN):
            print("还没有规划轨迹")
            return
        d = json.load(open(PLAN, encoding="utf-8"))
        print("规划 %s · %d 段 · 总长 %.0fmm · %s" % (
            time.strftime("%m-%d %H:%M:%S", time.localtime(d["ts"])), len(d["segs"]),
            d.get("total_mm", 0), d.get("note", "")))
        for s in d["segs"]:
            print("  %-2d %-9s %6.0fmm  →  %s" % (s["i"], s["dir"], s["d_mm"],
                                                  [round(v, 1) for v in s["to_mm"]]))
        return

    if a.draw_only:
        d = json.load(open(PLAN, encoding="utf-8"))
        print(draw(d["pts_m"], d["label"]))
        return

    if not a.segs:
        raise SystemExit("⛔ 要么给 --segs 规划, 要么 --show/--draw-only")

    segs = build_segs(a.segs)
    tcp, q, age = live_tcp()
    pts = [list(tcp)]
    cur = list(tcp)
    for i, s in enumerate(segs, 1):
        cur = list(cur)
        cur[s["axis"]] += s["sign"] * s["d_mm"]
        s["i"] = i
        s["from_mm"] = [round(v, 1) for v in (cur if False else pts[-1])]
        s["to_mm"] = [round(v, 1) for v in cur]
        s["cn"] = CN[s["dir"]]
        pts.append(list(cur))

    checks = []
    for p in pts:
        c = precheck_point(p)
        c["pos_mm"] = [round(v, 1) for v in p]
        checks.append(c)
    worst = min(c["clear_mm"] for c in checks)
    ok = all(c["ok"] for c in checks)
    total = sum(s["d_mm"] for s in segs)

    rec = {
        "ts": time.time(), "src": "tools/traj_plan.py", "note": a.note,
        "tcp0_mm": [round(v, 1) for v in tcp], "pose_age_s": round(age, 2),
        "segs": segs, "pts_mm": [[round(v, 1) for v in p] for p in pts],
        "pts_m": [[round(v / 1000.0, 5) for v in p] for p in pts],
        "total_mm": round(total, 1), "n_seg": len(segs),
        "precheck": {"ok": ok, "worst_mm": round(worst, 1), "min_clear_mm": MIN_CLEAR, "points": checks},
        "label": "规划轨迹 %d点/%d段/%.0fmm%s" % (len(pts), len(segs), total,
                                                (" · " + a.note) if a.note else ""),
    }
    tmp = PLAN + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=1)
    os.replace(tmp, PLAN)

    # 同时落一份"规划段表"到运动规划节点(n_moveit)读的那份唯一依据, 画布节点上就能看到这条轨迹
    #   字段名沿用既有段表口径(pos/speed/dir/lin_mm), 不另造一套
    try:
        import datetime as _dt
        segs_pub = [{"id": s["i"], "name": s["skill"], "pos": [v / 1000.0 for v in s["to_mm"]],
                     "speed": None, "dir": s["cn"], "lin_mm": s["d_mm"], "quat": None, "service": False}
                    for s in segs]
        pub = {"skill": "TRAJ.planned", "backend": "traj", "src": "tools/traj_plan.py",
               "n": len(segs_pub), "segs": segs_pub, "lin_total_mm": round(total, 1),
               "note": a.note, "precheck_ok": ok, "worst_clear_mm": round(worst, 1),
               "t": time.time(), "t_pub": _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        pdir = os.path.join(REPO, "zmax_data", "runtime", "plan")
        os.makedirs(pdir, exist_ok=True)
        with open(os.path.join(pdir, "plan_latest.json"), "w", encoding="utf-8") as f:
            json.dump(pub, f, ensure_ascii=False, indent=1)
    except Exception as e:                                                   # noqa: BLE001
        print("⚠ 段表没写进 plan_latest.json: %s (不影响规划/画线)" % str(e)[:80])

    print("起点 TCP = [%.1f, %.1f, %.1f] mm (帧龄 %.1fs)" % (tcp[0], tcp[1], tcp[2], age))
    for s in segs:
        print("  %-2d %-9s %6.0fmm  →  %s" % (s["i"], s["dir"], s["d_mm"], [round(v, 1) for v in s["to_mm"]]))
    print("总长 %.1fmm · 最差净空 %.1fmm ⇒ 预检 %s" % (total, worst, "✅ PASS" if ok else "❌ FAIL"))
    if not ok:
        for c in checks:
            if not c["ok"]:
                print("   · %.1fmm 处净空仅 %.1fmm (对 %s)" % (c["pos_mm"][0], c["clear_mm"], c["obj"]))
    print(draw(rec["pts_m"], rec["label"]))
    print("落盘: %s" % PLAN)


if __name__ == "__main__":
    main()
