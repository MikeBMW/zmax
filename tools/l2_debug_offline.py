#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""l2_daemon 离线调试台 —— 不读 FIFO、不下发、不动臂，只把"命令 → 计划"算出来。

📚 2026-10-18 老倪: 「l2_daemon.py 我怎么 debug，断点放在哪里？」

为什么要有这个：
  l2_daemon 是常驻 FIFO 执行器 —— 直接把断点压在线上进程里，进程一停，臂还按上一条命令在动，
  而且 8793 那头的回执窗口会超时。所以调试分两层：
    ① 计划层（这个脚本）：把 dispatch 里"算目标/分段/守卫"的那一段单独跑，断点随便放，零风险
    ② 执行层：另起一个 dry 实例（ZMAX_L2_FIFO=/tmp/l2_dbg.fifo），命令带 "dry":true

用法:
  ./gui-venv311/bin/python tools/l2_debug_offline.py L2.lift --d_mm 50
  ./gui-venv311/bin/python tools/l2_debug_offline.py L2.goto_space1 --manual
  ./gui-venv311/bin/python tools/l2_debug_offline.py L2.slot1 --speed 32
  ... --json            # 只打 JSON, 便于对比
"""
import argparse
import importlib.util
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))


def load_daemon():
    """把 l2_daemon.py 当模块加载（它 import 时不启线程，安全）。"""
    spec = importlib.util.spec_from_file_location("l2d", os.path.join(REPO, "tools", "l2_daemon.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def live_pose():
    """真值位姿（只读 tcp_out/latest.json）: (x,y,z), quat。"""
    for p in ("zmax_data/rokae_sdk/tcp_out/latest.json", "zmax_data/ss_live/tcp.json"):
        fp = os.path.join(REPO, p)
        if not os.path.exists(fp):
            continue
        try:
            d = json.load(open(fp, encoding="utf-8"))
        except Exception:                                                # noqa: BLE001
            continue
        xyz = [d.get("x"), d.get("y"), d.get("z")]
        if all(v is not None for v in xyz):
            quat = [d.get("qx"), d.get("qy"), d.get("qz"), d.get("qw")]
            return [float(v) for v in xyz], [float(v) for v in quat], p
    return None, None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("skill")
    ap.add_argument("--d_mm", type=float)
    ap.add_argument("--deg", type=float)
    ap.add_argument("--speed", type=float, default=32.0)
    ap.add_argument("--manual", action="store_true", help="等价页面 manual_point=1")
    ap.add_argument("--allow_climb_mm", type=float)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--pose", help="手动指定当前 xyz, 逗号分隔 (默认读真值)")
    a = ap.parse_args()

    m = load_daemon()
    reg = json.load(open(m.REG_PATH, encoding="utf-8"))
    skills = {s["id"]: s for s in reg["skills"]}
    sk = skills.get(a.skill)
    if not sk:
        print("未知技能 %r（可用示例: %s）" % (a.skill, ", ".join(list(skills)[:8])))
        return 2

    if a.pose:
        cur = [float(v) for v in a.pose.split(",")]
        curq, src = None, "手动 --pose"
    else:
        cur, curq, src = live_pose()
        if cur is None:
            print("读不到真值位姿（tcp_out/latest.json）—— 用 --pose x,y,z 指定")
            return 2

    spec = {"skill": a.skill, "speed": a.speed, "dry": True}
    if a.d_mm is not None:
        spec["d_mm"] = a.d_mm
    if a.deg is not None:
        spec["deg"] = a.deg
    if a.manual:
        spec["manual_point"] = True
    if a.allow_climb_mm is not None:
        spec["allow_climb_mm"] = a.allow_climb_mm

    pts = m._load_points()
    steps = sk.get("steps") or []
    # 单步技能 (方向键/抬升/下降/绝对点/旋转/J6): 没有 steps, 走 dispatch 里另一条分支
    if not steps:
        ros = sk.get("ros")
        if ros == "pose_rot":
            r = m.build_pose_rot(sk, spec, cur, curq)
            print("单步 pose_rot → %s" % (r,))
            return 0
        if ros == "j6_rot":
            r = m.build_j6_rot(sk, spec, cur, curq)
            print("单步 j6_rot → %s" % (r,))
            return 0
        r = m.build_move(sk, spec, pts, cur, curq)
        if not r:
            print("build_move 返回 None（位姿/点位不可用）")
            return 2
        tgt, quat = r[0], r[1]
        d = [(t - c) * 1000.0 for t, c in zip(tgt, cur)]
        print("单步 %-12s ros=%-9s" % (a.skill, ros))
        print("  起点 %s → 目标 %s" % (["%.4f" % v for v in cur], ["%.4f" % v for v in tgt]))
        print("  Δ = (%+.1f, %+.1f, %+.1f) mm  %s" % (d[0], d[1], d[2], m._dir_label(*d)))
        _gd = (sk.get("guard") or {}).get("dz_down_limit_mm")
        if _gd is not None and d[2] < -abs(float(_gd)):
            print("  🛡 守卫: dz_down_limit_mm=%.0f ⇒ 要下降 %.1fmm，需带 allow_down_mm 才放行" % (float(_gd), -d[2]))
        return 0
    out = {"skill": a.skill, "ros": sk.get("ros"), "mode": sk.get("exec_mode") or sk.get("mode"),
           "steps": len(steps), "start": cur, "start_src": src, "plans": []}

    print("技能 %-16s ros=%-6s 段数=%d" % (a.skill, sk.get("ros"), len(steps)))
    print("起点 %s  (来源 %s)" % (["%.4f" % v for v in cur], src))
    c = list(cur)
    for i, st in enumerate(steps, 1):
        pl = m.plan_stage(sk, st, pts, spec, c)
        rec = {"stage": i, "name": st.get("name") or st.get("point") or "",
               "err": pl.get("err") or "", "pos": pl.get("pos"),
               "delta_mm": pl.get("delta_mm") or pl.get("d_mm"), "call": (pl.get("call") or "")[:160]}
        out["plans"].append(rec)
        if pl.get("err"):
            print("  段 %d/%d  🛑 拒绝: %s" % (i, len(steps), pl["err"]))
            break
        print("  段 %d/%d  → pos=%s  Δ=%s  %s" %
              (i, len(steps), ["%.4f" % v for v in pl["pos"]], rec["delta_mm"], rec["name"]))
        print("        call: %s" % rec["call"])
        c = pl["pos"]

    if a.json:
        print(json.dumps(out, ensure_ascii=False, default=str))
    return 0


def _load_reg(m):
    """兼容不同版本: 优先用模块自带的 loader。"""
    for name in ("load_registry", "registry", "load_reg"):
        f = getattr(m, name, None)
        if callable(f):
            return f()
    raise RuntimeError("l2_daemon 里找不到注册表 loader（看 main() 里 reg 怎么来的）")


if __name__ == "__main__":
    sys.exit(main())
