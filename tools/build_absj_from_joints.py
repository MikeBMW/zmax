#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_absj_from_joints.py — 从"示教关节角日志"抽出一圈, 产出 MoveAbsJ 回放轨迹。

输入: zmax_data/rokae_sdk/teach_joints_*.jsonl   (10Hz, {j[6], p[3], rpy[3]})
输出: zmax_data/rokae_sdk/real_traj_absj.json     {"frames":[{q,p,rpy}]}

做法: 取**最后一段**离开初始位再回到初始位的连续运动(中间允许停顿), 原样保留关节角,
      按 20Hz 抽稀(去重复帧), 不动点、不插值 —— 关节空间回放不需要笛卡尔插值。
"""
from __future__ import annotations

import glob
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    src = sorted(glob.glob(os.path.join(ROOT, "zmax_data/rokae_sdk/teach_joints_*.jsonl")))[-1]
    rows = []
    for l in open(src):
        try:
            r = json.loads(l)
        except Exception:
            continue
        if r.get("j") and r.get("p"):
            rows.append(r)
    P = [r["p"] for r in rows]
    home = P[0]
    far = [i for i, p in enumerate(P) if math.dist(p, home) > 25.0]
    if not far:
        print("日志里没有运动(一直在初始位)")
        return 1
    # 找最后一段: 从最后一次"离开 home"的起点往前回溯到 home 附近
    # 取"最后一个完整一圈": 从末尾(回到 home)往前找, 直到该窗口里出现过离开 400mm 以上的点
    i_end = far[-1]
    while i_end + 1 < len(P) and math.dist(P[i_end + 1], home) <= 25.0:
        i_end += 1
    # 一整圈 = **从初始位出发**的那一段: 取"第一个在 home、且其后确实跑过 >2m"的帧作为起点。
    # (日志开始时机械臂可能还停在工位上, 那几十秒不该算进这一圈 —— 否则页面开头会冒出
    #  "等待检测/扫码/插入"这些高位段的假状态。)
    i_start = None
    for t in range(len(P)):
        if math.dist(P[t], home) <= 25.0:
            if max(math.dist(P[u], home) for u in range(t, len(P))) > 2000.0:
                i_start = t
                break
    if i_start is None:
        i_start = max(0, far[0] - 1)
    i_end = far[-1]
    while i_end + 1 < len(P) and math.dist(P[i_end + 1], home) <= 25.0:
        i_end += 1
    print("取帧 %d~%d(第一次离开 home → 最后一次回 home)" % (i_start, i_end))
    i_end_unused = 0
    while i_end + 1 < len(P) and math.dist(P[i_end + 1], home) <= 25.0:
        i_end += 1
    # (旧的向前回溯逻辑已由上面的"最后一个完整一圈"取代)

    seg = rows[i_start:i_end + 1]
    # 按"位移/角度变化"抽稀(比按时间更稳): 每帧至少移动 1.0mm 或转 0.35° 才留
    out, last = [], None
    for r in seg:
        if last is None:
            out.append({"q": r["j"], "p": r["p"], "rpy": r["rpy"]}); last = r; continue
        dp = math.dist(r["p"], last["p"])
        dq = max(abs(a - b) for a, b in zip(r["j"], last["j"])) * 57.2958
        if dp >= 1.0 or dq >= 0.35:
            out.append({"q": r["j"], "p": r["p"], "rpy": r["rpy"]}); last = r
    dst = os.path.join(ROOT, "zmax_data/rokae_sdk/real_traj_absj.json")
    ln = sum(math.dist(seg[i]["p"], seg[i + 1]["p"]) for i in range(len(seg) - 1))
    json.dump({"src": src, "n": len(out), "len_mm": round(ln, 1), "frames": out}, open(dst, "w"))
    print("关节回放轨迹: %d 帧 · 路径 %.0fmm · %.1fs → %s"
          % (len(out), ln, seg[-1]["ts"] - seg[0]["ts"], dst))
    print("起  p=%s  q=%s" % (seg[0]["p"], [round(v, 3) for v in seg[0]["j"]]))
    print("末  p=%s  q=%s" % (seg[-1]["p"], [round(v, 3) for v in seg[-1]["j"]]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
