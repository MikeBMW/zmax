#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""①把 MoveJ 自愈改成"默认关、按需开"(env ZMAX_MOVEJ_RETRY=1) ②语法自检 ③重启执行器 ④核验"""
import os
import re
import shutil
import subprocess
import sys
import time

REPO = "/home/ubuntu/zmax"
F = os.path.join(REPO, "tools/rokae/l2_transport_sdk.py")
s = open(F, encoding="utf-8").read()

n_hits = len(re.findall(r'"allow_movej_retry":\s*True', s))
print("  现状: 硬编码 allow_movej_retry:True 出现 %d 处" % n_hits)

if n_hits:
    shutil.copy2(F, F + ".bak_retrygate_" + time.strftime("%Y%m%d_%H%M%S"))
    s = s.replace('"allow_movej_retry": True', '"allow_movej_retry": MOVEJ_RETRY')
    # 在文件中插入模块级开关(放在 import 之后第一处空行前)
    if "MOVEJ_RETRY" not in s.split("def ")[0]:
        anchor = "import os"
        i = s.find(anchor)
        assert i > 0, "找不到 import os 锚点"
        j = s.find("\n", i)
        gate = (
            "\n\n# ⛔ MoveJ 自愈闸门 (2026-10-08 事故 INCIDENT-20261008-gsmap-space7-movej-rise-estop.md):\n"
            "#    MoveL 被 50102 拒后改用 MoveJ = **换运动学**: 关节空间插值, 末端路径不再受目标 Δz 约束,\n"
            "#    实测在 go space7 时途中意外升高/摆动, 现场只能按急停 ⇒ 默认**关**。\n"
            "#    只在\"下降/纯平移被拒\"这类目标 z ≤ 当前 z + 30mm 的场景, 才用 env ZMAX_MOVEJ_RETRY=1 显式打开;\n"
            "#    升高类动作永远不许开这个闸。\n"
            'MOVEJ_RETRY = os.environ.get("ZMAX_MOVEJ_RETRY", "0").strip() in ("1", "true", "True", "yes")'
        )
        s = s[:j] + gate + s[j:]
    open(F, "w", encoding="utf-8").write(s)
    print("  已改: 两处 True → MOVEJ_RETRY(默认 False) + 闸门注释 ✓")
else:
    print("  已经是 MOVEJ_RETRY 形态, 跳过")

import ast  # noqa: E402
ast.parse(open(F, encoding="utf-8").read())
print("  语法 ✓")

# 回读确认
s2 = open(F, encoding="utf-8").read()
print("  回读: MOVEJ_RETRY 定义 %d 处 · 引用 %d 处 · 残留 True %d 处"
      % (s2.count("MOVEJ_RETRY ="), len(re.findall(r'"allow_movej_retry":\s*MOVEJ_RETRY', s2)),
         len(re.findall(r'"allow_movej_retry":\s*True', s2))))
print("  默认值(不带 env): %s" % ("False ⛔自愈关" if '"0"' in s2 else "?"))
