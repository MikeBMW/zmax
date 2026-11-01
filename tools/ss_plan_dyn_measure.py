#!/usr/bin/env python3
"""量一遍 plan 发布出来的真实运动学/动力学余量: 采 ar_cmd 逐拍, 反算 v/a/jerk 与闸上限对比。

跑法: ./gui-venv311/bin/python tools/ss_plan_dyn_measure.py [秒数]
输出: 每阶段 v_peak/v_cap、a_peak/a_cap、j_peak/j_cap + 超限拍数；段边界跳变。
"""
from __future__ import annotations

import json
import math
import os
import sys
import time

ROOT = os.path.expanduser("~/zmax")
CMD = os.path.join(ROOT, "zmax_data", "ss_live", "ar_cmd.json")


def main(secs=45.0, hz=100.0):
    t_end = time.time() + float(secs)
    dt_loop = 1.0 / float(hz)
    rows = []
    last_t = 0.0
    while time.time() < t_end:
        try:
            st = os.stat(CMD)
            if st.st_mtime != last_t:
                last_t = st.st_mtime
                d = json.load(open(CMD, encoding="utf-8"))
                g = d.get("gate") or {}
                a, b = d.get("a"), d.get("b")
                if isinstance(a, list) and isinstance(b, list) and len(a) == 3 == len(b):
                    L = math.dist([float(x) for x in a], [float(x) for x in b])
                    rows.append({"t": float(d["t"]), "seq": d.get("seq"), "u": float(d.get("u") or 0.0),
                                 "L": L, "kind": d.get("kind"), "label": d.get("label"),
                                 "stage": g.get("stage"), "v_cap": float(g.get("v_cap") or 0) / 1000.0,
                                 "a_cap": float(g.get("a_cap") or 0) / 1000.0,
                                 "j_cap": float(g.get("j_cap") or 0) / 1000.0,
                                 "t_seg": float(d.get("t_seg") or 0)})
        except Exception:                                                  # noqa: BLE001
            pass
        time.sleep(dt_loop)

    if len(rows) < 20:
        print("采样太少 (%d 拍), 画布 loop 没在跑?" % len(rows))
        return 1
    rows.sort(key=lambda r: r["t"])
    span = rows[-1]["t"] - rows[0]["t"]
    print("采样 %d 拍 / %.1fs ⇒ %.1f Hz (画布 loop 口径)" % (len(rows), span, len(rows) / max(span, 1e-6)))

    # 逐段: 段内 s=u·L, v=Δs/Δt, a=Δv/Δt, j=Δa/Δt
    per, jump = {}, []
    prev = None
    for r in rows:
        s = r["u"] * r["L"]
        if prev is not None and r["seq"] == prev["seq"]:
            dt = r["t"] - prev["t"]
            if dt > 1e-4:
                v = (s - prev["u"] * prev["L"]) / 1000.0 / dt          # m/s
                d = per.setdefault(r["stage"], {"n": 0, "v": 0.0, "a": 0.0, "j": 0.0,
                                                "vc": r["v_cap"], "ac": r["a_cap"], "jc": r["j_cap"],
                                                "v_over": 0, "a_over": 0, "j_over": 0})
                d["n"] += 1
                d["v"] = max(d["v"], abs(v))
                d["v_over"] += int(r["v_cap"] > 0 and abs(v) > r["v_cap"] * 1.02)
                if "vprev" in prev and prev["seq"] == r["seq"]:
                    dt2 = r["t"] - prev["t"]
                    a = (v - prev["vprev"]) / dt2
                    d["a"] = max(d["a"], abs(a))
                    d["a_over"] += int(r["a_cap"] > 0 and abs(a) > r["a_cap"] * 1.05)
                    if prev.get("aprev") is not None:
                        j = (a - prev["aprev"]) / dt2
                        d["j"] = max(d["j"], abs(j))
                        d["j_over"] += int(r["j_cap"] > 0 and abs(j) > r["j_cap"] * 1.10)
                    r["aprev"] = a
                r["vprev"] = v
        elif prev is not None:
            # 段边界: 上段末速 ≠ 0 或位置跳变 ⇒ 不连续
            jump.append({"seq": r["seq"], "kind": r["kind"],
                         "u_prev": round(prev["u"], 3), "u_new": round(r["u"], 3),
                         "dv_ms": round(float((s - prev["u"] * prev["L"]) / 1000.0), 2)})
        prev = r

    print("\n%-8s %6s %10s %10s %10s" % ("阶段", "拍数", "v峰/v上限", "a峰/a上限", "j峰/j上限"))
    print("-" * 64)
    for st, d in sorted(per.items(), key=lambda kv: -kv[1]["n"]):
        print("%-8s %6d  %6.3f/%-6.3f %8.2f/%-8.2f %9.0f/%-9.0f  超限 v%d a%d j%d"
              % (st, d["n"], d["v"], d["vc"], d["a"], d["ac"], d["j"], d["jc"],
                 d["v_over"], d["a_over"], d["j_over"]))
    print("\n段边界 %d 处; 末速未归零/位置跳 >1mm 的: %d" %
          (len(jump), sum(1 for j in jump if abs(j["dv_ms"]) > 1.0)))
    for j in jump[:5]:
        print("   seq %-3s %-6s u %.2f→%.2f 位移 %s mm" % (j["seq"], j["kind"], j["u_prev"], j["u_new"], j["dv_ms"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(*[float(x) for x in sys.argv[1:]]))
