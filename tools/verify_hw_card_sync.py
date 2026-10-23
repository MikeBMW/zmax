#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_hw_card_sync.py — 判据: 首页「硬件资源」卡的数字必须与底部状态带逐项相等

做法: 取同一份 8796 /status/all → ①底部状态带解析器 StatusPanel.modes() 得槽位
      → ②HardwareCard._sync_strip() 贴到卡上 → 逐项比对 (名称/比例/文字)。
用法: QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/verify_hw_card_sync.py [--shot png]
"""
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, "/home/ubuntu/zmax/tools/gui")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtWidgets import QApplication  # noqa: E402

URL = os.environ.get("ZMAX_STATUS_URL", "http://127.0.0.1:8796/status/all")
app = QApplication(sys.argv)
import studio          # noqa: E402
import status_panel    # noqa: E402

ok = True
def chk(name, cond, extra=""):
    global ok
    ok = ok and bool(cond)
    print("%s %s%s" % ("✓" if cond else "✗", name, (" :: " + str(extra)) if extra else ""))

with urllib.request.urlopen(URL, timeout=5) as r:
    payload = json.loads(r.read().decode("utf-8", "replace"))

pn = status_panel.StatusPanel(poll=False)
pn.feed(payload)
cur = pn.current()
slots = cur.get("slots") or []
print("档位 %s · 底部状态带槽位: %s" % (cur.get("key"), slots))

card = studio.HardwareCard()
card.resize(1500, card.sizeHint().height())
card.show()
app.processEvents()
card._sync_strip(payload)
app.processEvents()

got = []
for key in ("gpu", "vram", "cpu", "mem"):
    rg = card._visual.rings[key]
    got.append((rg.caption, round((rg._frac or 0) * 100.0, 3) if rg._frac is not None else None, rg._text))
if len(slots) > 4:
    b = card._visual.bars["disk"]
    got.append((b.caption, round((b._frac or 0) * 100.0, 3) if b._frac is not None else None, b._text))
print("卡片实际显示   : %s" % (got,))

for i, sl in enumerate(slots[:4]):
    cap, frac, txt = sl[0], sl[1], sl[2]
    g = got[i]
    chk("槽%d 名称 %s == %s" % (i, g[0], cap), g[0] == cap)
    exp = str(txt) if txt not in (None, "") else (("%.0f%%" % float(frac)) if frac is not None else "—")
    chk("槽%d 文字 %r == %r" % (i, g[2], exp), g[2] == exp)
    ef = None if frac is None else round(float(frac), 3)
    chk("槽%d 比例 %s == %s" % (i, g[1], ef), (None if g[1] is None else round(g[1], 3)) == ef)
if len(slots) > 4:
    cap, frac, txt = slots[4][0], slots[4][1], slots[4][2]
    chk("第5槽(条) 名称 %s == %s" % (got[4][0], cap), got[4][0] == cap)
    chk("第5槽(条) 文字 %r == %r" % (got[4][2], str(txt)), got[4][2] == str(txt))

# 时间戳口径: 卡上时间必须是载荷 ts, 不是本机当前时间
chk("采样时间取自载荷 ts", card.lb_ts.text().startswith(
    time.strftime("%H:%M:%S", time.localtime(float(payload.get("ts") or 0)))), card.lb_ts.text())
chk("标注同源 8796", "8796" in card.lb_ts.text() or "8796" in card._visual.lb_dev.text(),
    card._visual.lb_dev.text())

if "--shot" in sys.argv:
    p = sys.argv[sys.argv.index("--shot") + 1]
    card.grab().save(p)
    print("  截图 -> %s" % p)
print("总高 %d px (宽 1500)" % card.height())
try:
    card._worker.stop()
except Exception:
    pass
print("SYNC SELFTEST %s" % ("PASS" if ok else "FAIL"))
sys.stdout.flush()
os._exit(0 if ok else 1)
