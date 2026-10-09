#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_library_sync.py — 模块库 ↔ 画布 同步体检 (老倪: 所有状态空间节点都要与模块库同步; 没关联的都删掉)

打印:
 ① 模块库: 分组数 / 条目总数 / 各分组条目数
 ② 状态空间画布: 功能节点数 / 库中缺哪些 (画布有、库里没有 → 要补)
 ③ 库条目关联性: 每个条目名 在 全部 flows/*.json 里能不能找到同名节点
      - 一个都找不到 → 「无关联」(候选删除)
      - 只在别的画布找到 (非状态空间) → 「他画布关联」(删前要确认)
 ④ 画布孤立节点 (无连线, 非 row_bg)
用法: QT_QPA_PLATFORM=offscreen env -u PYTHONPATH gui-venv311/bin/python tools/probe_library_sync.py
"""
import glob
import json
import os
import sys

ROOT = "/home/ubuntu/zmax"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(ROOT, "tools/gui"))
from PyQt5.QtWidgets import QApplication                                        # noqa: E402

app = QApplication(sys.argv)
import simulink_module as SM                                                     # noqa: E402

SS = os.path.join(ROOT, "src/lerobot/engineering/flows/state_space_obs.json")
ss = json.loads(open(SS, encoding="utf-8").read())
ss_nodes = ss["nodes"]
ss_func = [n for n in ss_nodes if n.get("type") != "row_bg"]
ss_links = ss["links"]
ss_names = {n["name"] for n in ss_func}

# 全部画布的节点名 (含状态空间)
all_names = {}
for fp in glob.glob(os.path.join(ROOT, "src/lerobot/engineering/flows/*.json")) + \
          glob.glob(os.path.join(ROOT, "flows/*.json")):
    try:
        d = json.loads(open(fp, encoding="utf-8").read())
    except Exception:                                                            # noqa: BLE001
        continue
    if not isinstance(d, dict):
        continue
    for n in (d.get("nodes") or []):
        if n.get("type") == "row_bg":
            continue
        all_names.setdefault(n["name"], set()).add(os.path.basename(fp))

LIB = SM.LIBRARY
items = [(t, g, it) for t, g, its in LIB for it in its]
print("① 模块库: %d 分组 / %d 条目" % (len(LIB), len(items)), flush=True)
for t, g, its in LIB:
    print("   %-28s %-4s %d 条" % (g[:28], t, len(its)), flush=True)

lib_names = [it["name"] for _, _, it in items]
n_flow = sum(1 for _, _, it in items if it.get("flow"))
n_tpl = sum(1 for _, _, it in items if it.get("template"))
n_scene = sum(1 for _, _, it in items if (it.get("params") or {}).get("scene_id"))
n_gate = sum(1 for _, _, it in items if (it.get("params") or {}).get("atomic_gate"))
print("   形态: 加节点 %d · 载flow %d · 模板 %d · 场景 %d · 原子 %d"
      % (len(items) - n_flow - n_tpl - n_scene - n_gate, n_flow, n_tpl, n_scene, n_gate), flush=True)

# ② 画布 → 库 缺失
missing = sorted(ss_names - set(lib_names))
print("\n② 状态空间画布: %d 功能节点 · 库中缺失 %d 个" % (len(ss_func), len(missing)), flush=True)
for m in missing:
    print("   ❌ 画布有/库里没有:", m, flush=True)

# ③ 库 → 画布 关联性
no_rel, other_only, ss_rel = [], [], []
dup = {}
for nm in lib_names:
    dup[nm] = dup.get(nm, 0) + 1
for nm in sorted(set(lib_names)):
    if nm in ss_names:
        ss_rel.append(nm)
    elif nm in all_names:
        other_only.append((nm, sorted(all_names[nm])))
    else:
        no_rel.append(nm)
print("\n③ 库条目关联: 状态空间命中 %d · 仅他画布命中 %d · 无关联 %d"
      % (len(ss_rel), len(other_only), len(no_rel)), flush=True)
for nm in no_rel:
    print("   ⚠️ 无关联(候选删除):", nm, flush=True)
print("   -- 仅别画布命中 (前 25) --", flush=True)
for nm, fps in other_only[:25]:
    print("      %-34s %s" % (nm[:34], ",".join(fps[:3])), flush=True)
dups = {k: v for k, v in dup.items() if v > 1}
print("   库内重名条目: %d %s" % (len(dups), list(dups.items())[:8]), flush=True)

# ④ 画布孤立
deg = {}
for l in ss_links:
    deg[l["f"]] = deg.get(l["f"], 0) + 1
    deg[l["t"]] = deg.get(l["t"], 0) + 1
orph = [n["name"] for n in ss_func if deg.get(n["id"], 0) == 0]
print("\n④ 状态空间画布孤立功能节点: %d %s" % (len(orph), orph[:10]), flush=True)
sys.stdout.flush()
os._exit(0)
