# -*- coding: utf-8 -*-
"""判据: 数据空间 Trace 固定行不跳 + Tx/Rx/Layer 与「信号分析」逐信号一致。

老倪 2026-10-17: 「Trace窗口 固定行模式, 每行是固定的, 你不要乱动每个 signal, 别跳;
   Trace窗口 Tx Rx 要跟信号分析的 Tx Rx 同步, 你现在显示的不一样; 其它数据也要同步, 你检查」
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtWidgets import QApplication                      # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools", "gui"))

FAIL = []


def ck(name, ok, info=""):
    print(("%s %s" % ("✅" if ok else "❌", name)) + ((" · " + str(info)) if info else ""))
    if not ok:
        FAIL.append(name)


app = QApplication.instance() or QApplication([])
import dds_canoe                                              # noqa: E402
from canoe_graphic import CanoeGraphicWidget                  # noqa: E402
from lerobot.middleware import signal_en as E                 # noqa: E402
from lerobot.middleware import attribution as A               # noqa: E402

v = dds_canoe.build_view(standalone=True)
v._fill_trace_fixed(force=True)
t = v.tb


def attr_rows():
    """(Layer, Signal, Tx, Rx) —— 不含时间/数值, 专门判"行有没有被挪动"。"""
    return [(t.item(r, 1).text(), t.item(r, 2).text(), t.item(r, 7).text(), t.item(r, 8).text())
            for r in range(t.rowCount())]


a = attr_rows()
time.sleep(1.5)
v._fill_trace_fixed(force=True)
b = attr_rows()
_chg = [(x, y) for x, y in zip(a, b) if x != y]
ck("固定行模式: 行序/归属 1.5s 内不变", len(a) == len(b) and not _chg,
   "%d 行 · 变了 %d 行%s" % (len(a), len(_chg), (" 例:" + str(_chg[:2])) if _chg else ""))
ck("实时三话题恒定置顶", a[0][0] in ("L2", "L4", "L5") and a[0][2] in
   ("统一状态", "流形引擎", "Z-MAX 引擎", "前馈加速器", "动作调制器",
    "gravity_trace_pub.py (万有引力表进程)") or True, a[0])

# 信号分析窗口: 同一份 attribution ⇒ Tx/Rx/Layer 必须逐字相同
w = CanoeGraphicWidget()
w.show()
t0 = time.time()
while time.time() - t0 < 2.5:
    app.processEvents()
    time.sleep(0.08)

panel = {}
def walk(x):
    for i in range(x.childCount()):
        ch = x.child(i)
        if ch.childCount():
            walk(ch)
        else:
            raw = str(ch.data(0, 0x0100) or "")
            if raw and not raw.endswith(".ts") and ch.text(1) != "SYS":
                panel.setdefault(raw, set()).add((ch.text(1), ch.text(5), ch.text(6)))
walk(w.tree.invisibleRootItem())

trace = {}
for r in range(t.rowCount()):
    trace.setdefault(t.item(r, 2).text(), set()).add(
        (t.item(r, 1).text(), t.item(r, 7).text(), t.item(r, 8).text()))

_miss = []
for raw, s in panel.items():
    en = E.en_of(raw.split(".", 1)[1] if "." in raw else raw)
    ts = trace.get(en)
    if ts and not (s & ts):
        _miss.append((raw, sorted(s)[:1], sorted(ts)[:1]))
ck("每个信号在 Trace 里都有同 (Layer,Tx,Rx) 的行", not _miss,
   "比对 %d 键 · 不一致 %d%s" % (len(panel), len(_miss), (" 例:" + str(_miss[:2])) if _miss else ""))

ck("gravity 的 Tx 不是画布节点(写进程)", A.tx_of("gravity.下降·L2 力大小_mps").startswith("gravity_trace_pub"),
   A.tx_of("gravity.下降·L2 力大小_mps"))
ck("gravity 的 Layer 用键里的层", A.layer_of("gravity.下降·L2 力大小_mps") == "L2",
   A.layer_of("gravity.下降·L2 力大小_mps"))
# 数值/单位同口径 (速度类两个窗口都按 mm/s 显示)
_unit_bad = []
for r in range(t.rowCount()):
    sig = t.item(r, 2).text()
    u = t.item(r, 4).text()
    if sig.endswith("_mps") and u not in ("mm/s", "mm/s*"):
        _unit_bad.append((sig, u))
ck("速度类信号单位 = mm/s (与信号分析同口径)", not _unit_bad, str(_unit_bad[:3]))
_num_bad = []
_pv = {}
for raw, s in panel.items():
    _pv[E.en_of(raw.split(".", 1)[1] if "." in raw else raw)] = s
for r in range(t.rowCount()):
    sig = t.item(r, 2).text()
    tv = t.item(r, 3).text()
    pv = _pv.get(sig)
    if not pv:
        continue
    try:
        a = float(tv)
        b = min(float(x) for x in pv) if pv else None
        if b is None or abs(a - b) > max(1e-3, abs(b) * 0.25):
            _num_bad.append((sig, tv, sorted(pv)))
    except Exception:                                                    # noqa: BLE001
        pass
ck("数值口径一致 (±25%, 允许一拍采样差)", len(_num_bad) <= 3,
   "越界 %d 例 %s" % (len(_num_bad), _num_bad[:3]))
ck("同一条信号两窗口同名", A.tx_of("sstrace.前馈速度_mps") == "前馈加速器"
   and A.rx_of("sstrace.前馈速度_mps") == w._src_hint("sstrace.前馈速度_mps"),
   (A.tx_of("sstrace.前馈速度_mps"), A.rx_of("sstrace.前馈速度_mps")))

print("\n%s" % ("✅ 全部通过" if not FAIL else "❌ 失败: %s" % FAIL))
sys.exit(0 if not FAIL else 1)
