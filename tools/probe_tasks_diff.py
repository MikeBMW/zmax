#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""查 tasks 段 diff 误报: 存档内容 vs 现场逐键比"""
import json
import os
import sys

sys.path.insert(0, "/home/ubuntu/zmax/tools")
sys.path.insert(0, "/home/ubuntu/zmax/tools/gui")
import project_file as PF  # noqa

proj = PF._read("/tmp/zmax_arch_verify/zmax_space.proj")
arch = proj.get("tasks", {}).get("content", {})
live = json.load(open("/home/ubuntu/zmax/config/ss_task_binding.json", encoding="utf-8"))
print("存档 keys:", sorted(arch)[:20])
print("现场 keys:", sorted(live)[:20])
diff = []
for k in sorted(set(arch) | set(live)):
    a, b = arch.get(k, "<缺>"), live.get(k, "<缺>")
    if a != b:
        diff.append(k)
        print("  ✗ %-22s 存档=%s  现场=%s" % (k, str(a)[:120], str(b)[:120]))
if not diff:
    print("  逐键完全相同 (浮点/嵌套也一致)")
else:
    print("  差异键: %s" % diff)
# diff 实现
import inspect
print("\n--- cmd_diff tasks 分支源码 ---")
src = inspect.getsource(PF.diff_project) if hasattr(PF, "diff_project") else ""
for line in src.splitlines():
    if "task" in line.lower():
        print("   " + line)
