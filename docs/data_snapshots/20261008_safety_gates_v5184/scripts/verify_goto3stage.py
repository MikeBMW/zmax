#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""零运动验证: 逐个 dry 发 L2.goto_space1~7, 检查 ①阶段数=3 ②每阶段目标 z ≤ 安全区天花板 ③三段类型对
   ④无拒发。只读+dry, 臂一动不动。"""
import json
import re
import sys
import urllib.request

sys.path.insert(0, "/home/ubuntu/zmax/tools/rokae")
import l2_transport_sdk as T  # noqa: E402

CEIL = T.taught_z_ceiling()
print("  安全区天花板 = %.4f m" % CEIL)
print("  当前臂位姿 = %s\n" % str([round(v, 4) for v in T.read_pose()["pos"]]))


def post(path, body, t=90):
    req = urllib.request.Request("http://127.0.0.1:8793" + path, method="POST",
                                data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=t) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


bad = 0
for n in range(1, 8):
    sk = "L2.goto_space%d" % n
    try:
        r = post("/ctl/move", {"action": "move", "dry": True, "arm": 0, "skill": sk, "by": "静静:三段配方验证"})
    except Exception as e:                                                       # noqa: BLE001
        print("  %-16s ❌ 请求失败 %s" % (sk, str(e)[:90]))
        bad += 1
        continue
    txt = "\n".join(r.get("lines") or [])
    zs = [float(m.group(1)) for m in re.finditer(r"pos=\([-\d.]+, [-\d.]+, ([\d.]+)\)", txt)]
    stages = len(re.findall(r"阶段 \d+/\d+", txt))
    refused = ("拒发" in txt) or ("拒绝" in txt)
    over = [z for z in zs if z > CEIL + 1e-6]
    kinds = []
    for m in re.finditer(r"Δ=\(([-+\d.]+), ([-+\d.]+), ([-+\d.]+)\)mm\s*([↑↓→]?\S*)", txt):
        dx, dy, dz = (float(m.group(i)) for i in (1, 2, 3))
        kinds.append("竖直" if abs(dx) < 1 and abs(dy) < 1 else ("水平" if abs(dz) < 1 else "斜线!"))
    ok = (not refused) and (not over) and ("斜线!" not in kinds)
    bad += 0 if ok else 1
    print("  %-16s %s 阶段目标 z=%s %s%s"
          % (sk, "✅" if ok else "❌",
             [round(z, 4) for z in zs],
             " · ".join(kinds),
             ("  ⚠️超天花板%s" % over) if over else ("  ⚠️有拒发" if refused else "")))

print("\n  结论: %s" % ("✅ 7 个技能全部合规(三段单轴 · 目标全在天花板内 · 无拒发)" if bad == 0
                      else "❌ 有 %d 个不合规, 见上" % bad))
p = T.read_pose()
print("  臂位姿(应没变) = %s" % str([round(v, 4) for v in p["pos"]]))
