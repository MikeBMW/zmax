# -*- coding: utf-8 -*-
"""capture_truth_template.py — 从仿真真值录一整轮模板 (不动机器人)

为什么: bridge_episode_path 自动录模板会"自我衰减"(录到的是上一轮实际走的小路径),
越跑越小。改成: 用仿真真值(truth_xyz)录一轮完整轨迹当模板, 之后只回放不再自动录。

输出: zmax_data/ss_live/episode_template_truth.json {"path":[[dx,dy,dz]..], "dur_s":.., "src":"仿真真值"}
"""
import json
import math
import os
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VFF = os.path.join(REPO, "zmax_data", "ss_live", "plan_from_vff.json")
TRACE = os.path.join(REPO, "zmax_data", "ss_live", "trace_live.json")
OUT = os.path.join(REPO, "zmax_data", "ss_live", "episode_template_truth.json")


def _j(p):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:                                                             # noqa: BLE001
        return {}


def main():
    secs = float(os.environ.get("CAPTURE_S") or 40)
    print("📐 录仿真真值模板 %.0fs (臂不动) ..." % secs, flush=True)
    pts, stages, t0 = [], [], time.time()
    while time.time() - t0 < secs:
        v = _j(VFF)
        tr = v.get("truth_xyz") or v.get("x_truth")
        if tr and len(tr) >= 3:
            pts.append([float(tr[0]), float(tr[1]), float(tr[2])])
            stages.append(str(_j(TRACE).get("阶段") or ""))
        time.sleep(0.05)
    if len(pts) < 20:
        print("❌ 真值点太少 (%d), 没写模板" % len(pts))
        return
    o = pts[0]
    rel = [[p[0] - o[0], p[1] - o[1], p[2] - o[2]] for p in pts]
    length = sum(math.dist(rel[i], rel[i + 1]) for i in range(len(rel) - 1))
    obj = {"path": [[round(c, 5) for c in q] for q in rel], "dur_s": round(time.time() - t0, 2),
           "len_mm": round(length * 1000, 1), "n": len(rel), "src": "仿真真值 truth_xyz (40s 窗口)",
           "stages": stages, "at": time.strftime("%H:%M:%S")}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    xs = [q[0] for q in rel]
    ys = [q[1] for q in rel]
    zs = [q[2] for q in rel]
    print("✅ 模板 %d 点 · %.1fs · 路径 %.0fmm · X %.0f Y %.0f Z %.0f mm → %s"
          % (obj["n"], obj["dur_s"], obj["len_mm"],
             (max(xs) - min(xs)) * 1000, (max(ys) - min(ys)) * 1000, (max(zs) - min(zs)) * 1000, OUT))


if __name__ == "__main__":
    main()
