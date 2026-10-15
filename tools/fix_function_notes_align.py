#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_function_notes_align.py — 把「功能点描述真源」重新按**节点名**对齐 (fn_id 是位置号, 插节点会整体错位)。

背景 (2026-10-15 实捉):
  `data/database/zmax/function_notes.json` 按 `fn_id` (FN-<系统>-<序号>) 存描述, 而 **fn_id 是行内位置号** ——
  往某一行里插一个节点 (本轮: ⚖ 物理约束闸 → FN-SYS0-60; 📦 metaworld 数据源 → FN-PLAT-63; 🧾 元任务预测 → FN-SYS2-24)
  会把该行**后面所有节点的号往前推一位** ⇒ 每个描述被挂到了"下一个节点"上 (实测 18 条错位/空缺, 而 setter 只看得见
  "空描述" 2 条 —— **错挂的名字看不出来**)。判据里本就有「描述里的功能名与 config_meta 一致」(verify_function_notes ①),
  这条能逐条查出来。

本脚本: 按**节点名** (notes[i].name ↔ functions.name) 重新挂号:
  ① 精确同名 → 直接搬到该 fn_id;
  ② 名字被改过 (前缀 14 字相同, 如「…LoRA 微调 (r8/α16)」→「…LoRA 微调 (接在意图解码器…)」) → 视为同一节点, 顺手把 name 字段更新;
  ③ 新节点 (没任何可挂的旧描述) → 报出来, 由人工补写 (本脚本 -new 文件可一次给多条);
  ④ 旧描述成了孤儿 (节点已删) → 保留在 `notes_orphan` 里 (不丢历史), 并从 notes 挪出。
用法: python3 tools/fix_function_notes_align.py            # 干跑, 打印计划
      python3 tools/fix_function_notes_align.py --apply    # 落盘
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
NOTES_J = "data/database/zmax/function_notes.json"
DB = "data/database/zmax/zmax_engineering.db"
NEW_J = "data/database/zmax/function_notes_new.json"          # 可选: 新节点描述 ({"notes": {名: {...}}})

doc = json.load(open(NOTES_J, encoding="utf-8"))
notes = dict(doc.get("notes") or {})
con = sqlite3.connect(DB)
rows = list(con.execute("SELECT fn_id, name FROM functions ORDER BY fn_id"))
names = {fid: nm for fid, nm in rows}

pool = {}                                     # 名 → [旧 fn_id, ...]
for _id, v in notes.items():
    _n = (v or {}).get("name")
    if _n:
        pool.setdefault(_n, []).append(_id)

newdoc = json.load(open(NEW_J, encoding="utf-8")) if os.path.exists(NEW_J) else {"notes": {}}
new_by_name = {k: v for k, v in (newdoc.get("notes") or {}).items()}

plan, out, orphan = [], {}, []
for fid, nm in rows:
    if nm in pool and pool[nm]:
        old = pool[nm].pop(0)
        out[fid] = notes[old]
        if old != fid:
            plan.append("  搬号 %-12s → %-12s  %s" % (old, fid, nm[:34]))
    else:
        _hit = next((k for k in list(pool) if k and k[:14] == (nm or "")[:14] and pool[k]), None)
        if _hit:
            old = pool[_hit].pop(0)
            out[fid] = dict(notes[old]); out[fid]["name"] = nm
            plan.append("  改名 %-12s → %-12s  %s (旧名 %s)" % (old, fid, nm[:26], _hit[:26]))
        elif nm in new_by_name:
            out[fid] = new_by_name[nm]
            plan.append("  新写 %-12s  %s" % (fid, nm[:40]))
        else:
            plan.append("  ❗缺描述 %-12s  %s" % (fid, nm[:44]))
for k, ids in pool.items():
    for i in ids:
        orphan.append("%s (%s)" % (i, k[:26]))
        plan.append("  孤儿 %-12s  %s" % (i, k[:34]))

print("═══ 计划 (%d 条节点) ═══" % len(rows))
print("\n".join(plan) or "  (无需改动)")
_missing = [l for l in plan if l.strip().startswith("❗")]
print("\n需人工补写: %d 条 · 孤儿: %d 条 · 搬号/改名: %d 条"
      % (len(_missing), len(orphan), len([l for l in plan if l.strip().startswith(("搬号", "改名"))])))
if "--apply" not in sys.argv or _missing:
    print("(干跑或仍有缺口; 补齐后再 --apply)")
    sys.exit(0 if not _missing else 1)
doc["notes"] = out
doc["count"] = len(out)
if orphan:
    doc["notes_orphan"] = {k: v for k, v in list(doc.get("notes_orphan", {}).items()) +
                           [(o.split(" ")[0], notes[o.split(" ")[0]]) for o in orphan]}
shutil.copy2(NOTES_J, NOTES_J + ".bak_%s" % time.strftime("%Y%m%d_%H%M%S"))
json.dump(doc, open(NOTES_J, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("\n已写盘 %s (count=%d, 孤儿 %d 存 notes_orphan)" % (NOTES_J, doc["count"], len(orphan)))
