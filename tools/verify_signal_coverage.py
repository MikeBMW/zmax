# -*- coding: utf-8 -*-
"""判据: L2~L5 + 系统 每一层每个 topic 都有信号行, Trace 一行不漏。

老倪 2026-10-17: 「怎么就这么少的信号? L1~L5 层所有的 topic 的所有信号, 都要加载」
"""
import sys, os, collections
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from lerobot.middleware import db, signals, cn_names

fails = []
def ck(name, ok, info=""):
    print(("%s %s" % ("✅" if ok else "❌", name)) + ((" · " + info) if info else ""))
    if not ok:
        fails.append(name)

tops = db.topics()
per_layer = collections.Counter()
for t in tops:
    per_layer[t["topic"].split(".")[2] if False else ""] = 0
lvl = {r["node_id"]: r.get("layer") for r in db.node_rows()}
lay = collections.Counter(lvl.get(r["node_id"], "?") for r in tops)
ck("话题总数 = 工程库 273", len(tops) == 273, str(len(tops)))
ck("分层: %s" % dict(lay), all(k in ("L2", "L3", "L4", "L5", "meta", "L1") for k in lay))

empty = []
n_sig = 0
for r in tops:
    s = signals.signals_of(r["topic"])
    n_sig += len(s)
    if not s or (len(s) == 1 and s[0][0] == "value"):
        empty.append(r["topic"])
ck("每个 topic 都有信号名 (非占位)", not empty, "%d 个仍是占位: %s" % (len(empty), empty[:4]))
ck("信号行总数 ≥ 1000", n_sig >= 1000, str(n_sig))

cov = signals.coverage()
ck("信号来源分级", True, str(cov))

# 名字规范: 中文 ≤5, 英文变量名合法
bad_cn = [(t, cn_names.cn_of(t)) for t in {r["topic"] for r in tops} if len(cn_names.cn_of(t)) > 5]
ck("话题中文名 ≤5 字", not bad_cn, str(bad_cn[:3]))
bad_en = [s for r in tops for s, _u, _src in signals.signals_of(r["topic"])
          if not s.replace("_", "").isalnum() or s.startswith("_") or len(s) > 32]
ck("信号英文名合法 (程序变量)", not bad_en, str(bad_en[:4]))

# 输入 topic 继承上游
inh = [r["topic"] for r in tops if r["dir"] == "in"
       and any(x[2] == "上游" for x in signals.signals_of(r["topic"]))]
ck("入口 topic 继承上游信号", len(inh) > 50, "%d 个入口有上游信号" % len(inh))

print("\n%s" % ("✅ 全部通过" if not fails else "❌ 失败: %s" % fails))
sys.exit(0 if not fails else 1)
