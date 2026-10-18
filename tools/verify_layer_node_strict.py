# -*- coding: utf-8 -*-
"""判据: 数据空间(Trace)与信号分析这两个窗口 —— 只保留 L2 的 topic/信号, Tx/Rx 只能是 L2 节点。

老倪 2026-10-17: 「数据空间和信号分析这两个独立窗口…只保留 L2 层的 topic, 删除其它层的 topic,
信号也只能显示 L2 层的信号, signal 是 topic 的组成单元; Tx Rx 节点, 只能是 L2 层节点, 其它层都删掉」
另: 「Rx 怎么还有 物理约束呢？也没有这个节点啊」「前馈直方图，是可视化层，也不属于 L2~L5 层」

检查项 (离屏, 不碰在跑的控制台):
  ① 工程库节点名严格一一对应 (N 节点 → N 个唯一显示名, naming.unique_map 是单射)
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
L2SET = set(A.l2_names())     # 与面板/数据空间同一份 L2 词表 (含阶段节点归一), 不在判据里另算
META_SET = {nm for nm, lay in LAYER_OF.items() if lay not in ("L2", "L3", "L4", "L5")}

# ① 单射
chk("① 工程节点名一一对应 (单射)", len(NAMESET) == len(rows), f"{len(NAMESET)} 名 / {len(rows)} 节点")

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

LAYERS = {"L2"}                     # 2026-10-17 老倪: 这两个窗口只保留 L2
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
    if not _tx or any(p == "—" or p not in L2SET for p in _tx):
        bad_tx.append((tp, tx))
    _rx = [p.strip() for p in rx.split(" / ") if p.strip()]
    for p in _rx:
        if p == "—":
            n_rx_dash += 1
        elif p in L2SET:
            n_rx_node += 1
        else:
            bad_rx.append((tp, p))

chk("③ Layer 全是 L2", not bad_layer, f"{len(bad_layer)} 违规 {bad_layer[:3]}")
chk("④ Topic 都在工程里定义 (mw_topic 或真值流归属节点 L2~L5)", not bad_topic,
    f"{len(bad_topic)} 违规 {bad_topic[:3]}")
chk("⑤ Tx 全是 L2 节点名", not bad_tx, f"{len(bad_tx)} 违规 {bad_tx[:3]}")
# 📚 2026-10-17 老倪: 「有个 —— 444 个, 没有分类的横杠, 不属于 L2, 在数据空间中, 全删掉」
chk("⑥ Rx 全是 L2 节点名 (没有横杠行)", not bad_rx and n_rx_dash == 0,
    f"{len(bad_rx)} 违规 {bad_rx[:3]} · 节点 {n_rx_node} / 横杠 {n_rx_dash}")

# ⑦ 可视化层/非 L2 节点不许出现在 Tx/Rx (老倪点名的 物理约束 / 前馈直方图)
_leaked = sorted({(tp, p) for tp, bad in ((b[0], b[1]) for b in bad_tx + bad_rx)
                  for p in [bad] if p in META_SET})
chk("⑦ Tx/Rx 里没有可视化层/meta 节点 (物理约束·前馈直方图…)", not _leaked,
    f"{_leaked[:4]}")

# ⑧ 数据空间页 (dds_space) 的话题表/节点表/报文表也只能有 L2
try:
    import dds_space as DS
    w = DS.build_widget()
    w.refresh()
    app.processEvents()
    _n_ch = w.t_ch.rowCount()
    _bad_ch = [w.t_ch.item(i, 1).text() for i in range(_n_ch)
               if w.t_ch.item(i, 1) and w.t_ch.item(i, 1).text() != "L2"]
    _bad_ms = [w.t_ms.item(i, 0).text() for i in range(w.t_ms.rowCount())
               if w.t_ms.item(i, 0) and w.t_ms.item(i, 0).text() != "L2"]
    _bad_nod = [x for x in (w.t_pj.item(i, 1).text() for i in range(w.t_pj.rowCount())
                            if w.t_pj.item(i, 1)) if not x.startswith("L2 ·")]
    chk("⑧ 数据空间页 话题/节点/报文 都只有 L2",
        _n_ch > 0 and not _bad_ch and not _bad_ms and not _bad_nod,
        f"话题 {_n_ch} 行 · 非L2 {len(_bad_ch)} · 报文非L2 {len(_bad_ms)} · 节点非L2 {len(_bad_nod)}")
except Exception as e:                                                        # noqa: BLE001
    chk("⑧ 数据空间页 话题/节点/报文 都只有 L2", False, f"{type(e).__name__}: {e}")


print()
print(f"Trace 行 {v.tb.rowCount()} · 话题 {len({(v.tb.item(r,2).toolTip() or '').split('话题: ')[-1].split(chr(10))[0] for r in range(v.tb.rowCount())})}")
if bad:
    print(f"❌ 失败: {bad}")
    sys.exit(1)
print(f"✅ 全部通过 ({ok} 项)")
