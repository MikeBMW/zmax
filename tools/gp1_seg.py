#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""金手指点1 —— 大动作拆小步(MoveL 途经点) 规划器/注册器。

背景: 单段 MoveL 到『金手指点1』被控制器 50113 奇异规避拦下(剩余额=全量位移)。
做法: 沿"位置线性 + 姿态 slerp"同一条路径切段(边转边移), 每段 Δ姿态<=MAX_DEG、Δ位置<=MAX_MM,
      写成途经点 + line_abs 技能 + 热读白名单, 逐段下发。

用法:
  python3 tools/gp1_seg.py            # 打印分段表 + 写途经点/技能/白名单
  python3 tools/gp1_seg.py --dry      # 只打印, 不写任何文件
"""
import json
import math
import os
import shutil
import sys
import time

ROOT = "/home/ubuntu/zmax"
DATA = os.path.join(ROOT, "data/skills/l2_atomic")
TAUGHT = os.path.join(DATA, "taught_points.json")
REG = os.path.join(DATA, "registry.json")
WL = os.path.join(DATA, "ctl_abs_skills.json")
LATEST = os.path.join(ROOT, "zmax_data/rokae_sdk/tcp_out/latest.json")

POINT = "金手指点1"
SRC_SKILL = "L2.goto_gold_pt1"
MAX_DEG = 10.0     # 每段姿态上限(度)
MAX_MM = 25.0      # 每段位置上限(mm)
PREFIX = "gp1_s"   # 途经点名/技能后缀


def qnorm(q):
    n = math.sqrt(sum(x * x for x in q)) or 1.0
    return [x / n for x in q]


def qang(a, b):
    d = abs(sum(x * y for x, y in zip(a, b)))
    return math.degrees(2.0 * math.acos(max(-1.0, min(1.0, d))))


def slerp(q0, q1, t):
    d = sum(x * y for x, y in zip(q0, q1))
    if d < 0:
        q1 = [-x for x in q1]
        d = -d
    d = max(-1.0, min(1.0, d))
    if d > 0.9995:
        return qnorm([q0[i] + t * (q1[i] - q0[i]) for i in range(4)])
    th = math.acos(d)
    s = math.sin(th)
    a = math.sin((1.0 - t) * th) / s
    b = math.sin(t * th) / s
    return qnorm([a * q0[i] + b * q1[i] for i in range(4)])


def main():
    dry = "--dry" in sys.argv
    d = json.load(open(LATEST))
    age = time.time() - os.path.getmtime(LATEST)
    p0 = [float(d["x"]), float(d["y"]), float(d["z"])]
    q0 = qnorm([float(d["qx"]), float(d["qy"]), float(d["qz"]), float(d["qw"])])
    taught = json.load(open(TAUGHT))["points"][POINT]
    p1 = [float(v) for v in taught["pos"]]
    q1 = qnorm([float(v) for v in taught["quat"]])

    dist = math.sqrt(sum((p1[i] - p0[i]) ** 2 for i in range(3))) * 1000.0
    ang = qang(q0, q1)
    N = max(int(math.ceil(ang / MAX_DEG)), int(math.ceil(dist / MAX_MM)), 1)

    print("=" * 78)
    print("金手指点1 分段规划 (边转边移 · slerp+LERP 同一条路径)")
    print("=" * 78)
    print("起始位姿(真值 帧龄%.1fs): pos=(%.4f, %.4f, %.4f) quat=(%.4f,%.4f,%.4f,%.4f)"
          % (age, *p0, *q0))
    print("目标『%s』: pos=(%.4f, %.4f, %.4f) quat=(%.4f,%.4f,%.4f,%.4f)" % (POINT, *p1, *q1))
    print("总位移 %.1fmm · 总姿态差 %.1f° · 段数 N=%d (每段<=%.0f° / %.0fmm)"
          % (dist, ang, N, MAX_DEG, MAX_MM))
    print("-" * 78)
    hdr = "段   t      目标pos(x,y,z)             Δpos(mm)          Δ姿态  累计mm  累计°"
    print(hdr)

    pts_out = {}
    skills_out = []
    prev_p, prev_q = p0, q0
    cum_mm = 0.0
    cum_deg = 0.0
    for i in range(1, N + 1):
        t = i / float(N)
        pi = [p0[j] + t * (p1[j] - p0[j]) for j in range(3)]
        qi = slerp(q0, q1, t)
        dmm = math.sqrt(sum((pi[j] - prev_p[j]) ** 2 for j in range(3))) * 1000.0
        ddeg = qang(prev_q, qi)
        cum_mm += dmm
        cum_deg += ddeg
        name = "%s%d" % (PREFIX, i)
        side = "|Δpos|=%.1f |Δ姿态|=%.2f°  cum=%.1fmm/%.1f°" % (dmm, ddeg, cum_mm, cum_deg)
        print("%2d  %.3f  (%.4f, %.4f, %.4f)  Δ=(%+.1f,%+.1f,%+.1f)  %6.2f°  %6.1f  %6.1f"
              % (i, t, pi[0], pi[1], pi[2],
                 (pi[0] - prev_p[0]) * 1000, (pi[1] - prev_p[1]) * 1000, (pi[2] - prev_p[2]) * 1000,
                 ddeg, cum_mm, cum_deg))
        pts_out[name] = {"pos": [round(v, 7) for v in pi],
                         "quat": [round(v, 7) for v in qi],
                         "desc": "金手指点1 分段途经 第%d/%d 段(自动生成)" % (i, N),
                         "source": "gp1_seg.py slerp+LERP", "recorded_at": time.strftime("%Y-%m-%d %H:%M:%S")}
        skills_out.append({
            "id": "L2.%s%d" % (PREFIX, i),
            "name": "金手指点1 段%d" % i, "icon": "🧩", "ros": "line_abs", "quat": "taught",
            "point": name, "point_locked": True, "group": "金手指点1分段",
            "guard": {"dz_down_limit_mm": 20},
            "note": "金手指点1 大动作分段(第%d/%d) — 自动生成, 到位后核真值; 失败即停",
        })
        prev_p, prev_q = pi, qi
    print("-" * 78)
    print("末段落点=目标? pos残差 %.3fmm · 姿态残差 %.4f°"
          % (math.sqrt(sum((prev_p[j] - p1[j]) ** 2 for j in range(3))) * 1000.0, qang(prev_q, q1)))
    print("=" * 78)

    if dry:
        print("[--dry] 未写任何文件")
        return

    ts = time.strftime("%Y%m%d_%H%M%S")
    # 1) 途经点
    td = json.load(open(TAUGHT))
    shutil.copy(TAUGHT, TAUGHT + ".bak_gp1seg_" + ts)
    td["points"].update(pts_out)
    json.dump(td, open(TAUGHT, "w"), ensure_ascii=False, indent=1)
    # 2) 技能
    rg = json.load(open(REG))
    shutil.copy(REG, REG + ".bak_gp1seg_" + ts)
    ids = {s["id"] for s in rg["skills"]}
    rg["skills"] = [s for s in rg["skills"] if not s["id"].startswith("L2." + PREFIX)]
    rg["skills"].extend(skills_out)
    json.dump(rg, open(REG, "w"), ensure_ascii=False, indent=1)
    # 3) 热读白名单
    wl = json.load(open(WL)) if os.path.exists(WL) else {"skills": {}}
    for s in skills_out:
        wl["skills"][s["id"]] = "🧩 " + s["name"]
    wl["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    json.dump(wl, open(WL, "w"), ensure_ascii=False, indent=1)
    print("已写入: %d 途经点 + %d 技能 + 白名单" % (len(pts_out), len(skills_out)))


if __name__ == "__main__":
    main()
