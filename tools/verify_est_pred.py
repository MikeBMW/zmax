# -*- coding: utf-8 -*-
"""verify_est_pred — 两个节点(自适应状态估计器 / 先验动力学预测器)的真实状态核查。

老倪 2026-11-10: 「自适应状态估计器, 先验动力学预测器, 代码都干啥了? 什么原理?」

这份脚本只做一件事: 把"文档说的"和"代码实际干的"分开摆出来, 不修饰。
  ① 两个类的源码是否在 / 多少行 / 算法公式是什么
  ② 有没有调用方 (引擎/节点/真机链)
  ③ 画布节点点了能不能跑
  ④ 右键"打开源代码"指的文件和实际执行的文件是否同一个

用法: gui-venv311/bin/python tools/verify_est_pred.py
"""
import importlib.util
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

OK, WARN, BAD = [], [], []


def line(tag, name, detail=""):
    ({"ok": OK, "warn": WARN, "bad": BAD}[tag]).append(name)
    icon = {"ok": "✅", "warn": "⚠️ ", "bad": "❌"}[tag]
    print("%s %s%s" % (icon, name, ("  " + detail) if detail else ""))


print("=" * 78)
print("① 源码是否在、多少行")
files = {
    "AdaptiveStateEstimator": os.path.join(ROOT, "src/lerobot/policies/left_right/state_space/parallel.py"),
    "PriorDynamicsPredictor": os.path.join(ROOT, "src/lerobot/policies/left_right/state_space/dynamics.py"),
}
for cls, f in files.items():
    if not os.path.exists(f):
        line("bad", "%s 源文件不存在" % cls, f)
        continue
    src = open(f, encoding="utf-8").read()
    has = ("class %s" % cls) in src
    n = src.count("\n") + 1
    line("ok" if has else "bad", "%s 在 %s" % (cls, os.path.basename(f)), "%d 行" % n)

print()
print("② 算法公式 (从源码抄, 不是推测)")
par = open(files["AdaptiveStateEstimator"], encoding="utf-8").read()
dyn = open(files["PriorDynamicsPredictor"], encoding="utf-8").read()
print("   AdaptiveStateEstimator:")
for pat in (r"return self\.A \* latent \+ self\.B \* action",
            r"return latent_pred \+ self\.K \* \(z_k - latent_pred\)"):
    m = re.search(pat, par)
    print("     %s  %s" % ("✓" if m else "✗", m.group(0) if m else pat))
print("   PriorDynamicsPredictor:")
for pat in (r"return self\.A \* np\.asarray\(latent, dtype=float\) \+ self\.B \* np\.asarray\(action, dtype=float\)",
            r"nxt, contact = self\.wm\("):
    m = re.search(pat, dyn)
    print("     %s  %s" % ("✓" if m else "✗", (m.group(0)[:70] if m else pat)))

# 有没有协方差 (真卡尔曼 vs 固定增益)
has_cov = bool(re.search(r"covarian|协方差|np\.cov|filterpy", par))
line("warn" if not has_cov else "ok", "是否有协方差传播 (真卡尔曼的标志)",
     "无 ⇒ 是固定增益指数平滑, 不是卡尔曼" if not has_cov else "有")

print()
print("③ 调用方 (谁真的 new 了这两个类)")
for cls in ("AdaptiveStateEstimator", "PriorDynamicsPredictor"):
    hits = []
    for base, _, fs in os.walk(os.path.join(ROOT, "src")):
        if "verification" in base:
            continue
        for fn in fs:
            if not fn.endswith(".py"):
                continue
            p = os.path.join(base, fn)
            try:
                t = open(p, encoding="utf-8").read()
            except Exception:  # noqa: BLE001
                continue
            if re.search(r"%s\(" % cls, t):
                hits.append(os.path.relpath(p, ROOT))
    if hits:
        line("ok", "%s 有调用方" % cls, ", ".join(hits[:3]))
    else:
        line("warn", "%s 在 src/ 下零调用方 (除 verification/)" % cls, "只有验证脚本会 new 它")

print()
print("④ 画布节点能不能跑 / 指向对不对")
flow = json.load(open(os.path.join(ROOT, "flows/state_space_obs.json"), encoding="utf-8"))
nodes = {n["id"]: n for n in flow["nodes"]}
for nid, expect in (("ssest", "parallel.py"), ("sspred", "dynamics.py")):
    n = nodes.get(nid)
    if not n:
        line("bad", "节点 %s 不存在" % nid)
        continue
    p = n.get("params") or {}
    src_decl = p.get("source") or "?"
    print("   %-7s %-24s 声明源码: %s" % (nid, n.get("name"), src_decl))
    if expect in str(src_decl):
        line("ok", "%s 声明指向 %s" % (nid, expect))
    else:
        line("bad", "%s 声明指向与预期不符" % nid, str(src_decl))

# ssest 的转调目标文件是否存在
tgt = os.path.join(ROOT, "src/lerobot/middleware/nodes/impl/ss_est.py")
exists = os.path.exists(tgt)
line("ok" if exists else "bad", "ss_est 节点实现文件 impl/ss_est.py",
     "存在" if exists else "**不存在** ⇒ node_ss_s2 转调会 ImportError")

# sspred 实际 registry 实现
print()
imp = open(os.path.join(ROOT, "src/lerobot/middleware/nodes/impl/shared_runtime.py"),
           encoding="utf-8").read()
m = re.search(r'_reg\("ss_pred", \[([^\]]*)\][^\n]*', imp)
print("   registry ss_pred 注册别名: %s" % (m.group(1) if m else "?"))
m2 = re.search(r'_EXTERNAL_LOC\["ss_pred"\] = \([^)]*"([^"]*)"', imp)
if m2:
    print("   ss_pred 源码落点: ...%s" % m2.group(1))
line("warn", "sspred 节点名 vs 实际执行",
     "节点名=先验动力学预测器, registry key=ss_pred → 实际跑 JEPA 世界模型 (predictor_layer.py)")

print()
print("=" * 78)
print("✅ %d   ⚠️  %d   ❌ %d" % (len(OK), len(WARN), len(BAD)))
sys.exit(0 if not BAD else 1)
