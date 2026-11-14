#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧭 轨迹分状态: 把 215 点切成「抓取 → 插入 → AOI → 分拣」这类工序段。

判据只用**能取证的三样**, 不猜:
  ① 示教点邻近 (data/skills/l2_atomic/taught_points.json, 距 <40mm 就算"到这个工位")
  ② 夹爪计划 (tools/web/real_traj_grip.json: i=9 合 · i=205 开)
  ③ 运动学 (相邻点位移 = 走位; 位移≈0 = 停留做动作)

输出: zmax_data/reports/traj_phases_<ts>.csv + 终端表
"""
import json
import os
import time

import numpy as np

REPO = os.path.expanduser("~/zmax")
TAUGHT = os.path.join(REPO, "data", "skills", "l2_atomic", "taught_points.json")
TRAJ = os.path.join(REPO, "tools", "web", "real_traj_joints.json")
GRIP = os.path.join(REPO, "tools", "web", "real_traj_grip.json")
OUTDIR = os.path.join(REPO, "zmax_data", "reports")

# 示教点 → 工位分类(点名可读; 顺序即优先级)
CAT = [
    ("插入", ("insert_pose", "insert_deep", "insert_pre", "insert_mouth", "insert_corrected",
              "插入口", "插入到位", "hole_retract", "hole_up", "光模块插入点", "光模块插入口")),
    ("槽位", ("slot", "mod_slot_")),
    ("AOI检测", ("aoi_gold_view", "金手指点", "侧面点", "正向观察位")),
    ("抓取准备", ("光模块插拔准备点", "afx", "loop20_", "准备点", "准备")),
]


def cat_of(name):
    for c, keys in CAT:
        if any(k in name for k in keys):
            return c
    return "其它"


def main():
    T = json.load(open(TAUGHT, encoding="utf-8"))["points"]
    lm = [(k, np.array(v["pos"], dtype=float) * 1000.0) for k, v in T.items() if v.get("pos")]
    fr = json.load(open(TRAJ, encoding="utf-8"))["frames"]
    P = np.array([[c * 1000.0 for c in f["p"]] for f in fr])
    N = len(P)

    grip = json.load(open(GRIP, encoding="utf-8"))
    ev = sorted([(int(e["i"]), e.get("act", e.get("state", "?"))) for e in grip.get("grip", [])])

    def grip_at(i):
        st = "开"
        for gi, gs in ev:
            if i >= gi:
                st = "合" if gs in ("close", "closed", 0) else "开"
        return st

    rows = []
    for i, p in enumerate(P):
        d = np.linalg.norm(P - p, axis=1)
        prev_i = max(0, i - 1)
        step = float(np.linalg.norm(P[i] - P[prev_i])) if i > 0 else 0.0
        near = [(k, float(np.linalg.norm(p - q))) for k, q in lm]
        near = sorted([x for x in near if x[1] < 40.0], key=lambda x: x[1])
        cats = []
        for k, dd in near:
            c = cat_of(k)
            if c not in cats:
                cats.append(c)
        rows.append({"i": i, "p": p, "step": step, "near": near, "cats": cats,
                     "grip": grip_at(i)})

    # ── 分段: 类别序列变化处切; 纯走位(无邻近点)且 step 大体为"移动"
    phases = []
    for r in rows:
        key = tuple(r["cats"][:1]) if r["cats"] else ("走位",)
        if not phases or phases[-1]["key"] != key:
            phases.append({"key": key, "i0": r["i"], "i1": r["i"], "grip": r["grip"]})
        else:
            phases[-1]["i1"] = r["i"]
    # 合并 <=2 点的碎段到前一段(噪声)
    merged = []
    for ph in phases:
        if merged and (ph["i1"] - ph["i0"] + 1) <= 2:
            merged[-1]["i1"] = ph["i1"]
        else:
            merged.append(ph)
    phases = merged

    def name_of(ph):
        k = ph["key"][0] if ph["key"] else "走位"
        i0, i1 = ph["i0"], ph["i1"]
        seg = rows[i0:i1 + 1]
        speed = np.mean([r["step"] for r in seg])
        g = ph["grip"]
        if k == "走位":
            return "走位/过渡"
        if k == "插入":
            return "插入" if speed > 3 else "插入·压入保持"
        if k == "槽位":
            return "放回/取件(槽位)" if speed > 3 else "槽位定位/停留"
        if k == "AOI检测":
            return "AOI检测(观察位)" if speed > 3 else "AOI检测·停住判图"
        if k == "抓取准备":
            return "抓取准备/对位" if g == "开" else "搬运(已夹住)"
        return k

    print("=" * 84)
    print("215 点工序分段  (判据: 示教点邻近<40mm + 夹爪计划 + 相邻位移)")
    print("=" * 84)
    print(" 区间       点数   平均步长   夹爪  工序                    最近示教点")
    print("-" * 84)
    out_rows = []
    for ph in phases:
        seg = rows[ph["i0"]:ph["i1"] + 1]
        speed = float(np.mean([r["step"] for r in seg]))
        nm = name_of(ph)
        ann = ",".join("%s(%.0f)" % (k, d) for k, d in seg[len(seg) // 2]["near"][:3]) or "-"
        print("%3d~%-3d   %3d   %6.1fmm   %-3s  %-22s %s"
              % (ph["i0"], ph["i1"], len(seg), speed, ph["grip"], nm, ann[:34]))
        out_rows.append({"i0": ph["i0"], "i1": ph["i1"], "n": len(seg),
                         "phase": nm, "cat": ph["key"][0] if ph["key"] else "走位",
                         "mean_step_mm": round(speed, 1), "grip": ph["grip"],
                         "landmarks": [[k, round(d, 1)] for k, d in seg[len(seg) // 2]["near"][:3]]})

    # 关键事件
    print("-" * 84)
    print("关键事件:")
    for gi, gs in ev:
        p = P[gi]
        near = sorted([(k, float(np.linalg.norm(p - q))) for k, q in lm], key=lambda x: x[1])[:2]
        print("  i=%-3d 夹爪 %-5s @ (%.0f,%.0f,%.0f)mm  最近: %s"
              % (gi, "合上" if gs in ("close", "closed", 0) else "打开", p[0], p[1], p[2],
                 ", ".join("%s %.0fmm" % x for x in near)))
    # 停留最久的 6 段(动作发生的证据)
    print("-" * 84)
    print("停留最久的段(位移<2mm, 连续):")
    runs, cur = [], None
    for r in rows:
        if r["step"] < 2.0:
            cur = [r["i"], r["i"]] if cur is None else [cur[0], r["i"]]
        else:
            if cur and cur[1] - cur[0] >= 2:
                runs.append(cur)
            cur = None
    if cur and cur[1] - cur[0] >= 2:
        runs.append(cur)
    for a, b in sorted(runs, key=lambda x: -(x[1] - x[0]))[:6]:
        mid = (a + b) // 2
        ann = ",".join("%s(%.0f)" % (k, d) for k, d in rows[mid]["near"][:2]) or "-"
        print("  i=%3d~%-3d (%2d 点静)  %s" % (a, b, b - a + 1, ann[:44]))

    # ── 工序层(把细段按工位+夹爪+高度归并成可读工序)
    print("-" * 84)
    print("工序层(按 工位类别 + 夹爪 + TCP 高度 归并):")
    ops = []
    for ph in phases:
        seg = rows[ph["i0"]:ph["i1"] + 1]
        zmax = max(r["p"][2] for r in seg)
        zmin = min(r["p"][2] for r in seg)
        cat = ph["key"][0] if ph["key"] else "走位"
        if cat == "插入":
            op = "插入"
        elif cat == "槽位":
            op = "槽位取放(分拣)"
        elif cat == "AOI检测":
            op = "AOI 检测"
        elif cat == "抓取准备":
            op = "抓取/准备"
        else:
            op = "抬升转移(高位)" if zmin > 600 else "走位"
        if ops and ops[-1]["op"] == op:
            ops[-1]["i1"] = ph["i1"]
            ops[-1]["z"] = max(ops[-1]["z"], zmax)
        else:
            ops.append({"op": op, "i0": ph["i0"], "i1": ph["i1"], "z": zmax, "grip": ph["grip"]})
    print(" 区间       工序                 最高 Z     夹爪")
    for o in ops:
        print("%3d~%-3d   %-18s  %5.0fmm   %s" % (o["i0"], o["i1"], o["op"], o["z"], o["grip"]))

    os.makedirs(OUTDIR, exist_ok=True)
    out = os.path.join(OUTDIR, "traj_phases_%s.csv" % time.strftime("%Y%m%d_%H%M%S"))
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("i0,i1,n,phase,cat,mean_step_mm,grip,landmarks\n")
        for r in out_rows:
            fh.write("%d,%d,%d,%s,%s,%.1f,%s,\"%s\"\n" % (
                r["i0"], r["i1"], r["n"], r["phase"], r["cat"], r["mean_step_mm"],
                r["grip"], "; ".join("%s %.0fmm" % (k, d) for k, d in r["landmarks"])))
    print("-" * 84)
    print("分段 %d 段 · CSV: %s" % (len(out_rows), out))
    print("=" * 84)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
