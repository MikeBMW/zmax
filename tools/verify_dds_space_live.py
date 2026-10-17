# -*- coding: utf-8 -*-
"""判据: 全局数据空间(数据空间页) 必须真的在实时刷新 —— 不是"能打开"就算。

老倪 2026-10-17: 「全局数据空间，时局怎么不实时更新了」
根因(实测): dds_space.refresh() 里用 _naming, 但 import 写在另一个函数的局部作用域 ⇒
每次刷新 NameError; build_widget 一开始就抛 ⇒ 页面要么空、要么冻在第一次内容。

判据 (离屏, 不碰在跑的控制台):
  ① build_widget 能建起来 (不抛)
  ② 连刷两拍不抛异常
  ③ 状态行里的 「live 龄」真的在变小 (证明读的是现写文件, 不是缓存/常量)
  ④ 四张表都有数据 (告警/信号/节点/报文), 不是空壳
  ⑤ live.json 本身是新鲜的 (<15s), 否则先报数据源不给判 UI
"""
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "tools", "gui"), os.path.join(ROOT, "src")]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

LIVE = os.path.join(ROOT, "zmax_data", "dataspace", "live.json")
ok, bad = 0, []


def chk(name, cond, extra=""):
    global ok
    if cond:
        ok += 1
        print(f"✅ {name}{(' · ' + extra) if extra else ''}")
    else:
        bad.append(name)
        print(f"❌ {name}{(' · ' + extra) if extra else ''}")


# ⑤ 数据源新鲜度 (先排除"源就停了"的情况, 不然会误判 UI)
age = time.time() - os.path.getmtime(LIVE) if os.path.isfile(LIVE) else 1e9
chk("live.json 新鲜 (<15s)", age < 15, f"{age:.1f}s")

from PyQt5.QtWidgets import QApplication, QTableWidget                        # noqa: E402

app = QApplication.instance() or QApplication([])
import dds_space as DS                                                        # noqa: E402

err = ""
try:
    w = DS.build_widget()
except Exception as e:                                                        # noqa: BLE001
    err = f"{type(e).__name__}: {e}"
chk("① build_widget 建得起来", not err, err or "OK")
if err:
    print(f"\n❌ 失败: {bad}")
    sys.exit(1)


def live_age():
    t = re.sub(r"<[^>]+>", "", w.lbl.text())
    m = re.search(r"live 龄\s*([\d.]+)s", t)
    return float(m.group(1)) if m else -1.0


e2 = ""
a1 = live_age()
time.sleep(3.0)
app.processEvents()
try:
    w.refresh()
    app.processEvents()
except Exception as e:                                                        # noqa: BLE001
    e2 = f"{type(e).__name__}: {e}"
chk("② 连续刷新不抛异常", not e2, e2 or "OK")
a2 = live_age()
chk("③ live 龄在变小 (真刷新)", a2 >= 0 and a1 >= 0 and a2 < a1, f"{a1}s → {a2}s")

tabs = w.findChildren(QTableWidget)
rows = [t.rowCount() for t in tabs]
chk("④ 四张表都有数据", len(tabs) >= 4 and all(r > 0 for r in rows[:4]),
    f"表数 {len(tabs)} · 行数 {rows[:4]}")

print()
if bad:
    print(f"❌ 失败: {bad}")
    sys.exit(1)
print(f"✅ 全部通过 ({ok} 项)")
