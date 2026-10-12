#!/usr/bin/env python3
"""判据: 配置中心「工程配置」页里能**立刻找到** 金手指点1 的实际位置数据 (AR 场景专用工程配置块)。

老倪 2026-10-12: 「我已经在配置中心的 TASK-07 激活的 AOI 任务, 现在要看到 金手指点1 的实际位置数据,
                应该在工程配置里, 用户能立刻找到 —— 搞一个专门对应 AR场景的 工程配置数据」

判定 (真起窗口 + 真点按钮, 不看返回值):
  ① ⚙️ 工程配置 那一页里有专门的「🥽 AR 场景 · 工程配置数据」块
  ② 表头 = 点位/X(m)/Y(m)/Z(m)/记录时间/更新/真源文件; 第一行就是 **金手指点1**
  ③ 表里 金手指点1 的 x/y/z 与台账真源 reports/aoi_points/金手指点1.json **逐位相同**
  ④ 该行有历史/来源 tooltip(记录时间 + 真源文件 + 更新次数)
  ⑤ 「📋 复制这张表」真点一下 → 剪贴板拿到的 TSV 里含金手指点1 的坐标
  ⑥ 「📄 存 CSV」真点一下 → 文件真的写出来了且内容含金手指点1
"""
from __future__ import annotations

import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

P = F = 0


def ck(cond, name, extra=""):
    global P, F
    if cond:
        P += 1
        print("  ✅ " + name + (("  · " + str(extra)) if extra else ""))
    else:
        F += 1
        print("  ⛔ " + name + (("  · " + str(extra)) if extra else ""))


from PyQt5.QtWidgets import QApplication  # noqa: E402

import veh6_config_page as V  # noqa: E402

app = QApplication.instance() or QApplication([])
page = V.build_config_center()

print("=== ① 工程配置页里有 AR 场景专用块 ===")
card = getattr(page, "ar_pts_card", None)
ck(card is not None, "页面里有 ar_pts_card(🥽 AR 场景 · 工程配置数据)")
tab_idx = page._tab_index_by_title("工程配置")
ck(tab_idx >= 0, "找到「⚙️ 工程配置」页", "tab %d" % tab_idx)
ck(tab_idx >= 0 and page.tabs.widget(tab_idx).findChild(type(card)) is not None if card is not None else False,
   "那个块就在「工程配置」页里")

print("\n=== ② 表头 + 第一行 = 金手指点1 ===")
tb = card.findChild(type(card.findChildren(__import__("PyQt5.QtWidgets", fromlist=["QTableWidget"]).QTableWidget)[0])) \
    if card is not None and card.findChildren(__import__("PyQt5.QtWidgets", fromlist=["QTableWidget"]).QTableWidget) else None
from PyQt5.QtWidgets import QTableWidget  # noqa: E402
tbs = card.findChildren(QTableWidget) if card is not None else []
ck(len(tbs) == 1, "块里只有一张表", "%d 张" % len(tbs))
tb = tbs[0] if tbs else None
if tb is not None:
    hdr = [tb.horizontalHeaderItem(c).text() for c in range(tb.columnCount())]
    ck(hdr == ["点位", "X (m)", "Y (m)", "Z (m)", "记录时间", "更新", "真源文件"], "表头齐", hdr)
    ck(tb.rowCount() >= 8, "点位行数 ≥8", tb.rowCount())
    r0 = [tb.item(0, c).text() for c in range(tb.columnCount())]
    ck(r0[0] == "金手指点1", "第一行就是金手指点1", r0)

    print("\n=== ③ 与台账真源逐位相同 ===")
    with open(os.path.join(ROOT, "reports", "aoi_points", "金手指点1.json"), encoding="utf-8") as f:
        j = json.load(f)
    want = ["%.6f" % j["pos"][0], "%.6f" % j["pos"][1], "%.6f" % j["pos"][2]]
    got = [r0[1], r0[2], r0[3]]
    ck(got == want, "x/y/z 与 reports/aoi_points/金手指点1.json 一致", "%s vs %s" % (got, want))
    ck(j["recorded_at"] in r0[4], "记录时间一致", r0[4])
    ck(r0[6].endswith("金手指点1.json"), "真源文件名一致", r0[6])

    print("\n=== ④ 行 tooltip 带来源/历史 ===")
    tip = tb.item(0, 0).toolTip() or ""
    ck("金手指点1" in tip and "reports/aoi_points" in tip and "次更新" in tip,
       "tooltip 有真源 + 更新记录", tip.replace("\n", " | ")[:110])

print("\n=== ⑤ 真点「📋 复制这张表」 ===")
btns = {b.text(): b for b in card.findChildren(__import__("PyQt5.QtWidgets", fromlist=["QPushButton"]).QPushButton)} if card is not None else {}
b_cp = next((b for t, b in btns.items() if "复制" in t), None)
ck(b_cp is not None, "找到复制按钮", list(btns))
if b_cp is not None:
    QApplication.clipboard().setText("")
    b_cp.click()
    txt = QApplication.clipboard().text()
    ck("金手指点1" in txt and want[0] in txt and "点位" in txt, "剪贴板拿到 TSV(含金手指点1 坐标)",
       txt.splitlines()[1] if len(txt.splitlines()) > 1 else txt[:80])
    ck("已复制" in (getattr(page, "out", None).toPlainText() if getattr(page, "out", None) else ""),
       "页面底部如实回报已复制")

print("\n=== ⑥ 真点「📄 存 CSV」 ===")
b_ex = next((b for t, b in btns.items() if "存 CSV" in t), None)
ck(b_ex is not None, "找到存 CSV 按钮")
if b_ex is not None:
    before = set(glob.glob(os.path.join(ROOT, "reports", "exports", "AR场景_示教点位_*.csv")))
    b_ex.click()
    after = set(glob.glob(os.path.join(ROOT, "reports", "exports", "AR场景_示教点位_*.csv")))
    new = sorted(after - before)
    ck(len(new) == 1, "写出了新的 CSV 文件", os.path.relpath(new[0], ROOT) if new else "没写出")
    if new:
        body = open(new[0], encoding="utf-8-sig").read()
        ck("金手指点1" in body and want[0] in body, "CSV 内容含金手指点1 坐标")

print("\n=== ⑦ 记住上次那一页(重启后回来还是「工程配置」) ===")
try:
    mk = os.path.join(ROOT, "zmax_data", "cc_last_tab.txt")
    os.makedirs(os.path.dirname(mk), exist_ok=True)
    with open(mk, "w", encoding="utf-8") as f:
        f.write(str(tab_idx))
    page2 = V.build_config_center()
    ck(page2.tabs.currentIndex() == tab_idx, "重建后自动回到「工程配置」页",
       "current=%d (工程配置=%d)" % (page2.tabs.currentIndex(), tab_idx))
    page2.tabs.setCurrentIndex(0)
    ck(open(mk, encoding="utf-8").read().strip() == "0", "切页会回写标记(下次按它恢复)",
       open(mk, encoding="utf-8").read().strip())
    with open(mk, "w", encoding="utf-8") as f:
        f.write(str(tab_idx))                      # 还原成"工程配置", 让老倪重启后直接看到
except Exception as e:                                                           # noqa: BLE001
    ck(False, "记住上次那一页", repr(e)[:120])

print("\n=== 汇总: PASS %d · FAIL %d ===" % (P, F))
sys.exit(0 if F == 0 else 1)
