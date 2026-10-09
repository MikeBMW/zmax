#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ss_bypass_station_smoke.py — 🛰 工位总览 station 带 离屏冒烟 (真起窗, 不改真机状态)

只做: 起 SSBypassView → 让 1.5s 轮询真的跑几轮 (拉真 station /station/status) →
读回**界面上实际显示**的四路数字 + 截图。另含两段注入测试 (都明确标注是假的):
  · 【假数据】注入一份构造的 status → 验证渲染路径 (数字来自假 JSON)
  · 【离线态】注入一个原始错误码 → 验证红色离线显示
不碰控制台 (独立进程), 不写任何真机状态, 不动既有数据源文件。
"""
import os
import re
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, "/home/ubuntu/zmax/tools/gui")

from PyQt5 import QtWidgets                # noqa: E402

import ss_bypass_view as V                  # noqa: E402

OUT = "/home/ubuntu/.hermes/cache/scratch"
os.makedirs(OUT, exist_ok=True)

app = QtWidgets.QApplication(sys.argv)
win = V.SSBypassView()
win.resize(1720, 1180)
win.show()
app.processEvents()


def pump(sec):
    t0 = time.time()
    while time.time() - t0 < sec:
        app.processEvents()
        time.sleep(0.05)


print("=" * 74)
print("① 真起窗 + 1.5s 轮询真的跑几轮 (拉真 station), 等 5s …")
t0 = time.time()
while time.time() - t0 < 5.0:               # 至少 3 个 tick + 后台线程回交
    app.processEvents()
    time.sleep(0.05)
print("   station 配置:", win.station_cfg)

L = win.station_labs
disp = {k: L[k].text() for k in ("cam", "tcp", "auth", "robot", "peers", "ledger")}
print("\n② 界面实际显示 (逐行):")
for k in ("cam", "tcp", "auth", "robot", "peers", "ledger"):
    print("   %-7s : %s" % (k, disp[k]))

png_live = os.path.join(OUT, "ss_bypass_station_live.png")
win.grab().save(png_live)
print("\n③ 截图 (真数据, 可直接打开):", png_live)

# ── 四个数字 (从界面文本里真解析出来, 不是另算一份) ──────────────────────────
def grp(pat, s, cast=float):
    m = re.search(pat, s)
    return cast(m.group(1)) if m else None

n_online = grp(r"在线 (\d+)/", disp["cam"], int)
n_total = grp(r"在线 \d+/(\d+)", disp["cam"], int)
age_max = grp(r"最大帧龄 (-?\d+)s", disp["cam"], float)
tcp3 = re.search(r"x=([-\d.]+) y=([-\d.]+) z=([-\d.]+)", disp["tcp"])
auth_left = grp(r"剩余 (-?\d+)s", disp["auth"], float)

print("\n④ 【截图里那四个数字】(live 真实数据):")
print("   (1) 六路相机在线数        = %s/%s" % (n_online, n_total))
print("   (2) 六路相机最大帧龄      = %ss" % age_max)
print("   (3) TCP 位姿 x/y/z        = %s" % (list(tcp3.groups()) if tcp3 else None))
print("   (4) 授权剩余秒            = %ss  (armed=%s)"
      % (auth_left, "已授权" in disp["auth"]))
print("   + 机器人 operation/mode   = %s" % disp["robot"])

# ── 注入假 status (验证渲染路径; 明确标注假的) ────────────────────────────────
print("\n" + "=" * 74)
print("⑤ 【注入假数据 · FAKE · 非真实】status → 验证渲染路径")
FAKE = {
    "stats": {"arm": {"online": True, "age_s": 1.0}, "local": {"online": True, "age_s": 2.0},
              "local2": {"online": False, "age_s": -1.0}, "depth": {"online": True, "age_s": 3.0},
              "aoi_gold": {"online": True, "age_s": 4.0}, "aoi_surface": {"online": False, "age_s": -1.0}},
    "ctl": {"tcp": {"xyz": [1.234, -5.678, 9.012], "age_s": 0.5},
            "auth": {"armed": True, "left_s": 123.0},
            "robot": {"operation": "FAKE-moving", "mode": "FAKE-auto"}},
}
win._station_render_status(FAKE, "")
app.processEvents()
for k in ("cam", "tcp", "auth", "robot"):
    print("   %-7s : %s" % (k, L[k].text()))
png_fake = os.path.join(OUT, "ss_bypass_station_FAKE_injected.png")
win.grab().save(png_fake)
print("   截图 (假数据, 文件名人肉标注 FAKE):", png_fake)
print("   期望: 在线 4/6 · 最大帧龄 4s · x=1.234 y=-5.678 z=9.012 · 已授权 剩余 123s")

# ── 注入离线态 (附原始错误码) ────────────────────────────────────────────────
print("\n" + "=" * 74)
print("⑥ 【离线态】注入原始错误码 → 验证红色离线 (不静默)")
RAW_ERR = "URLError <urlopen error [Errno 111] Connection refused>"
win._station_render_status(None, RAW_ERR)
app.processEvents()
for k in ("cam", "tcp", "auth", "robot"):
    print("   %-7s : %s" % (k, L[k].text()))
png_off = os.path.join(OUT, "ss_bypass_station_offline.png")
win.grab().save(png_off)
print("   截图 (离线态):", png_off)

# ── peers 渲染 (注入假 peers 文件 + 假台账, 都标注假的) ──────────────────────
print("\n" + "=" * 74)
print("⑦ 【注入假文件 · FAKE】hil_peers.json + station_plan_ledger.jsonl 末行 → 验证渲染")
tmpd = tempfile.mkdtemp(prefix="ssst_", dir=OUT)
peers_p = os.path.join(tmpd, "hil_peers.json")
import json
with open(peers_p, "w", encoding="utf-8") as f:      # L5 新鲜, 终端超 30s ⇒ 应判离线
    json.dump({"peers": [{"name": "L5", "kind": "scene_vlm", "age_s": 3.0},
                         {"name": "终端", "kind": "hermes", "age_s": 95.0}]}, f, ensure_ascii=False)
ledg_p = os.path.join(tmpd, "station_plan_ledger.jsonl")
with open(ledg_p, "w", encoding="utf-8") as f:
    f.write(json.dumps({"ts": "2026-10-09 13:30:00", "kind": "plan", "target": "space1",
                        "plan_id": "FAKE-pl42", "segments": 3, "ok": True}, ensure_ascii=False) + "\n")
_o1, _o2 = V.STATION_HIL_PEERS_PATH, V.STATION_LEDGER_PATH
V.STATION_HIL_PEERS_PATH, V.STATION_LEDGER_PATH = peers_p, ledg_p
win._station_hil_ok, win._station_hil_err = True, ""
win._station_render_peers()
win._station_render_ledger()
app.processEvents()
print("   peers  :", L["peers"].text())
print("   ledger :", L["ledger"].text())
print("   期望: L5 🟢 · 终端 🔴(95s>30s) · hil ✅ 在线 | 台账 plan_id=FAKE-pl42 …")
V.STATION_HIL_PEERS_PATH, V.STATION_LEDGER_PATH = _o1, _o2     # 还原, 不留假路径

print("\n⑧ 真值复查 — 台账文件当前是否真实存在:",
      os.path.exists(V.STATION_LEDGER_PATH),
      "| hil_peers.json:", os.path.exists(V.STATION_HIL_PEERS_PATH))
win.close()
print("已关闭 (未影响控制台, 未改任何真机状态)")
print("=" * 74)
