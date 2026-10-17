# -*- coding: utf-8 -*-
"""SK01~SK08 逐信号体检: 值 / 变化率 / 与 3D 插拔场景的一致性 (老倪 2026-10-17 要求逐条检查)。

输出一张表 + 退出码 (0 = 位置三轴全部与场景一致; 1 = 有不符)。
"""
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
from lerobot.middleware import pose_check as PC                      # noqa: E402

LIVE = os.path.join(ROOT, "zmax_data", "ss_live")


def load(name):
    with open(os.path.join(LIVE, name), encoding="utf-8") as f:
        return json.load(f)


def snap():
    return load("skill_phys.json"), load("trace_live.json")


sp1, tl1 = snap()
time.sleep(1.2)
sp2, tl2 = snap()
ref2 = PC.scene_xyz(tl2)
dt = float(sp2.get("ts") or 0) - float(sp1.get("ts") or 0) or 1.0

print("3D 场景: 阶段=%s 末端=(%.2f, %.2f, %.2f) mm  时间_s=%s"
      % (tl2.get("阶段"), ref2[0], ref2[1], ref2[2], tl2.get("时间_s")))
print("%-6s %-6s %-4s | %-28s | %-28s | %s"
      % ("SK", "阶段", "在职", "x/y/z (mm) 值 → 与场景Δ", "变化率 (mm/s)", "a/b/c"))
print("-" * 118)
bad = 0
for code in sorted((sp2.get("skills") or {})):
    if not str(code).startswith("SK"):
        continue
    r2 = sp2["skills"][code]
    r1 = (sp1.get("skills") or {}).get(code) or {}
    if not isinstance(r2, dict):
        continue
    vals, rates = [], []
    for ax, rf in zip(("x", "y", "z"), ref2):
        v = r2.get(ax)
        v0 = r1.get(ax)
        if not isinstance(v, (int, float)) or v == -1.0:
            vals.append("%s=无值" % ax)
            rates.append("—")
            bad += 1
            continue
        d = float(v) - rf
        flag = "" if abs(d) <= 5.0 else ("!" if abs(d) > 10 else "?")
        vals.append("%s=%8.2f Δ%+6.2f%s" % (ax, v, d, flag))
        if isinstance(v0, (int, float)) and v0 != -1.0:
            rates.append("%+7.2f" % ((float(v) - float(v0)) / dt))
        else:
            rates.append("   —   ")
    att = "/".join("%.1f" % r2.get(k, -1.0) for k in ("a", "b", "c"))
    print("%-6s %-6s %-4s | %-28s | %-28s | %s"
          % (code, str(r2.get("stage"))[:6], r2.get("在职"),
             " ".join(vals), "  ".join(rates), att))

print("\n一致性判据 (pose_check, tol=5mm):")
_al = PC.check(tl2, sp2, tol_mm=5.0)
if not _al:
    print("  ✅ 无报警")
for lv, ob, msg in _al:
    print("  [%s] %s: %s" % (lv, ob, msg))
_fail = [a for a in _al if a[0] == "fail"]
print("\n结论: %s (fail %d / warn %d)"
      % ("✅ 位置三轴与 3D 场景一致" if not _fail else "❌ 有不一致", len(_fail),
         len([a for a in _al if a[0] == "warn"])))
sys.exit(1 if _fail else 0)
