#!/usr/bin/env python3
"""动力学约束有效性实测: 按画布 loop 的节奏反复调 plan.run() (= 真发布路径, 含 S 曲线/L4 记忆),
采它写出的 ar_cmd 反算 v/a/jerk, 与闸给的 v_cap/a_cap/j_cap 对比。

跑法: ./gui-venv311/bin/python tools/ss_plan_dyn_selfcheck.py [秒数] [Hz]
写临时 ar_cmd, 不动现场 ar_cmd.json。
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import sys
import tempfile
import time

ROOT = os.path.expanduser("~/zmax")
PLAN = os.path.join(ROOT, "src", "lerobot", "engineering", "nodes", "plan_long_impl.py")


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main(secs=40.0, hz=10.0):
    P = load(PLAN, "plan_dyn_sc")
    tmpd = tempfile.mkdtemp(dir="/home/ubuntu/.hermes/cache/scratch")
    P._AR_CMD = os.path.join(tmpd, "ar_cmd_dyn.json")
    P._AR_PUB = True
    os.environ["ZMAX_AR_OWNER"] = "plan"
    P.run({})                                   # 建段表 + 计时起点

    ser, seen = [], 0.0
    t_end = time.time() + float(secs)
    period = 1.0 / float(hz)
    while time.time() < t_end:
        P.run({})                               # 真发布路径
        try:
            st = os.stat(P._AR_CMD)
            if st.st_mtime != seen:
                seen = st.st_mtime
                d = json.load(open(P._AR_CMD, encoding="utf-8"))
                g = d.get("gate") or {}
                ser.append({"t": d["t"], "seq": d.get("seq"), "stage": g.get("stage"),
                            "a": d["a"], "b": d["b"], "u": float(d["u"]),
                            "vc": float(g.get("v_cap") or 0) / 1000.0,
                            "ac": float(g.get("a_cap") or 0) / 1000.0,
                            "jc": float(g.get("j_cap") or 0) / 1000.0,
                            "sm": int(((d.get("mem") or {}).get("l4") or {}).get("smooth") or 0)})
        except Exception:                                                  # noqa: BLE001
            pass
        time.sleep(period)

    from collections import defaultdict
    agg = defaultdict(lambda: dict(n=0, v=0.0, a=0.0, j=0.0, vc=0.0, ac=0.0, jc=0.0,
                                  vo=0, ao=0, jo=0))
    jumps, prev = [], None
    for r in ser:
        # 全局位置 (mm): p = a + u·(b-a) —— 段边界 u 会归零, 只有全局坐标才可比
        r["p"] = [float(r["a"][k]) + (float(r["b"][k]) - float(r["a"][k])) * r["u"] for k in range(3)]
        L = math.dist([float(x) for x in r["a"]], [float(x) for x in r["b"]])
        r["s"] = r["u"] * L
        d = agg[r["stage"]]
        d["vc"], d["ac"], d["jc"] = r["vc"], r["ac"], r["jc"]
        if prev is not None:
            dt = r["t"] - prev["t"]
            gap = math.dist([float(x) for x in r["a"]], [float(x) for x in prev["b"]]) \
                if r["seq"] != prev["seq"] else 0.0
            if r["seq"] != prev["seq"]:
                jumps.append((r["seq"], round(gap, 1)))
            if dt > 1e-5 and gap <= 3.0:        # 位置跳变不算速度 (单独报)
                v = math.dist(r["p"], prev["p"]) / 1000.0 / dt   # 拍间真实位移/时间
                a = (v - prev["v"]) / dt
                j = (a - prev["a"]) / dt
                d["n"] += 1
                d["v"] = max(d["v"], abs(v))
                d["a"] = max(d["a"], abs(a))
                d["j"] = max(d["j"], abs(j))
                d["vo"] += int(r["vc"] > 0 and abs(v) > r["vc"] * 1.02)
                d["ao"] += int(r["ac"] > 0 and abs(a) > r["ac"] * 1.05)
                d["jo"] += int(r["jc"] > 0 and abs(j) > r["jc"] * 1.10)
                r["v"], r["a"] = v, a
        if "v" not in r:
            r["v"], r["a"] = 0.0, 0.0
        prev = r

    print("真发布路径 plan.run @%.0fHz: %d 拍 / %.1fs · L4 smooth=%s"
          % (hz, len(ser), (ser[-1]["t"] - ser[0]["t"]) if ser else 0, ser[0]["sm"] if ser else "?"))
    print("\n%-6s %5s %13s %14s %13s" % ("阶段", "拍", "v峰/上限", "a峰/上限", "j峰/上限"))
    print("-" * 64)
    for st, d in sorted(agg.items(), key=lambda kv: -kv[1]["n"]):
        print("%-6s %5d %6.3f/%-6.3f %7.2f/%-6.2f %7.0f/%-6.0f  超 v%-3d a%-3d j%d"
              % (st, d["n"], d["v"], d["vc"], d["a"], d["ac"], d["j"], d["jc"],
                 d["vo"], d["ao"], d["jo"]))
    print("\nv 超限 %d 拍 · a 超限 %d 拍 · j 超限 %d 拍"
          % (sum(d["vo"] for d in agg.values()), sum(d["ao"] for d in agg.values()),
             sum(d["jo"] for d in agg.values())))
    if jumps:
        big = [x for x in jumps if x[1] > 3.0]
        print("段间位置跳变: %d/%d 处 > 3mm" % (len(big), len(jumps)))
        for x in big[:6]:
            print("   → 进 seq %s 起点离上段终点 %.1fmm" % x)
    return 0


if __name__ == "__main__":
    sys.exit(main(*[float(x) for x in sys.argv[1:]]))
