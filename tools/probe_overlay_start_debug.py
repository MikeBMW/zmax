#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""定位: 画布「🧩 场景叠加」为什么 start 返回 False (复现 verify_scene_overlay_canvas 的 ④ 失败)

⚠️ studio.py 会把 sys.stdout 重定向进 GUI 日志面板 ⇒ 本探针所有结论写 /tmp/ovdbg.txt
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = "/home/ubuntu/zmax"
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))

_F = open("/tmp/ovdbg.txt", "w", encoding="utf-8")


def P(*a):
    print(*a, file=_F, flush=True)


try:
    from PyQt5.QtWidgets import QApplication
    app = QApplication(sys.argv)
    import studio as ST

    win = ST.StudioMainWindow()
    win.show()
    for _ in range(8):
        app.processEvents()
    sim = win.stack.widget(10)
    P("simulink 页类:", type(sim).__name__)
    sim.load_flow_file(os.path.join(ROOT, "flows", "state_space_obs.json"), confirm=False)
    for _ in range(5):
        app.processEvents()
    P("_items 数:", len(sim._items))
    it = sim._ov_live_target_item()
    P("_ov_live_target_item() →", None if it is None else (it.node.get("id"), it.node.get("name")))
    P("OV_LIVE_PORT =", getattr(sim, "OV_LIVE_PORT", None))
    import urllib.request
    for nm in ("arm", "local", "local2"):
        try:
            with urllib.request.urlopen("http://127.0.0.1:%d/snapshot/overlay_%s.jpg" % (sim.OV_LIVE_PORT, nm), timeout=4) as r:
                b = r.read()
            P("  overlay_%s: %d bytes · JPEG=%s" % (nm, len(b), b[:2] == b"\xff\xd8"))
        except Exception as e:                                              # noqa: BLE001
            P("  overlay_%s: 异常 %s" % (nm, str(e)[:90]))
    r = sim.start_canvas_live_overlay()
    P("start_canvas_live_overlay() →", r)
    P("_ov_live =", {k: v for k, v in (getattr(sim, "_ov_live", {}) or {}).items() if k in ("on", "node_id", "srcs", "offline")})
    import time
    for _ in range(50):
        app.processEvents()
        time.sleep(0.1)
    P("_ov_live 复查: on=%s frames=%s" % ((sim._ov_live or {}).get("on"), (sim._ov_live or {}).get("frames")))
    P("线程检查: 当前线程 is 主线程 =", __import__("PyQt5.QtCore", fromlist=["QThread"]).QThread.currentThread() is win.thread())
except Exception:                                                            # noqa: BLE001
    import traceback
    P("探针崩溃:\n" + traceback.format_exc())
_F.close()
os._exit(0)
