#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""稳健改写注册器: 用【行号+括号配平】定位 steps 块整块替换, 不靠精确空白匹配。
   背景: 上一版脚本 assert 没过(空白不符) 却没拦住后面的注册器执行 ⇒ 把配方打回了旧四段(speed_max 200)。
   本脚本 ① 打印实际块(确认) ② 整块替换 ③ 常量/speed_max/措辞 ④ ast 自检 ⑤ 回读。"""
import ast
import os

REPO = "/home/ubuntu/zmax"
F = os.path.join(REPO, "tools/register_space_skills.py")
lines = open(F, encoding="utf-8").read().split("\n")

# ── 定位 steps 块(从 '            "steps": [' 到与之配平的 '          ],') ──
i0 = next((i for i, l in enumerate(lines) if l.strip().startswith('"steps": [')), None)
assert i0 is not None, "找不到 steps"
depth = 0
i1 = None
for i in range(i0, len(lines)):
    depth += lines[i].count("[") - lines[i].count("]")
    if depth == 0 and i > i0:
        i1 = i
        break
assert i1 is not None, "steps 块括号不配平"
ind = lines[i0][:len(lines[i0]) - len(lines[i0].lstrip())]
print("  steps 块: 行 %d~%d (缩进 %d 空格)" % (i0 + 1, i1 + 1, len(ind)))
print("  ── 当前块(前 4 行) ──")
for l in lines[i0:i0 + 4]:
    print("    %s" % l)

NEW = [
    ind + '"steps": [',
    ind + "    {",
    ind + '        "stage": 1, "rel": True, "dz_mm": 0.0,',
    ind + '        "adapt_point": True, "adapt_margin_mm": LIFT_MARGIN_MM,',
    ind + '        "note": "阶段1 竖直抬到「该点 z + 40mm」'
          '(自适应 max(当前z, 该点z+40) ⇒ 既不盲抬也不低于目标) —— 纯竖直段",',
    ind + '        "guard": {"dz_down_limit_mm": 400},',
    ind + '        "tol_mm": 1.0, "timeout_s": 120, "dwell_s": 1.5,',
    ind + "    },",
    ind + "    {",
    ind + '        "stage": 2, "to": pname, "dz_mm": 0.0, "keep_z": True,',
    ind + '        "note": "阶段2 保持当前高度横移到该点正上方(keep_z) —— 纯水平段'
          '(2026-10-08 老倪「改」: 斜线会被 50102 奇异点拒发, 故拆成单轴)",',
    ind + '        "guard": {"dz_down_limit_mm": 400},',
    ind + '        "tol_mm": 1.0, "timeout_s": 240, "dwell_s": 1.5,',
    ind + "    },",
    ind + "    {",
    ind + '        "stage": 3, "to": pname, "dz_mm": 0.0,',
    ind + '        "note": "阶段3 竖直下落到位(到位即停, 禁下压) —— 纯竖直段",',
    ind + '        "guard": {"dz_down_limit_mm": 40},',
    ind + '        "tol_mm": 0.5, "timeout_s": 60, "dwell_s": 1.0,',
    ind + "    },",
    ind + "],",
]
lines[i0:i1 + 1] = NEW
s = "\n".join(lines)

# ── 常量 / speed_max / 措辞 ──
s = s.replace("ADAPT_MARGIN_MM = 2.0",
              "LIFT_MARGIN_MM = 40.0   # 2026-10-08 老倪「改」: 横移高度 = 目标点 z + 40mm\n"
              "                        # (最高点 space2 0.3385 ⇒ 0.3785, 仍在安全区天花板 0.3885 之下)", 1)
s = s.replace('"speed_max": 200,', '"speed_max": 1000,', 1)
s = s.replace("四段安全轨迹", "三段单轴安全轨迹")
s = s.replace("①就地抬升(自适应到不低于该点高度) ②高位横移(z 保持, keep_z) ③降 30mm ④落到位",
              "①竖直抬到(该点 z+40mm) ②保持高度横移(keep_z) ③竖直落到位")
s = s.replace("阶段4 到位即停、禁下压", "阶段3 到位即停、禁下压")
ast.parse(s)
open(F, "w", encoding="utf-8").write(s)
print("\n  已改写 ✓ (行数 %d → %d)" % (len(lines), s.count(chr(10)) + 1))

s2 = open(F, encoding="utf-8").read()
print("  回读: stage4 残留=%d · LIFT_MARGIN_MM=%d · speed_max1000=%d · ADAPT_MARGIN 残留=%d"
      % (s2.count('"stage": 4'), s2.count("LIFT_MARGIN_MM"), s2.count('"speed_max": 1000'), s2.count("ADAPT_MARGIN_MM")))
