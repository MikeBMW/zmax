#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_wave_noise.py — 判据: 波形是不是"一条线" (同钟 + 不叠趟 + 同 x 不跳变)。

跑法: QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python tools/probe_wave_noise.py [秒数]
前提: 3D 面板在回放 (signal 页读 trace_live.json)。
"""
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "gui"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5 import QtWidgets                     # noqa: E402

import canoe_graphic as cg                      # noqa: E402

secs = float(sys.argv[1]) if len(sys.argv) > 1 else 52.0
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
w = cg.CanoeGraphicWidget()
w.show()
t_end = time.time() + secs
while time.time() < t_end:
    app.processEvents()
    time.sleep(0.1)

st = w.store
print("趟号 %d · 新一趟清空次数 %d" % (st.lap, st.lap_clears))
cands = [k for k in st.keys() if ("ss_stage.idx8" in k) or ("接触" in k) or ("末端_x" in k)][:6]


def stat(k):
    b = st.bufs.get(k)
    if not b or not b.n:
        return None
    t, v = b.arrays()
    d = np.diff(t)
    dv = np.diff(v)
    same_x_jump = int(np.logical_and(np.abs(d) < 1e-9, np.abs(dv) > 0.5).sum())
    return dict(k=k, n=int(b.n), scene=bool(b.scene), x0=round(float(t[0]), 2), x1=round(float(t[-1]), 2),
                v_now=round(float(v[-1]), 1), 同x跳变=same_x_jump)


rows = [r for r in (stat(k) for k in cands) if r]
for r in rows:
    print(r)
ds = [r for r in rows if r["k"].startswith("ds.")]
tr = [r for r in rows if not r["k"].startswith("ds.")]
ok = True
if ds and tr:
    gap = abs(ds[0]["x1"] - tr[0]["x1"])
    print("主钟对齐: ds.x1=%.2f vs sstrace.x1=%.2f ⇒ 差 %.2fs" % (ds[0]["x1"], tr[0]["x1"], gap))
    ok = ok and gap < 5.0
bad_jump = [r for r in rows if r["同x跳变"] > 6]
print("同 x 上跳变的信号:", [r["k"] for r in bad_jump] or "无")
print("最近说明:", list(st.notes)[-2:])
print("结论:", "✅ 同钟且无同-x乱跳" if (ok and not bad_jump) else "❌ 还有问题 (见上)")
