#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""① 注册器里阶段3 的 dz_down_limit_mm 40 → 260(容纳"从天花板高度落到最低点"≈234mm 的纯竖直下落;
   真正的下限保护是 z_floor_point=该点z, 这才是"不许下压") ②重新注册 ③逐技能 dry 全阶段核验"""
import ast
import json
import os
import re
import subprocess
import sys
import urllib.request

REPO = "/home/ubuntu/zmax"
F = os.path.join(REPO, "tools/register_space_skills.py")

# ① 只改阶段3 那一处守卫(阶段3 的 note 里带"竖直下落到位")
s = open(F, encoding="utf-8").read()
old = '''        "stage": 3, "to": pname, "dz_mm": 0.0,
        "note": "阶段3 竖直下落到位(到位即停, 禁下压) —— 纯竖直段",
        "guard": {"dz_down_limit_mm": 40},'''
new = '''        "stage": 3, "to": pname, "dz_mm": 0.0,
        "note": "阶段3 竖直下落到位(到位即停, 禁下压) —— 纯竖直段; 下降量上限放到 260mm 是"
                "因为横移高度取『该点z+40』而臂可能本就在更高处 ⇒ 纯竖直下落到该点是良性的; "
                "真正的『不许下压』由 z_floor_point(该点 z) 保证",
        "guard": {"dz_down_limit_mm": 260},'''
if old in s:
    s = s.replace(old, new, 1)
    ast.parse(s)
    open(F, "w", encoding="utf-8").write(s)
    print("  ① 阶段3 下降守卫 40 → 260 ✓")
elif '"dz_down_limit_mm": 260' in s:
    print("  ① 已是 260, 跳过")
else:
    print("  ❌ 找不到阶段3 守卫锚点, 停手")
    sys.exit(1)

# ② 重新注册
print("  ② ", subprocess.run(["python3", os.path.join(REPO, "tools/register_space_skills.py")],
                            cwd=REPO, capture_output=True, text=True).stdout.strip().splitlines()[-2:])

# ③ 逐技能 dry, 把**所有阶段**的目标 z 都抓出来核
sys.path.insert(0, os.path.join(REPO, "tools/rokae"))
import l2_transport_sdk as T  # noqa: E402

CEIL = T.taught_z_ceiling()
print("  ③ 天花板 %.4f · 臂 %s\n" % (CEIL, [round(v, 4) for v in T.read_pose()["pos"]]))


def post(path, body, t=90):
    req = urllib.request.Request("http://127.0.0.1:8793" + path, method="POST",
                                data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=t) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


bad = 0
for n in range(1, 8):
    sk = "L2.goto_space%d" % n
    r = post("/ctl/move", {"action": "move", "dry": True, "arm": 0, "skill": sk, "by": "静静:三段配方验证2"})
    lines = r.get("lines") or []
    txt = "\n".join(lines)
    stages = [l for l in lines if re.search(r"阶段 \d+/\d+", str(l)) and ("点=" in str(l) or "Δ=" in str(l))]
    zs, kinds = [], []
    for l in lines:
        l = str(l)
        m = re.search(r"点=(\S+)\s+pos=\(([-\d.]+), ([-\d.]+), ([\d.]+)\)", l)
        if m:
            zs.append(float(m.group(4)))
        m2 = re.search(r"Δ=\(([-+\d.]+), ([-+\d.]+), ([-+\d.]+)\)mm\s*([↑↓→]?)", l)
        if m2:
            dx, dy, dz = (float(m2.group(i)) for i in (1, 2, 3))
            kinds.append("竖直" if (abs(dx) < 1 and abs(dy) < 1) else ("水平" if abs(dz) < 1 else "斜线"))
    refused = [str(l)[:130] for l in lines if ("拒发" in str(l) or "拒绝" in str(l))]
    over = [z for z in zs if z > CEIL + 1e-6]
    ok = (not refused) and (not over) and zs
    bad += 0 if ok else 1
    print("  %-16s %s 各阶段目标z=%s 类型=%s%s%s"
          % (sk, "✅" if ok else "❌", [round(z, 4) for z in zs], kinds,
             (" ⚠️超天花板" + str(over)) if over else "",
             (" ⚠️" + refused[0]) if refused else ""))

print("\n  %s" % ("✅ 7 个技能全部合规: 各阶段目标都在天花板内、无拒发" if bad == 0 else "❌ %d 个不合规" % bad))
print("  臂位姿(应没变) = %s" % [round(v, 4) for v in T.read_pose()["pos"]])
