#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""零运动证明「安全区天花板」闸真的会拦: 把天花板临时压到 0.20m, 再 dry 发一个 z=0.3385 的真技能。
   走执行器真代码路径(dispatch), 但 dry ⇒ 绝不下发。测完打印判定。"""
import importlib.util
import json
import os
import sys

REPO = "/home/ubuntu/zmax"
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, os.path.join(REPO, "tools/rokae"))
import l2_transport_sdk as TS  # noqa: E402

print("  真实天花板(不改): %.4f" % TS.taught_z_ceiling())

# 加载执行器模块(与线上同一份文件; 模块有 __main__ 保护, import 不会起第二个实例)
spec = importlib.util.spec_from_file_location("l2d_probe", os.path.join(REPO, "tools/l2_daemon.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

# 把天花板临时压低(只在本进程内存里), 让一个**真实存在**的点被拦
TS.taught_z_ceiling = lambda: 0.20
print("  本进程内天花板临时压到 0.20m (真值不动)")
print("  目标: L2.goto_space2 (z=0.3385 > 0.20) ⇒ 执行器应当『🧱 拒发』而不是『已下发』\n")

reg = json.load(open(os.path.join(REPO, "data/skills/l2_atomic/registry.json"), encoding="utf-8"))
lines = []


def logf(msg):
    lines.append(str(msg))
    print("      %s" % str(msg)[:190])


try:
    r = m.dispatch(reg, {"skill": "L2.goto_space2", "speed": 8, "dry": True}, None, logf=logf)
except TypeError:
    r = m.dispatch(reg, {"skill": "L2.goto_space2", "speed": 8, "dry": True}, None)
    print("      (dispatch 签名不同, 已按三参调用; 日志见返回值)")

print("\n  ── 判定 ──")
txt = "\n".join(lines) + "\n" + json.dumps(r, ensure_ascii=False) if r is not None else "\n".join(lines)
hit = ("🧱" in txt and "拒发" in txt) or "超安全区天花板" in txt
bad = "已下发" in txt or "DRY-RUN(未下发)" in txt
print("  含 🧱 拒发行 = %s" % ("✅ 是" if hit else "❌ 否"))
print("  含『已下发/DRY-RUN』(说明闸没拦住) = %s" % ("⚠️ 是" if bad else "✅ 否"))
print("  结论: %s" % ("✅ 天花板闸真在拦" if (hit and not bad) else "❌ 闸没生效, 要查"))
