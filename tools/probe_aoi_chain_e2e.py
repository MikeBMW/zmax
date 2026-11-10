#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_aoi_chain_e2e.py — 质量检测链路端到端实测: ssaoi → sssensor.in4 / sssched.in5

证明三件事 (缺一件就是没接上):
  A) ssaoi 真出业务 dict (verdict/pass/缺陷数/帧龄)
  B) sssensor 真读 in4, 输出里带 aoi 质量观测 (不是 None)
  C) safety_limit(动作调制器) 真读 in5 做质量门, 且口径正确:
       取像不健康 ⇒ 不拦; 取像健康+pass=False ⇒ 拦; 取像健康+pass=True ⇒ 放行
"""
import json
import os
import sys
import time

sys.path.insert(0, "/home/ubuntu/zmax/src")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = "/home/ubuntu/zmax"

from lerobot.middleware.nodes.impl import ss_aoi as AOI          # noqa: E402
from lerobot.middleware.nodes.impl import ss_sensor as SENSOR    # noqa: E402
from lerobot.middleware.nodes.impl import safety_limit_impl as LIM  # noqa: E402

res = {}


def P(title):
    print("\n" + "=" * 68 + "\n" + title + "\n" + "=" * 68)


# ── A. ssaoi 出真结果 ────────────────────────────────────────────
P("A · 光学质量检测 (ssaoi) 真实输出")
o = AOI.node_ss_aoi({"log": lambda m: print("   ", m)})
t0 = time.time()
while o["out1"].get("verdict") == "warming" and time.time() - t0 < 40:
    time.sleep(1.0)
    o = AOI.node_ss_aoi({"log": None})
a = o["out1"]
res["A_aoi"] = {k: a.get(k) for k in ("kind", "verdict", "verdict_why", "pass",
                                      "scratch", "blob", "defect_n", "sig_n", "seq", "age_s", "stale")}
print("   %s" % json.dumps(res["A_aoi"], ensure_ascii=False))
print("   worker:", AOI.aoi_worker_stats())


# ── B. sssensor 真读 in4 ────────────────────────────────────────
P("B · 融合定位建图 (sssensor) 读 in4 外观质量门")
ctx_s = {"in4": {"value": dict(a), "age_s": a.get("age_s"), "fresh": True},
         "log": lambda m: print("   ", m)}
r = SENSOR.node_ss_s1(ctx_s)
res["B_sensor"] = {"ok": bool(r and r.get("out1")), "aoi": (r.get("out1") or {}).get("aoi")}
print("   out1.aoi = %s" % json.dumps(res["B_sensor"]["aoi"], ensure_ascii=False))
print("   out1 键数 = %s (含 obs43 %s 维)" % (
    len(r.get("out1") or {}), len((r.get("out1") or {}).get("obs43") or [])))

# 无 in4 时 (证明是"真读"而不是内部回填)
r_none = SENSOR.node_ss_s1({"log": None})
res["B_sensor_no_in4"] = (r_none.get("out1") or {}).get("aoi")
print("   不连 in4 时: %s  ← 必须显示未连(证明端口是真读的)" % json.dumps(res["B_sensor_no_in4"], ensure_ascii=False))


# ── C. 质量门口径 (三种工况) ────────────────────────────────
P("C · 动作调制器 (safety_limit) 的 in5 质量门口径")


def mk_aoi(verdict, passed, stale=False, scratch=1, blob=1):
    return {"kind": "aoi", "verdict": verdict, "pass": passed, "stale": stale,
            "age_s": 1.2, "seq": 5, "scratch": scratch, "blob": blob}


u_ff = {"u_ff": [0.5, 0.0, 0.0, 1.0]}
cases = [
    ("取像不健康(gaps_washed)+pass=False", mk_aoi("gaps_washed", False), False),
    ("取像健康+pass=False (真NG)",         mk_aoi("ok", False, scratch=8, blob=4), True),
    ("取像健康+pass=True (OK)",            mk_aoi("ok", True),  False),
    ("快照过期",                            mk_aoi("ok", False, stale=True), False),
    ("未出判决",                            mk_aoi("", None),   False),
]
rows = []
for name, pl, expect_block in cases:
    ctx = {"in6": {"value": dict(u_ff), "age_s": 0.1, "fresh": True},
           "in5": {"value": pl, "age_s": 1.0, "fresh": True},
           "log": None}
    rr = LIM.run(ctx)
    o1 = rr.get("out1") or {}
    qg = o1.get("quality_gate") or {}
    got = bool(qg.get("block"))
    ok = (got == expect_block)
    rows.append({"case": name, "kind": o1.get("kind"), "block": got,
                 "expect": expect_block, "pass_ok": ok, "why": qg.get("why"),
                 "available": qg.get("available")})
    print("   [%s] %-32s kind=%-14s block=%-5s 期望=%-5s | %s"
          % ("OK " if ok else "❌", name, o1.get("kind"), got, expect_block, qg.get("why")))
res["C_gate"] = rows
res["C_all_pass"] = all(x["pass_ok"] for x in rows)

# ④ 旧行为回归: 没有 in5 时不该被拦
r0 = LIM.run({"in6": {"value": dict(u_ff), "age_s": 0.1, "fresh": True}, "log": None})
res["C_no_in5"] = {"kind": (r0.get("out1") or {}).get("kind"),
                   "block": bool(((r0.get("out1") or {}).get("quality_gate") or {}).get("block"))}
print("   [%s] 无 in5 (旧行为)                  kind=%s block=%s"
      % ("OK " if not res["C_no_in5"]["block"] else "❌",
         res["C_no_in5"]["kind"], res["C_no_in5"]["block"]))

p = os.path.join(ROOT, "zmax_data", "ss_live", "aoi_chain_e2e.json")
json.dump(res, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
print("\n存:", os.path.relpath(p, ROOT))
print("\n总判定: A/B 见上 · C 质量门口径 %s" % ("全过" if res["C_all_pass"] and not res["C_no_in5"]["block"] else "有失败"))
