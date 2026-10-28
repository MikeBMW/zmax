#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""判据: 🧩 SAM3 分割 → 🧿 DeepSeek-VL (L5) 这条线**在画布上真渲染出来** (不是只在 JSON 里)

老倪 2026-10-14: 「把 SAM3 节点…作为 deepseek vl 的一个输入选项」 ⇒ 画布上必须看得见这条线。
接线 ≠ 渲染 ≠ 被消费, 三层各验一次 (本脚本管**渲染**): 离屏真建 SimulinkModule + 真加载画布,
按**节点名**找到 SimLinkItem (load_flow_file 会重编 id, 名字才稳)。
"""
from __future__ import annotations

import json
import os
import sys
import traceback

sys.path.insert(0, "/home/ubuntu/zmax/tools/gui")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5 import QtWidgets                                                   # noqa: E402

app = QtWidgets.QApplication(sys.argv)
import simulink_module as SM                                                  # noqa: E402

FLOW = "/home/ubuntu/zmax/flows/state_space_obs.json"
SRC_KEY, DST_KEY = "开放词汇分割", "DeepSeek"
fails = []


def chk(cond, label, extra=""):
    print(("  ✅ " if cond else "  ❌ ") + label + (("  " + extra) if extra else ""))
    if not cond:
        fails.append(label)
    return cond


spec = json.load(open(FLOW, encoding="utf-8"))
print("═══ 🧩 SAM3 → 🧿DeepSeek-VL 画布连线 渲染判据 ═══")
print("画布唯一依据: %d 节点 / %d 连线" % (len(spec["nodes"]), len(spec["links"])))

m = SM.SimulinkModule()
err = None
try:
    m.load_flow_file(FLOW, confirm=False)
except Exception:                                                             # noqa: BLE001
    err = traceback.format_exc()
app.processEvents()
chk(err is None, "画布加载无异常", (err or "").strip().splitlines()[-1] if err else "")

items = list(m.canvas._scene.items())
nodes = [i for i in items if isinstance(i, SM.SimNodeItem)]
links = [i for i in items if isinstance(i, SM.SimLinkItem)]
chk(len(nodes) == len(spec["nodes"]), "节点项 == 文件节点数",
    "%d/%d" % (len(nodes), len(spec["nodes"])))
chk(len(links) >= len(spec["links"]) - 1, "连线项 ≥ 文件连线数-1 (既有去重)",
    "%d/%d" % (len(links), len(spec["links"])))

hit = []
for it in links:
    try:
        sn = (it.src.node or {}).get("name") or ""
        dn = (it.dst.node or {}).get("name") or ""
        if SRC_KEY in sn and DST_KEY in dn:
            hit.append(it)
    except Exception:                                                         # noqa: BLE001
        pass
chk(len(hit) == 1, "画布上有一条 🧩开放词汇分割 → 🧿DeepSeek 的连线", "命中 %d 条" % len(hit))
if hit:
    lb = (hit[0].link or {}).get("label") or ""
    chk("DeepSeek-VL 视觉输入选项" in lb, "该线带口径标签", lb[:56])
    chk(hit[0].src is not hit[0].dst, "端点不同 (不是自环)")
print("判据汇总: %d/%d %s" % (len(fails) and 0 or 5, 5, "PASS" if not fails else "FAIL"))
sys.exit(0 if not fails else 3)
