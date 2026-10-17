# -*- coding: utf-8 -*-
"""判据: Trace/信号分析的每一行都必须落回状态空间工程 —— 层 L2~L5, Tx/Rx 是工程节点, 名字严格相同。

老倪 2026-10-17: 「再次检查，搞数据同步，所有的 Topic, 都在 L2~L5层定义，Tx Rx节点都是 L2~L5层的
node 节点，与状态空间的工程，都是同一个数据源，保证 node 的严格相同」

检查项 (离屏, 不碰在跑的控制台):
  ① 工程库节点名严格一一对应 (75 节点 → 75 个唯一显示名, naming.unique_map 是单射)
  ② attribution 用的节点表 == 工程库 + naming 的同一份 (不是另抄一份)
  ③ Trace 每行 Layer ∈ L2~L5 (SYS 行不会进表)
  ④ 每行 topic: 工程库 mw_topic 里定义, 或是本机真值流话题且归属节点在 L2~L5
  ⑤ 每行 Tx 全部是工程节点显示名 (不允许 "—"/进程名)
  ⑥ 每行 Rx 是工程节点显示名或 "—" (没有真连线就不许编)
"""
import os
import re
import sqlite3
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "tools", "gui"), os.path.join(ROOT, "src"), ROOT]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("ZMAX_REPO", ROOT)

ok, bad = 0, []


def chk(name, cond, extra=""):
    global ok
    extra = str(extra)
    if cond:
        ok += 1
        print(f"✅ {name}{(' · ' + extra) if extra else ''}")
    else:
        bad.append(name)
        print(f"❌ {name}{(' · ' + extra) if extra else ''}")


from lerobot.middleware import attribution as A, db, naming                     # noqa: E402

rows = db.node_rows()
CLEAN = naming.unique_map([(r.get("node_id"), r.get("name")) for r in rows])
NAMES = [v for v in CLEAN.values() if v]
NAMESET = set(NAMES)
LAYER_OF = {CLEAN[r["node_id"]]: r["layer"] for r in rows if CLEAN.get(r["node_id"])}

# ① 单射
chk("① 工程节点名一一对应 (单射)", len(NAMESET) == len(rows) == 75, f"{len(NAMESET)} 名 / {len(rows)} 节点")

# ② 同一数据源
chk("② attribution 节点表 == 工程库+命名真源", dict(A._load_nodes()) == {k: CLEAN[k] for k in CLEAN if CLEAN.get(k)},
    f"attribution {len(A._load_nodes())} 项")

# ③~⑥ Trace 逐行
DB = os.path.join(ROOT, "data", "database", "zmax", "zmax_engineering.db")
_c = sqlite3.connect(DB)
DB_TOPICS = {r[0] for r in _c.execute("SELECT DISTINCT topic FROM mw_topic")}
_c.close()
TAP = {tp: A.PREFIX_OWNER.get(pre) for tp, pre in A.LIVE_PREFIX.items()}

import dds_canoe                                                              # noqa: E402
from PyQt5.QtWidgets import QApplication                                      # noqa: E402

app = QApplication.instance() or QApplication([])
v = dds_canoe.build_view(standalone=True)
t0 = time.time()
while time.time() - t0 < 3.0:
    app.processEvents()
    time.sleep(0.05)
v._fill_trace_fixed(force=True)
app.processEvents()

LAYERS = {"L2", "L3", "L4", "L5"}
bad_layer, bad_topic, bad_tx, bad_rx = [], [], [], []
n_rx_node = n_rx_dash = 0
for r in range(v.tb.rowCount()):
    tip = (v.tb.item(r, 2).toolTip() or "") if v.tb.item(r, 2) else ""
    tp = ""
    for ln in tip.split("\n"):
        if ln.startswith("话题:"):
            tp = ln.split(":", 1)[1].strip()
    lay = (v.tb.item(r, 1).text() if v.tb.item(r, 1) else "").strip()
    tx = (v.tb.item(r, 7).text() if v.tb.item(r, 7) else "").strip()
    rx = (v.tb.item(r, 8).text() if v.tb.item(r, 8) else "").strip()

    if lay not in LAYERS:
        bad_layer.append((tp, lay))
    _owner = TAP.get(tp)
    _pre = A.LIVE_PREFIX.get(tp)
    if tp in DB_TOPICS:
        pass                                            # 工程库 mw_topic 里定义 ✓
    elif _pre in ("skill", "skillphys"):
        # 技能话题没有单一属主: 每行按阶段落到 8 个 SK 节点 (Tx 已在 ⑤ 逐行校验是工程节点)
        if not all(p.strip() in NAMESET for p in tx.split(" / ") if p.strip()):
            bad_topic.append((tp, "SK 阶段"))
    elif _owner and LAYER_OF.get(CLEAN.get(_owner, ""), "") in LAYERS:
        pass                                            # 真值流话题 → 归属节点在 L2~L5 ✓
    else:
        bad_topic.append((tp, _owner))
    _tx = [p.strip() for p in tx.split(" / ") if p.strip()]
    if not _tx or any(p == "—" or p not in NAMESET for p in _tx):
        bad_tx.append((tp, tx))
    _rx = [p.strip() for p in rx.split(" / ") if p.strip()]
    for p in _rx:
        if p == "—":
            n_rx_dash += 1
        elif p in NAMESET:
            n_rx_node += 1
        else:
            bad_rx.append((tp, p))

chk("③ Layer 全在 L2~L5", not bad_layer, f"{len(bad_layer)} 违规 {bad_layer[:3]}")
chk("④ Topic 都在工程里定义 (mw_topic 或真值流归属节点 L2~L5)", not bad_topic,
    f"{len(bad_topic)} 违规 {bad_topic[:3]}")
chk("⑤ Tx 全是工程节点名", not bad_tx, f"{len(bad_tx)} 违规 {bad_tx[:3]}")
chk("⑥ Rx 是工程节点名或 —", not bad_rx,
    f"{len(bad_rx)} 违规 {bad_rx[:3]} · 节点 {n_rx_node} / — {n_rx_dash}")

print()
print(f"Trace 行 {v.tb.rowCount()} · 话题 {len({(v.tb.item(r,2).toolTip() or '').split('话题: ')[-1].split(chr(10))[0] for r in range(v.tb.rowCount())})}")
if bad:
    print(f"❌ 失败: {bad}")
    sys.exit(1)
print(f"✅ 全部通过 ({ok} 项)")
