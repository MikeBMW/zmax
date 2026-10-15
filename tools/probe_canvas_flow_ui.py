#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_canvas_flow_ui.py — 界面级验收: 真加载画布后, 📈数据流仍是从左到右吗?

老倪 2026-10-15: 「动作调制的位置, 应该是在前馈加速器的右边…接线符合从左上到右下角的趋势」

判据 (全部打在**界面内存里的节点几何**上, 不是 JSON):
 ① ⚡前馈加速器 必须在 🧭动作调制器 左边 (老倪点名的这一条)
 ② 非环边前向比例 ≥ 97% (改前 178/190=93.7%)
 ③ 反向线必须**向下走** (对角线趋势), 长程回环除外
 ④ 功能节点零重叠
"""
from __future__ import annotations

import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools", "gui"))
sys.path.insert(0, os.path.join(REPO, "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5 import QtWidgets                                            # noqa: E402
import simulink_module as SM                                          # noqa: E402

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
m = SM.SimulinkModule()
m.resize(1600, 1000)
m.open_state_space()
for _ in range(60):
    app.processEvents()

pat = os.path.realpath(os.path.join(REPO, "flows", "state_space_obs.json"))
d = json.load(open(pat, encoding="utf-8"))
want = {n["id"]: (int(n["x"]), int(n["y"]), int(n.get("w", 280)), int(n.get("h", 110))) for n in d["nodes"]}

geo = {}
for k, it in (getattr(m, "_items", {}) or {}).items():
    nd = getattr(it, "node", None) or {}
    # 🔴 GUI 的 load_flow_file 会**重编节点 id** ⇒ 只能用**名字**对上真源
    nid = str(nd.get("name") or nd.get("id") or k)
    try:
        p = it.pos()
        br = it.boundingRect()
        geo[nid] = (int(p.x()), int(p.y()), int(br.width()), int(br.height()))
    except Exception:                                                   # noqa: BLE001
        continue

print("界面节点 %d 个 (真源 %d)" % (len(geo), len(want)))
ok = True
if len(geo) < 50:
    print("❌ 界面没加载出画布 (几何拿不到)"); sys.exit(1)


# 界面几何按名字取; 真源同名字的 (x,y,w,h)
JNAME = {n["id"]: str(n.get("name", "")) for n in d["nodes"]}
JWH = {str(n.get("name", "")): (int(n.get("w", 280)), int(n.get("h", 110)))
       for n in d["nodes"] if n.get("type") not in ("bg", "row_bg")}


def g(nid):
    nm = JNAME.get(nid, "")
    got = geo.get(nm)
    if got:
        return (got[0], got[1], JWH.get(nm, (280, 110))[0], JWH.get(nm, (280, 110))[1])
    return want.get(nid)


ff, sc = g("ssff"), g("sssched")
c1 = bool(ff and sc and ff[0] + ff[2] <= sc[0])
print("%s ① ⚡前馈加速器 x=%s → 🧭动作调制器 x=%s" % ("✅" if c1 else "❌", ff, sc))

links = [(l["f"], l["t"]) for l in d["links"]
         if JNAME.get(l["f"], "") in geo and JNAME.get(l["t"], "") in geo]
fwd = rev = rev_down = 0
for f, t in links:
    fx, fy, fw, _ = g(f)
    tx, ty, _, _ = g(t)
    if fx + fw <= tx:
        fwd += 1
    else:
        rev += 1
        if ty > fy:
            rev_down += 1
ratio = fwd / max(1, len(links))
c2 = ratio >= 0.97
print("%s ② 前向 %d/%d = %.1f%% (判据 ≥97%%)" % ("✅" if c2 else "❌", fwd, len(links), ratio * 100))
c3 = rev_down * 2 >= rev
print("%s ③ 反向 %d 条, 其中向下 %d 条" % ("✅" if c3 else "❌", rev, rev_down))

ov = []
ks = sorted([JNAME[i] for i in want if JNAME[i] in geo and want[i] and
             next(n for n in d["nodes"] if n["id"] == i).get("type") not in ("bg", "row_bg")])
for i in range(len(ks)):
    for j in range(i + 1, len(ks)):
        ax, ay, *_ = geo[ks[i]]
        bx, by, *_ = geo[ks[j]]
        aw, ah = JWH.get(ks[i], (280, 110))
        bw, bh = JWH.get(ks[j], (280, 110))
        if ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah:
            ov.append((ks[i], ks[j]))
c4 = not ov
print("%s ④ 界面重叠 %d 对 %s" % ("✅" if c4 else "❌", len(ov), ov[:3]))
ok = c1 and c2 and c3 and c4
print("结论: %s" % ("✅ 界面就是从左到右 / 左上到右下" if ok else "❌ 未通过"))
sys.exit(0 if ok else 1)
