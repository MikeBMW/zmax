#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""render_strip_550b.py — 550B 两种连接方式的真实渲染取证 (离屏, 不动真源)

输出: 远程模式 / 局域网模式 各一张 PNG + OCR 文本, 用来核对「链」槽与硬件槽是否按模式换人。
用法: QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/render_strip_550b.py [--out 前缀]
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, "/home/ubuntu/zmax/tools/gui")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
import status_panel as sp  # noqa: E402

out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else "/tmp/strip550b"

base = json.loads(json.dumps(sp.REAL))
base["profile"] = {"key": "550B", "hardware": "4060", "hw_label": "4060"}
base["edge"] = {"online": True,
                "hw": {"cpu_pct": 45.9, "mem_pct": 45.7, "disk_pct": 6.5, "disk_free_gb": 889.2},
                "pipeline": {"on": True, "devices": {
                    "NPU": {"fps": 492.8, "duty_pct": 63.0, "models": ["yolo_peg_live", "intact_enc"]},
                    "GPU": {"fps": 369.8, "duty_pct": 98.3, "models": ["intact_pred"]}}}}

for tag, lan, desc in (("remote", {"mode": "remote", "local_ips": [], "hosts": {"intel": False}},
                        "远程模式 → 4060 本机硬件 + 在役层模型"),
                       ("lan", {"mode": "lan", "local_ips": ["192.168.23.50"], "hosts": {"intel": True}},
                        "局域网模式 → Intel 端侧硬件 + 端侧模型")):
    d = json.loads(json.dumps(base))
    d["lan"] = lan
    pn = sp.StatusPanel(poll=False)
    pn.feed(d)
    cur = pn.current()
    p = "%s_%s.png" % (out, tag)
    pn.grab().save(p)
    big = p.replace(".png", "_big.png")
    from PIL import Image
    im = Image.open(p)
    im.resize((im.width * 2, im.height * 2), Image.LANCZOS).save(big)
    txt = subprocess.run(["tesseract", big, "-", "-l", "eng+chi_sim"], capture_output=True, text=True).stdout
    print("── %s (%s)" % (tag, desc))
    print("   槽位: %s" % (cur["slots"],))
    print("   模型 chip: %s" % ([(c["layer"], c["name"], c["version"]) for c in pn._chips()],))
    print("   OCR: %s" % " ".join(txt.split()))
    print("   截图: %s" % p)
