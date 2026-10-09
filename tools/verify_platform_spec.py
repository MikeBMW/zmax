#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_platform_spec.py — 📋 工程数据库 + 功能清单页 判据 (2026-10-09 老倪)

判据 (全绿才算交付):
  ① 单一数据库文件: data/database/zmax_engineering.db 存在, 且 data/database 只有库 + 说明/清单
  ② 库内容: 平台/产品/产品特征/子系统/功能/三轴/标定/模块/模块代码/能力/验证项 全部非空且数目对得上真源
  ③ 同步判据: engineering_db.py check rc=0 (特征→子系统·功能→模块·三轴覆盖·段齐·真源一致)
  ④ 功能清单页 (离屏真建): 页签齐 (Z-MAX 平台 / System 2 / System 1 / System 0 / 平台支撑),
     Z-MAX 页有产品 Z700/Z100 与 18 条产品特征; 各系统页有 三轴 + 功能清单
  ⑤ 主窗口接线: 侧栏 Z-MAX 卡在 System 2 之上; 点 zmax/sys2/sys1/sys0 → 切到功能清单页并选中对应页签
  ⑥ 解耦: 换库即换工程 —— 复制库到临时路径, 用 PlatformSpecPage(db_path=临时库) 能独立加载出同样内容
用法: QT_QPA_PLATFORM=offscreen env -u PYTHONPATH gui-venv311/bin/python tools/verify_platform_spec.py
"""
import json
import os
import shutil
import subprocess
import re
import sys

ROOT = "/home/ubuntu/zmax"
PY = os.path.join(ROOT, "gui-venv311/bin/python")
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

DB = os.path.join(ROOT, "data", "database", "zmax_engineering.db")
FAIL = []


def chk(c, msg):
    print(("  ✅ " if c else "  ❌ ") + str(msg), flush=True)
    if not c:
        FAIL.append(str(msg))


print("① 单一数据库文件", flush=True)
chk(os.path.exists(DB), "库在: %s (%.2f MB)" % (DB, (os.path.getsize(DB) / 1048576) if os.path.exists(DB) else 0))
_dd = os.path.join(ROOT, "data", "database")
_files = sorted(os.listdir(_dd)) if os.path.isdir(_dd) else []
chk(all(x.endswith((".db", ".md", ".txt", ".json", ".jsonl")) for x in _files),
    "data/database/ 内容: %s" % _files)

print("② 库内容 (真源 ↔ 库 数目)", flush=True)
import engineering_db as ED                                                     # noqa: E402
D = ED.load(DB)
plat = json.load(open(ED.PLATFORM_SRC, encoding="utf-8"))
chk(len(D["products"]) == len(plat["products"]) and len(D["products"]) == 2,
    "平台产品 %d 个: %s" % (len(D["products"]), [x["product_id"] for x in D["products"]]))
chk(len(D["product_features"]) == len(plat["product_features"]) and len(D["product_features"]) >= 15,
    "产品特征清单 %d 条" % len(D["product_features"]))
chk(len(D["subsystems"]) >= 4, "子系统 %d 个: %s" % (len(D["subsystems"]),
                                                    [x["system_id"] for x in D["subsystems"]]))
chk(len(D["functions"]) == len(D["canvas"]["nodes"]) and len(D["functions"]) >= 70,
    "功能清单 %d 条 == 画布功能节点 %d" % (len(D["functions"]), len(D["canvas"]["nodes"])))
chk(all(len(D["axes"].get(s, {}).get(a, [])) > 0 for s in ("sys2", "sys1", "sys0")
        for a in ("cfg", "cal", "dia")), "三个子系统 x 三轴 全部非空")
chk(len(D["calib"]) >= 30, "标定参数 %d 条" % len(D["calib"]))
chk(len(D["modules"]) >= 70 and len(D["module_code"]) >= 70,
    "模块 %d 个 · 其中链到引擎代码 %d 个" % (len(D["modules"]), len(D["module_code"])))
chk(len(D["capabilities"]) >= 30, "能力库 (feature.dbc) %d 条" % len(D["capabilities"]))
chk(len(D["verification"]) >= 50, "验证/诊断项 (FEATURES) %d 条" % len(D["verification"]))
_sec = set(D["project"].keys())
chk({"canvas", "pane", "calib", "measure", "mparam", "task", "meta"} <= _sec,
    "工程 7 段齐 (实取 %d 段)" % len(_sec))

print("③ 同步判据 (engineering_db.py check)", flush=True)
env = dict(os.environ)
env["QT_QPA_PLATFORM"] = "offscreen"
env.pop("PYTHONPATH", None)
r = subprocess.run([PY, os.path.join(ROOT, "tools/engineering_db.py"), "check"], capture_output=True,
                   text=True, env=env, cwd=ROOT, timeout=600)
for ln in [x for x in (r.stdout or "").splitlines() if x.strip().startswith(("  ✅", "  ❌", "✅", "❌"))]:
    print("     " + ln, flush=True)
chk(r.returncode == 0, "engineering_db check rc=%d" % r.returncode)

print("④ 功能清单页 (离屏真建)", flush=True)
from PyQt5.QtWidgets import QApplication                                          # noqa: E402

app = QApplication.instance() or QApplication(sys.argv[:1])
from platform_spec import PlatformSpecPage                                        # noqa: E402

pg = PlatformSpecPage()
tabs = [pg.tabs.tabText(i) for i in range(pg.tabs.count())]
for want in ("Z-MAX", "System 2", "System 1", "System 0"):
    chk(any(want in t for t in tabs), "页签含 %s (共 %s)" % (want, tabs))
chk(pg.select_system("zmax") and "Z-MAX" in pg.tabs.tabText(pg.tabs.currentIndex()),
    "select_system('zmax') → 选中 Z-MAX 平台页")
_payload = pg.current_payload()
chk(len(_payload.get("products", [])) == 2 and len(_payload.get("product_features", [])) >= 15,
    "Z-MAX 页数据: %d 产品 / %d 产品特征" % (len(_payload.get("products", [])),
                                            len(_payload.get("product_features", []))))
pg.select_system("sys2")
_p2 = pg.current_payload()
chk(len(_p2.get("functions", [])) == 30 and len(_p2.get("axes", {}).get("cfg", [])) > 0,
    "System 2 页数据: %d 功能 · 三轴 cfg%d/cal%d/dia%d" % (
        len(_p2.get("functions", [])), len(_p2.get("axes", {}).get("cfg", [])),
        len(_p2.get("axes", {}).get("cal", [])), len(_p2.get("axes", {}).get("dia", []))))

print("⑤ 主窗口接线 (侧栏 Z-MAX 卡在 System 2 之上 · 点击开清单)", flush=True)
import studio as ST                                                               # noqa: E402

win = ST.StudioMainWindow()
for _ in range(80):
    app.processEvents()
    if getattr(win, "simulink", None) is not None:
        break
    import time as _t
    _t.sleep(0.2)
sb = win.sidebar
chk(hasattr(sb, "zmax") and hasattr(sb, "sys2"), "侧栏有 Z-MAX 卡与 System 2 卡")
_cards = [c.layer_id for c in sb.findChildren(ST.SystemLayerCard)] if hasattr(ST, "SystemLayerCard") else []
if _cards:
    chk(_cards.index("zmax") < _cards.index("sys2"), "Z-MAX 卡排在 System 2 之上 (%s)" % _cards)
    chk(_cards == ["zmax", "sys2", "sys1", "sys0", "spec", "params"],
        "侧栏卡序 = 产品/系统 2·1·0/功能清单/参数中心(最下) (%s)" % _cards)
chk(getattr(win, "spec", None) is not None and "spec" in win.modules, "主窗口已挂「功能清单」页")
for tgt, want in (("zmax", "Z-MAX"), ("sys2", "System 2"), ("sys1", "System 1"), ("sys0", "System 0")):
    sb.layer_clicked.emit(tgt)               # 等价于点那张卡 (卡 clicked → layer_clicked)
    app.processEvents()
    ok = (win.stack.currentWidget() is win.spec) and (want in win.spec.tabs.tabText(win.spec.tabs.currentIndex()))
    chk(ok, "点 %-5s → 功能清单页选中「%s」" % (tgt, win.spec.tabs.tabText(win.spec.tabs.currentIndex())))

print("⑥ 解耦: 换库即换工程 (独立文件加载)", flush=True)
_tmp = os.path.join(ROOT, ".hermes_spec_db_%s.db" % os.getpid())
shutil.copy2(DB, _tmp)
try:
    pg2 = PlatformSpecPage(db_path=_tmp)
    chk(pg2.data is not None and len(pg2.data["functions"]) == len(D["functions"]),
        "用迁移过来的库 (独立文件) 加载出同样 %d 条功能" % (len(pg2.data["functions"]) if pg2.data else -1))
finally:
    os.path.exists(_tmp) and os.remove(_tmp)

# ⑦ 侧栏配色纪律 (老倪: 删黑色字体, 彩色不超过两种) + 卡上不留说明行
from PyQt5.QtWidgets import QLabel as _QL, QWidget as _QW
_cards_w = [w for w in win.sidebar.findChildren(_QW) if w.__class__.__name__ == "SystemLayerCard"]
_bad, _pal = {}, set()
for _l in win.sidebar.findChildren(_QL):
    for _h in re.findall(r"color:\s*(#[0-9a-fA-F]{6})", _l.styleSheet() or ""):
        _pal.add(_h.lower())
for _c in _cards_w:
    _cols = set()
    for _l in _c.findChildren(_QL):
        for _h in re.findall(r"color:\s*(#[0-9a-fA-F]{6})", _l.styleSheet() or ""):
            _cols.add(_h.lower()); _pal.add(_h.lower())
    if len(_cols) > 2:
        _bad[_c.layer_id] = sorted(_cols)
    if len(_c.findChildren(_QL)) > 4:
        _bad.setdefault(_c.layer_id, []).append("labels=%d(说明行没删净?)" % len(_c.findChildren(_QL)))
chk(_cards_w and not _bad, "每张卡 ≤2 色 且 无黑色说明行 (违规: %s)" % (_bad or "无"))
_same = {}
for _c in _cards_w:
    _b = re.findall(r"border:\s*\d+px\s+solid\s+(#[0-9a-fA-F]{6})", _c.styleSheet() or "")
    if not _b:
        continue
    _bc = _b[0].lower()
    for _l in _c.findChildren(_QL):
        if _bc in [h.lower() for h in re.findall(r"color:\s*(#[0-9a-fA-F]{6})", _l.styleSheet() or "")]:
            _same[_c.layer_id] = _bc
chk(not _same, "卡的边框色 ≠ 卡内字体色 (同色违规: %s)" % (_same or "无"))

chk(len(_pal) <= 2, "侧栏整体(卡+分组标题+页脚)配色 ≤2 种 (实际 %d 种: %s)" % (len(_pal), sorted(_pal)))

print(("✅ 全部通过 — 工程数据库 + 功能清单页 (9 项)" if not FAIL else
       "❌ 失败 %d 项: %s" % (len(FAIL), FAIL[:6])), flush=True)
sys.stdout.flush()
os._exit(1 if FAIL else 0)
