#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""修 taught_z_ceiling 的路径 bug(改成向上找仓库根, 不再数目录层数) + 自证 + 找可测目标"""
import ast
import os
import shutil
import time

REPO = "/home/ubuntu/zmax"
SDK = os.path.join(REPO, "tools/rokae/l2_transport_sdk.py")
s = open(SDK, encoding="utf-8").read()

old = '''        _p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "data/skills/l2_atomic/space_points.json")'''
new = '''        _r = os.path.dirname(os.path.abspath(__file__))
        for _ in range(6):                       # 向上找仓库根(含 data/skills/l2_atomic), 不数目录层数
            if os.path.isdir(os.path.join(_r, "data/skills/l2_atomic")):
                break
            _r = os.path.dirname(_r)
        _p = os.path.join(_r, "data/skills/l2_atomic/space_points.json")'''
if new in s:
    print("  已是向上找根写法")
elif old in s:
    shutil.copy2(SDK, SDK + ".bak_ceilpath_" + time.strftime("%Y%m%d_%H%M%S"))
    s = s.replace(old, new, 1)
    open(SDK, "w", encoding="utf-8").write(s)
    print("  已修路径(向上找仓库根) ✓")
else:
    print("  ❌ 没找到要修的锚点")

ast.parse(open(SDK, encoding="utf-8").read())
print("  语法 ✓")

import sys  # noqa: E402
sys.path.insert(0, os.path.join(REPO, "tools/rokae"))
import l2_transport_sdk as T  # noqa: E402
import json  # noqa: E402

c = T.taught_z_ceiling()
print("  taught_z_ceiling() = %s" % (round(c, 4) if c else c))
b = T.env_box()
print("  env_box() z = %s  (夹住 = %s)" % ([round(v, 4) for v in b["z"]], b["z"][1] <= (c or 9)))
pts = json.load(open(os.path.join(REPO, "data/skills/l2_atomic/space_points.json"), encoding="utf-8"))["points"]
print("  7 点全部在天花板内: %s" % all((v.get("pos") or [0, 0, 0])[2] <= c for v in pts.values()))

# 找手动白名单里 z 高于天花板的技能(既能做零运动验证, 也是潜在风险点)
wl = os.path.join(REPO, "zmax_data/manual_skills.json")
print("\n  找「目标 z > 天花板」的可测技能:")
reg = json.load(open(os.path.join(REPO, "data/skills/l2_atomic/registry.json"), encoding="utf-8"))
sk = reg.get("skills") or reg
hi = []
for k, v in sk.items():
    v = v or {}
    p = None
    for key in ("pos", "point", "target"):
        if isinstance(v.get(key), list) and len(v[key]) == 3:
            p = v[key]
            break
    if p is None:
        for stp in (v.get("steps") or []):
            if isinstance(stp.get("pos"), list) and len(stp["pos"]) == 3:
                p = stp["pos"]
                break
    if p and float(p[2]) > c:
        hi.append((k, [round(float(x), 4) for x in p]))
for k, p in hi[:12]:
    print("    %-34s pos=%s" % (k, p))
print("  共 %d 个技能目标高于天花板 %.4f" % (len(hi), c))
